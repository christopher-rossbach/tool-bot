"""Matrix client wrapper with async event handlers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional, Tuple

from nio import (
    AsyncClient,
    InviteEvent,
    LoginResponse,
    RoomMessageText,
    RoomMessageAudio,
    ReactionEvent,
    RoomMessageNotice,
    RedactionEvent,
    RoomMessagesResponse,
    RoomMemberEvent,
    SyncResponse,
)

from tool_bot.config import Config
from tool_bot.conversation import ConversationManager, MessageNode

logger = logging.getLogger(__name__)


class MatrixBot:
    def __init__(self, config: Config):
        self.config = config
        self.client: Optional[AsyncClient] = None
        self.bot_user_id: Optional[str] = None
        self.conversation_mgr = ConversationManager()
        from tool_bot.llm_engine import LLMEngine
        from tool_bot.web_search_client import WebSearchClient

        self.llm = LLMEngine(config)
        self.web_search = WebSearchClient()
        self.is_initial_sync = True
        self.whisper_model = None
        self.room_topics: Dict[str, Optional[str]] = {}

    @staticmethod
    def _get_default_system_prompt() -> str:
        """Return the default system prompt used across all contexts."""
        return (
            "You are a helpful and friendly assistant. Feel free to have normal conversations. "
            "You can also create Anki flashcards and Todoist todos when the user asks for them. "
            "IMPORTANT: Pay close attention to singular vs plural. If the user says 'a flashcard' or 'one flashcard', "
            "create exactly ONE. If they say '3 flashcards', create exactly THREE. Never add extra items. "
            "Use the web_search tool whenever a user asks for time-sensitive, volatile, or unlikely-to-be-memorized information so your answers stay current. "
            "If the flashcards you create ask for multiple facts at once (e.g., 'What are the colors of the French flag?'), ALWAYS include that number in parentheses after the question (e.g., 'What are the colors of the French flag? (3)') and then give the answer as a numbered list. (e.g., '1. Blue,\n 2. White,\n 3. Red')"
            "It is very important that the number of expected facts is mentioned in the question to help with later review."
        )

    @staticmethod
    def _is_thumbs_up(key: Optional[str]) -> bool:
        """Return True if the reaction key represents any thumbs-up variant.
        Handles base emoji, variation selector-16, and all skin tones.
        Also accepts common textual aliases like ":+1:".
        """
        if not key:
            return False
        # Normalize: remove VS16 (U+FE0F) and skin tone modifiers U+1F3FB..U+1F3FF
        modifiers = {chr(cp) for cp in range(0x1F3FB, 0x1F3FF + 1)}
        normalized = "".join(ch for ch in key if ch not in modifiers and ch != "\ufe0f")
        if normalized == "👍":
            return True
        # Common alias used in some clients
        if key.strip().lower() in {":+1:", "+1"}:
            return True
        return False

    @staticmethod
    def _parse_tool_proposal(body: str) -> Optional[Dict]:
        """Parse a tool proposal from bot message body."""
        import re

        # Try to parse flashcard proposal
        if "**Flashcard Proposal**" in body:
            proposal = {}
            if m := re.search(r"Type:\s*(\S+)", body):
                proposal["card_type"] = m.group(1)
            if m := re.search(r"Front:\s*(.+?)(?:\n|$)", body):
                proposal["front"] = m.group(1).strip()
            if m := re.search(r"Back:\s*(.+?)(?:\n|$)", body):
                proposal["back"] = m.group(1).strip()
            if m := re.search(r"Deck:\s*(.+?)(?:\n|$)", body):
                proposal["deck"] = m.group(1).strip()
            return proposal if proposal else None

        # Try to parse todo proposal
        elif "**Todo Proposal**" in body:
            proposal = {}
            if m := re.search(r"Task:\s*(.+?)(?:\n|$)", body):
                proposal["content"] = m.group(1).strip()
            if m := re.search(r"Due:\s*(.+?)(?:\n|$)", body):
                due = m.group(1).strip()
                if due:
                    proposal["due_string"] = due
            if m := re.search(r"Priority:\s*(\d+)", body):
                proposal["priority"] = int(m.group(1))
            if m := re.search(r"Project:\s*(.+?)(?:\n|$)", body):
                project = m.group(1).strip()
                if project:
                    proposal["project_name"] = project
            return proposal if proposal else None

        return None

    async def start(self) -> None:
        """Initialize and start the Matrix client."""
        self.client = AsyncClient(
            homeserver=self.config.matrix_homeserver,
            user=self.config.matrix_user or "",
        )

        # Register event callbacks
        self.client.add_event_callback(self.on_message, RoomMessageText)
        self.client.add_event_callback(self.on_audio, RoomMessageAudio)
        self.client.add_event_callback(self.on_reaction, ReactionEvent)
        self.client.add_event_callback(self.on_redaction, RedactionEvent)
        self.client.add_event_callback(self.on_invite, InviteEvent)
        self.client.add_event_callback(self.on_member_event, RoomMemberEvent)
        
        # Register sync callback to detect room topic changes
        self.client.add_response_callback(self.on_sync_response, SyncResponse)

        # Login
        if self.config.matrix_access_token:
            self.client.access_token = self.config.matrix_access_token
            self.client.user_id = self.config.matrix_user
            self.bot_user_id = self.config.matrix_user
            logger.info("Using access token for authentication")
        else:
            logger.info("Logging in with password...")
            response = await self.client.login(self.config.matrix_password)
            if isinstance(response, LoginResponse):
                self.bot_user_id = response.user_id
                logger.info(f"Logged in as {self.bot_user_id}")
            else:
                logger.error(f"Login failed: {response}")
                raise RuntimeError("Login failed")

        # Perform initial sync to get joined rooms
        logger.info("Performing initial sync to load room history...")
        self.is_initial_sync = True
        await self.client.sync(timeout=30000, full_state=True)

        # Load history for all joined rooms and respond to any pending user messages
        for room_id in self.client.rooms.keys():
            await self._load_room_history(room_id)
            await self._process_pending_messages(room_id)
            
            # Initialize room topic tracking
            room = self.client.rooms.get(room_id)
            if room:
                self.room_topics[room_id] = room.topic

        logger.info("History loaded. Starting sync loop...")
        self.is_initial_sync = False
        await self.client.sync_forever(timeout=30000, full_state=True)

    async def _load_room_history(self, room_id: str, limit: int = 10000) -> None:
        """Load recent room history to populate conversation tree."""
        if not self.client:
            return

        logger.info(f"Loading history for room {room_id}...")

        try:
            response = await self.client.room_messages(
                room_id=room_id,
                start="",
                limit=limit,
            )

            if not isinstance(response, RoomMessagesResponse):
                logger.warning(f"Failed to load history for {room_id}: {response}")
                return

            tree = self.conversation_mgr.get_tree(room_id)

            # Process events in chronological order (reverse)
            for event in reversed(response.chunk):
                # Handle text messages
                if hasattr(event, "body") and hasattr(event, "sender"):
                    content = event.source.get("content", {})
                    relates_to = content.get("m.relates_to", {})

                    reply_to = relates_to.get("m.in_reply_to", {}).get("event_id")
                    thread_root = (
                        relates_to.get("event_id")
                        if relates_to.get("rel_type") == "m.thread"
                        else None
                    )
                    replaces = (
                        relates_to.get("event_id")
                        if relates_to.get("rel_type") == "m.replace"
                        else None
                    )

                    node = tree.add_message(
                        event_id=event.event_id,
                        sender=event.sender,
                        content=event.body,
                        timestamp=event.server_timestamp,
                        reply_to=reply_to,
                        thread_root=thread_root,
                        replaces=replaces,
                        is_bot_message=(event.sender == self.bot_user_id),
                    )

                    # Parse tool proposals from all bot messages (for reactions to work)
                    if event.sender == self.bot_user_id:
                        node.tool_proposal = self._parse_tool_proposal(event.body)
                        if node.tool_proposal:
                            logger.debug(
                                f"Loaded proposal from history: {event.event_id}"
                            )

                # Handle reactions
                elif hasattr(event, "source"):
                    content = event.source.get("content", {})
                    if (
                        content.get("m.relates_to", {}).get("rel_type")
                        == "m.annotation"
                    ):
                        reacted_to = content.get("m.relates_to", {}).get("event_id")
                        key = content.get("m.relates_to", {}).get("key")
                        if reacted_to and key and hasattr(event, "sender"):
                            tree.add_reaction(reacted_to, key, event.sender)

            logger.info(f"Loaded {len(response.chunk)} events for room {room_id}")
        except Exception as e:
            logger.error(f"Error loading history for {room_id}: {e}")

    async def on_invite(self, room, event: InviteEvent) -> None:
        """Handle room invitations."""
        logger.info(f"Invited to room {room.room_id}")
        if self.client:
            await self.client.join(room.room_id)
            logger.info(f"Joined room {room.room_id}")
            # Load history for the newly joined room
            await self._load_room_history(room.room_id)
            # Set default system prompt in room topic if empty
            await self._ensure_room_prompt(room.room_id)

    async def on_member_event(self, room, event: RoomMemberEvent) -> None:
        """Handle room membership events.

        Leave the room if the bot is the only member remaining.
        """
        if not self.client:
            return

        # Skip during initial sync to avoid leaving rooms prematurely
        if self.is_initial_sync:
            return

        # Only check when someone leaves (not joins or other membership changes)
        if event.membership != "leave" and event.membership != "ban":
            return

        # Don't check if the bot itself is leaving
        if event.state_key == self.bot_user_id:
            return

        try:
            # Get current joined members in the room
            room_obj = self.client.rooms.get(room.room_id)
            if not room_obj:
                return

            # Count members excluding the bot
            other_members = [
                user_id for user_id in room_obj.users
                if user_id != self.bot_user_id
            ]

            if len(other_members) == 0:
                logger.info(f"Bot is alone in room {room.room_id}, leaving...")
                await self.client.room_leave(room.room_id)
                logger.info(f"Left room {room.room_id}")
        except Exception as e:
            logger.error(f"Error checking room members in {room.room_id}: {e}")

    async def on_sync_response(self, response: SyncResponse) -> None:
        """Handle sync responses to detect room topic changes.
        
        This callback is called after each sync and allows us to detect
        when room topics have changed, ensuring each room maintains its
        own independent system prompt.
        """
        if self.is_initial_sync:
            return
        
        if not self.client:
            return
        
        # Check all rooms for topic changes
        for room_id, room in self.client.rooms.items():
            current_topic = room.topic if room else None
            previous_topic = self.room_topics.get(room_id)
            
            # If topic changed and it's not the first time we're seeing this room
            if room_id in self.room_topics and current_topic != previous_topic:
                logger.info(f"Room topic changed in {room_id}: {current_topic[:100] if current_topic else '(empty)'}...")
            
            # Update our tracking
            self.room_topics[room_id] = current_topic

    async def _mark_as_read(self, room_id: str, event_id: str) -> None:
        """Mark a message as read by setting read markers."""
        if not self.client:
            return

        try:
            await self.client.room_read_markers(
                room_id=room_id,
                fully_read_event=event_id,
                read_event=event_id,
            )
            logger.debug(f"Marked message {event_id} as read in room {room_id}")
        except Exception as e:
            logger.warning(f"Failed to mark message as read: {e}")

    async def on_audio(self, room, event: RoomMessageAudio) -> None:
        """Handle audio/voice messages."""
        if event.sender == self.bot_user_id:
            return

        if self.config.allowed_users and event.sender not in self.config.allowed_users:
            return

        if self.is_initial_sync:
            logger.debug(f"Skipping audio during initial sync: {event.event_id}")
            return

        logger.info(f"Audio message in {room.room_id} from {event.sender}")
        # Use await (not create_task) to ensure completion before early returns
        await self._mark_as_read(room.room_id, event.event_id)

        try:
            # Download audio file
            mxc_url = event.source.get("content", {}).get("url")
            if not mxc_url:
                logger.warning("Audio message missing MXC URL")
                return

            response = await self.client.download(mxc_url)
            if not hasattr(response, "body"):
                logger.error(f"Failed to download audio: {response}")
                return

            audio_data = response.body

            # Transcribe using OpenAI Whisper API
            transcript = await self._transcribe_audio(audio_data)

            if not transcript:
                await self.client.room_send(
                    room_id=room.room_id,
                    message_type="m.room.message",
                    content={
                        "msgtype": "m.text",
                        "body": "❌ Failed to transcribe audio",
                        "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
                    },
                )
                return

            # Send transcript as reply
            content = {
                "msgtype": "m.text",
                "body": f"🎤 Transcript:\n{transcript}",
                "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
            }
            transcript_resp = await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content=content,
            )

            # Add to conversation tree
            tree = self.conversation_mgr.get_tree(room.room_id)
            tree.add_message(
                event_id=event.event_id,
                sender=event.sender,
                content=f"[Audio: {transcript}]",
                timestamp=event.server_timestamp,
            )

            if hasattr(transcript_resp, "event_id"):
                tree.add_message(
                    event_id=transcript_resp.event_id,
                    sender=self.bot_user_id or "",
                    content=f"🎤 Transcript:\n{transcript}",
                    timestamp=event.server_timestamp,
                    reply_to=event.event_id,
                    is_bot_message=True,
                )

            # Now process transcript with LLM
            context_nodes = tree.get_thread_context(
                transcript_resp.event_id, max_depth=10
            )
            messages = []
            for node in context_nodes:
                role = "user" if not node.is_bot_message else "assistant"
                messages.append({"role": role, "content": node.content})

            system_prompt = self._get_default_system_prompt()

            # Call LLM
            text, tool_calls = await self.llm.process_message(system_prompt, messages)

            # Get the response event ID for threading
            response_event_id = (
                transcript_resp.event_id
                if hasattr(transcript_resp, "event_id")
                else event.event_id
            )

            # Send text response if any
            if text:
                await self._send_text_reply(
                    room.room_id,
                    response_event_id,
                    text,
                    tree=tree,
                    timestamp=event.server_timestamp,
                )

            # Send proposals if any
            if tool_calls:
                await self._send_tool_proposals(
                    room.room_id,
                    response_event_id,
                    tool_calls,
                    tree,
                    event.server_timestamp,
                )

        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            await self.client.room_send(
                room_id=room.room_id,
                message_type="m.room.message",
                content={
                    "msgtype": "m.text",
                    "body": f"❌ Error processing audio: {e}",
                    "m.relates_to": {"m.in_reply_to": {"event_id": event.event_id}},
                },
            )

    async def _transcribe_audio(self, audio_data: bytes) -> Optional[str]:
        """Transcribe audio using local OpenAI Whisper model (offline)."""
        try:
            import whisper
            import tempfile
            import os

            # Load model once on first use
            if self.whisper_model is None:
                logger.info(f"Loading Whisper model '{self.config.whisper_model}'...")
                # Use FP32 for CPU to avoid FP16 warning
                self.whisper_model = whisper.load_model(
                    self.config.whisper_model, device="cpu", download_root=None
                )
                logger.info("Whisper model loaded")

            # Write to temp file (Whisper needs a file path)
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name

            try:
                # Transcribe with auto-detection (supports DE/ES/EN)
                logger.info("Transcribing audio with Whisper...")
                start_parsing = time.time()
                result = self.whisper_model.transcribe(
                    temp_path, language=None, fp16=False
                )
                end_parsing = time.time()
                logger.info(
                    f"Transcription took {end_parsing - start_parsing:.2f} seconds"
                )
                return result["text"]
            finally:
                os.unlink(temp_path)
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return None

    async def on_message(self, room, event: RoomMessageText) -> None:
        """Handle text messages."""
        # Ignore our own messages
        if event.sender == self.bot_user_id:
            return

        # Check if sender is allowed
        if self.config.allowed_users and event.sender not in self.config.allowed_users:
            logger.debug(f"Ignoring message from unauthorized user {event.sender}")
            return

        # Skip processing during initial sync to avoid duplicate responses
        if self.is_initial_sync:
            logger.debug(f"Skipping message during initial sync: {event.event_id}")
            return

        logger.info(f"Message in {room.room_id} from {event.sender}: {event.body}")
        
        asyncio.create_task(self._mark_as_read(room.room_id, event.event_id))

        # Extract relations
        content = event.source.get("content", {})
        relates_to = content.get("m.relates_to", {})

        # Check if this is an edit (m.replace)
        if relates_to.get("rel_type") == "m.replace":
            original_event_id = relates_to.get("event_id")
            logger.info(f"Detected edit of event {original_event_id}")
            tree = self.conversation_mgr.get_tree(room.room_id)
            tree.add_message(
                event_id=event.event_id,
                sender=event.sender,
                content=event.body,
                timestamp=event.server_timestamp,
                replaces=original_event_id,
            )

            # Delete old proposals for the original message
            if original_event_id in tree.nodes:
                descendants = tree.get_descendants(original_event_id)
                for desc_id in descendants:
                    if desc_id in tree.nodes and tree.nodes[desc_id].is_bot_message:
                        try:
                            await self.client.room_redact(
                                room.room_id, desc_id, reason="Message edited"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to redact {desc_id}: {e}")
                        tree.remove_message(desc_id)

            # Regenerate proposals with edited content
            await self._respond_with_llm(
                room.room_id, tree, event.event_id, event.server_timestamp
            )
            return

        # Check relations
        in_reply_to = relates_to.get("m.in_reply_to", {}).get("event_id")
        thread_root = (
            relates_to.get("event_id")
            if relates_to.get("rel_type") == "m.thread"
            else None
        )
        is_threaded = relates_to.get("rel_type") == "m.thread"

        # Add to conversation tree
        tree = self.conversation_mgr.get_tree(room.room_id)

        # New or known message, ensure it exists in the tree
        if event.event_id not in tree.nodes:
            tree.add_message(
                event_id=event.event_id,
                sender=event.sender,
                content=event.body,
                timestamp=event.server_timestamp,
                reply_to=in_reply_to,
                thread_root=thread_root,
            )

        # Skip if we've already replied to this message (from history or current run)
        if tree.has_bot_response(event.event_id):
            logger.debug(
                f"Already responded to {event.event_id}, skipping duplicate processing"
            )
            return

        # If this is a top-level message (no reply_to and no thread_root),
        # the bot should respond by replying to it
        if not in_reply_to and not thread_root:
            # Just reply normally, don't try to create threads
            pass

        await self._respond_with_llm(
            room.room_id, tree, event.event_id, event.server_timestamp
        )

    async def _get_room_prompt(self, room_id: str) -> str:
        """Get system prompt from room topic or return default."""
        try:
            room = self.client.rooms.get(room_id)
            if room and room.topic:
                logger.info(f"Using room topic as system prompt for {room_id}")
                return room.topic
        except Exception as e:
            logger.warning(f"Failed to get room topic: {e}")

        return self._get_default_system_prompt()

    async def _respond_with_llm(
        self, room_id: str, tree, event_id: str, timestamp: int, send_error: bool = True
    ) -> None:
        """Generate and send bot replies for a given message."""
        context_nodes = tree.get_thread_context(event_id, max_depth=10)
        messages = []
        for node in context_nodes:
            role = "user" if not node.is_bot_message else "assistant"
            messages.append({"role": role, "content": node.content})

        system_prompt = await self._get_room_prompt(room_id)

        try:
            text, tool_calls = await self.llm.process_message(system_prompt, messages)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            if send_error:
                await self._send_error_reply(room_id, event_id, str(e))
            return

        if text:
            await self._send_text_reply(
                room_id, event_id, text, tree=tree, timestamp=timestamp
            )

        if tool_calls:
            await self._send_tool_proposals(
                room_id, event_id, tool_calls, tree, timestamp
            )

    async def _process_pending_messages(self, room_id: str) -> None:
        """Respond to all user messages in history that have no bot reply."""
        tree = self.conversation_mgr.get_tree(room_id)
        pending = tree.pending_user_messages()
        if not pending:
            return

        logger.info(f"Processing {len(pending)} pending messages in {room_id}")
        for node in pending:
            # Skip if a bot reply appeared between collection and processing
            if tree.has_bot_response(node.event_id):
                continue
            await self._respond_with_llm(room_id, tree, node.event_id, node.timestamp)

    async def _ensure_room_prompt(self, room_id: str) -> None:
        """Set default system prompt in room topic if it's empty.
        
        If the bot lacks permissions to set the topic, it will send a message
        to the room informing users of the issue.
        """
        try:
            room = self.client.rooms.get(room_id)
            if room and not room.topic:
                response = await self.client.room_put_state(
                    room_id=room_id,
                    event_type="m.room.topic",
                    content={"topic": self._get_default_system_prompt()},
                )
                
                # Check if the request was successful by checking for event_id
                # A successful RoomPutStateResponse will have an event_id attribute
                # An error response (RoomPutStateError) will not
                if hasattr(response, 'event_id') and response.event_id:
                    logger.info(f"Set default system prompt in room topic for {room_id}")
                else:
                    logger.warning(f"Failed to set room topic for {room_id}: {response}")
                    await self._notify_room_topic_permission_error(room_id)
        except Exception as e:
            logger.warning(f"Failed to set room topic: {e}")
            await self._notify_room_topic_permission_error(room_id)
    
    async def _notify_room_topic_permission_error(self, room_id: str) -> None:
        """Send a message to the room about lacking permission to set topic."""
        try:
            message = (
                "⚠️ I don't have permission to set the room topic/description.\n\n"
                "The room topic is used as my system prompt. "
                "Please either:\n"
                "1. Grant me permission to change the room topic, or\n"
                "2. Set the room topic manually to customize my behavior for this room.\n\n"
                "Until then, I'll use my default system prompt."
            )
            
            content = {
                "msgtype": "m.text",
                "body": message,
            }
            
            await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            )
            logger.info(f"Sent permission error notification to room {room_id}")
        except Exception as e:
            logger.error(f"Failed to send notification to room {room_id}: {e}")

    async def _build_deck_samples(self, sample_size: int = 10) -> Dict[str, List[Dict[str, str]]]:
        if not self.config.enable_anki:
            return {}

        try:
            from tool_bot.anki_client import AnkiConnectClient

            anki = AnkiConnectClient(url=self.config.anki_connect_url)
            deck_names = await anki.get_deck_names()
            active_decks = [d for d in deck_names if d.startswith("Active::Bot")]

            samples: Dict[str, List[Dict[str, str]]] = {}
            for deck in active_decks:
                samples[deck] = await anki.get_sample_cards(deck, sample_size=sample_size)

            return samples
        except Exception as e:
            logger.warning(f"Failed to fetch deck samples: {e}")
            return {}

    @staticmethod
    def _ensure_active_bot_deck(deck: str) -> str:
        if not deck:
            return "Active::Bot"
        return deck if deck.startswith("Active::Bot") else f"Active::Bot::{deck}"

    async def _choose_deck_with_llm(
        self,
        flashcard: Dict,
        deck_samples: Dict[str, List[Dict[str, str]]],
    ) -> Tuple[str, str, List[str]]:
        """Ask the LLM to select a deck or propose a new subdeck. Fails if the LLM cannot decide."""
        requested = flashcard.get("deck") or "Default"

        deck_payload = []
        for deck, samples in deck_samples.items():
            deck_payload.append({
                "deck": deck,
                "samples": samples[:10],
            })

        system_prompt = (
            "You are an Anki deck routing helper."
            " Choose the best existing Active::Bot subdeck for the proposed flashcard,"
            " or propose a concise new subdeck under Active::Bot if none fit."
            " Return JSON only."
        )

        user_prompt = (
            "Flashcard to file:\n"
            f"Front: {flashcard.get('front','')}\n"
            f"Back: {flashcard.get('back','')}\n"
            f"Requested deck: {requested}\n"
            "Candidate decks with samples (up to 10 per deck):\n"
            f"{json.dumps(deck_payload, ensure_ascii=True)}\n"
            "Respond with a JSON object: {\"deck\": string, \"reason\": string, \"preview\": [strings]}"
        )

        response_text, _ = await self.llm.process_message(
            system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            enable_tools=False,
        )

        if not response_text:
            raise RuntimeError("LLM did not return a deck selection")

        try:
            parsed = json.loads(response_text)
        except Exception:
            match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
            if not match:
                raise RuntimeError("LLM response was not valid JSON")
            parsed = json.loads(match.group(0))

        deck = self._ensure_active_bot_deck(parsed.get("deck") or requested)
        reason = parsed.get("reason") or "LLM chose this deck."
        preview_raw = parsed.get("preview") or []
        preview = []
        if isinstance(preview_raw, list):
            for item in preview_raw[:10]:
                if isinstance(item, str):
                    preview.append(item.strip())

        return deck, reason, preview

    async def _select_deck_for_flashcard(
        self,
        flashcard: Dict,
        deck_samples: Dict[str, List[Dict[str, str]]],
    ) -> Tuple[str, str, List[str]]:
        return await self._choose_deck_with_llm(flashcard, deck_samples)

    async def _send_tool_proposals(
        self, room_id: str, trigger_event_id: str, tool_calls, tree, timestamp: int
    ):
        """Send tool proposals as replies to messages."""
        # Separate web_search calls from other tool calls
        web_search_calls = []
        other_tool_calls = []

        for tool_call in tool_calls:
            if tool_call.tool_name == "web_search":
                web_search_calls.append(tool_call)
            else:
                other_tool_calls.append(tool_call)

        # Process non-web-search tools individually (flashcards, todos, etc.)
        for tool_call in other_tool_calls:
            if tool_call.tool_name == "create_flashcards":
                deck_samples = await self._build_deck_samples()
                for fc in tool_call.arguments.get("flashcards", []):
                    try:
                        selected_deck, deck_reason, deck_preview = await self._select_deck_for_flashcard(
                            fc, deck_samples
                        )
                    except Exception as e:
                        error_body = (
                            "❌ Failed to choose deck for flashcard via LLM.\n"
                            f"Front: {fc.get('front','')}\n"
                            f"Back: {fc.get('back','')}\n"
                            f"Error: {e}"
                        )
                        await self._send_text_reply(
                            room_id,
                            trigger_event_id,
                            error_body,
                            tree=tree,
                            timestamp=timestamp,
                        )
                        continue

                    fc["deck"] = selected_deck
                    fc["deck_reason"] = deck_reason

                    body = (
                        f"**Flashcard Proposal**\n"
                        f"Type: {fc.get('card_type','basic')}\n"
                        f"Front: {fc.get('front','')}\n"
                        f"Back: {fc.get('back','')}\n"
                        f"Deck: {fc.get('deck','Default')}\n"
                    )

                    body += "\nReact with 👍 to create."

                    content = {
                        "msgtype": "m.text",
                        "body": body,
                        "m.relates_to": {
                            "m.in_reply_to": {"event_id": trigger_event_id},
                        },
                    }
                    resp = await self.client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=content,
                    )
                    if hasattr(resp, "event_id"):
                        tree.add_message(
                            event_id=resp.event_id,
                            sender=self.bot_user_id or "",
                            content=body,
                            timestamp=timestamp,
                            reply_to=trigger_event_id,
                            is_bot_message=True,
                        )
                        tree.nodes[resp.event_id].tool_proposal = fc
            elif tool_call.tool_name == "create_todos":
                for td in tool_call.arguments.get("todos", []):
                    body = (
                        f"**Todo Proposal**\n"
                        f"Task: {td.get('content','')}\n"
                        f"Due: {td.get('due_string','')}\n"
                        f"Priority: {td.get('priority',1)}\n"
                        f"Project: {td.get('project_name','')}\n"
                        f"\nReact with 👍 to create."
                    )
                    content = {
                        "msgtype": "m.text",
                        "body": body,
                        "m.relates_to": {
                            "m.in_reply_to": {"event_id": trigger_event_id},
                        },
                    }
                    resp = await self.client.room_send(
                        room_id=room_id,
                        message_type="m.room.message",
                        content=content,
                    )
                    if hasattr(resp, "event_id"):
                        tree.add_message(
                            event_id=resp.event_id,
                            sender=self.bot_user_id or "",
                            content=body,
                            timestamp=timestamp,
                            reply_to=trigger_event_id,
                            is_bot_message=True,
                        )
                        tree.nodes[resp.event_id].tool_proposal = td

        # Process all web_search calls together in a single response
        if web_search_calls:
            await self._handle_web_searches(
                room_id, trigger_event_id, web_search_calls, tree, timestamp
            )

    async def _handle_web_searches(
        self,
        room_id: str,
        trigger_event_id: str,
        web_search_calls,
        tree,
        timestamp: int,
    ):
        """Handle multiple web search calls in a single consolidated response."""
        # Step 1: Send initial message indicating all searches
        queries = [call.arguments.get("query", "") for call in web_search_calls]

        if len(queries) == 1:
            initial_body = f"🔍 Searching the web for: **{queries[0]}**\n\nFetching and analyzing results..."
        else:
            initial_body = f"🔍 Searching the web for {len(queries)} queries:\n"
            for i, query in enumerate(queries, 1):
                initial_body += f"  {i}. **{query}**\n"
            initial_body += "\nFetching and analyzing results..."

        initial_content = {
            "msgtype": "m.text",
            "body": initial_body,
            "m.relates_to": {
                "m.in_reply_to": {"event_id": trigger_event_id},
            },
        }
        initial_resp = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=initial_content,
        )

        initial_event_id = None
        if hasattr(initial_resp, "event_id"):
            initial_event_id = initial_resp.event_id
            tree.add_message(
                event_id=initial_event_id,
                sender=self.bot_user_id or "",
                content=initial_body,
                timestamp=timestamp,
                reply_to=trigger_event_id,
                is_bot_message=True,
            )

        # Step 2: Execute all searches and collect results
        search_queries = [
            {
                "query": call.arguments.get("query", ""),
                "max_results": call.arguments.get("max_results", 3),
            }
            for call in web_search_calls
        ]

        all_search_results = await self.web_search.execute_searches(search_queries)

        # Step 3: Use LLM to extract and synthesize information
        try:
            if not any(r.get("status") == "success" for r in all_search_results):
                final_body = "❌ All web searches failed or returned no usable results."
            else:
                # Build extraction prompt
                extraction_prompt, source_map = self.web_search.build_extraction_prompt(
                    all_search_results
                )

                # Call LLM to extract information
                system_prompt = (
                    "You are a helpful assistant that extracts and synthesizes information from web search results. "
                    "Provide clear, concise answers based on the provided content. "
                    "Always cite your sources by mentioning the source number."
                )

                extraction_messages = [{"role": "user", "content": extraction_prompt}]

                extracted_text, _ = await self.llm.process_message(
                    system_prompt, extraction_messages, enable_tools=False
                )

                if extracted_text:
                    final_body = self.web_search.format_search_results(
                        extracted_text, source_map
                    )
                else:
                    final_body = (
                        "Could not extract information from the search results."
                    )

        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            final_body = f"❌ Failed to process search results: {str(e)}"

        # Step 4: Send final consolidated reply
        reply_to_id = initial_event_id if initial_event_id else trigger_event_id
        final_content = {
            "msgtype": "m.text",
            "body": final_body,
            "m.relates_to": {
                "m.in_reply_to": {"event_id": reply_to_id},
            },
        }
        final_resp = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=final_content,
        )
        if hasattr(final_resp, "event_id"):
            tree.add_message(
                event_id=final_resp.event_id,
                sender=self.bot_user_id or "",
                content=final_body,
                timestamp=timestamp,
                reply_to=reply_to_id,
                is_bot_message=True,
            )

    async def _execute_proposal(
        self,
        room_id: str,
        proposal_event_id: str,
        proposal_node: MessageNode,
        user_id: str,
        timestamp: int,
    ) -> None:
        """Execute a tool proposal (flashcard or todo) when approved by user."""
        if not proposal_node.tool_proposal:
            logger.warning(f"Proposal node {proposal_event_id} has no tool_proposal")
            return

        proposal = proposal_node.tool_proposal
        reply_body = ""

        try:
            if "card_type" in proposal:
                if not self.config.enable_anki:
                    reply_body = "⚠️ Anki integration is disabled. Set ENABLE_ANKI=true to enable."
                else:
                    try:
                        from tool_bot.anki_client import AnkiConnectClient

                        anki = AnkiConnectClient(url=self.config.anki_connect_url)
                        card_type = proposal.get("card_type", "basic")
                        deck = proposal.get("deck", "Default")
                        tags = proposal.get("tags", [])
                        if card_type == "basic":
                            note_id = await anki.add_basic_card(
                                front=proposal.get("front", ""),
                                back=proposal.get("back", ""),
                                deck=deck,
                                tags=tags,
                            )
                        elif card_type == "basic-reversed":
                            note_id = await anki.add_basic_reversed_card(
                                front=proposal.get("front", ""),
                                back=proposal.get("back", ""),
                                deck=deck,
                                tags=tags,
                            )
                        elif card_type == "cloze":
                            note_id = await anki.add_cloze_card(
                                text=proposal.get("front", ""),
                                deck=deck,
                                tags=tags,
                            )
                        else:
                            raise ValueError(f"Unknown card_type: {card_type}")
                        reply_body = f"✅ Flashcard created in Anki (note id: {note_id})"
                        try:
                            await anki.sync()
                        except Exception as sync_error:
                            logger.warning(f"Anki sync to AnkiWeb failed (flashcard was still created): {sync_error}")
                    except Exception as anki_error:
                        logger.error(f"Anki-Connect error: {anki_error}")
                        reply_body = (
                            f"❌ Failed to create flashcard: {anki_error}\n\n"
                            f"**Troubleshooting:**\n"
                            f"1. Make sure Anki is running\n"
                            f"2. Install Anki-Connect add-on (code: 2055492159)\n"
                            f"3. Restart Anki after installing\n"
                            f"4. Check Anki-Connect is accessible at {self.config.anki_connect_url}"
                        )
            elif "content" in proposal:
                from tool_bot.todoist_client import TodoistClient

                todoist = TodoistClient(self.config.todoist_token)
                project_id = None
                if proposal.get("project_name"):
                    project_id = await todoist.get_or_create_project(
                        proposal["project_name"]
                    )
                task = await todoist.create_task(
                    content=proposal.get("content", ""),
                    due_string=proposal.get("due_string"),
                    priority=proposal.get("priority", 1),
                    labels=proposal.get("labels", []),
                    project_id=project_id,
                )
                reply_body = f"✅ Todo created in Todoist (task id: {task['id']})"
            else:
                reply_body = "⚠️ Unknown proposal type."
        except Exception as e:
            logger.error(f"Failed to execute proposal: {e}")
            reply_body = f"❌ Failed to create: {e}"

        if reply_body:
            content = {
                "msgtype": "m.text",
                "body": reply_body,
                "m.relates_to": {
                    "m.in_reply_to": {"event_id": proposal_event_id},
                },
            }
            send_resp = await self.client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content=content,
            )
            # Track confirmation message in conversation tree so redactions cascade
            try:
                tree = self.conversation_mgr.get_tree(room_id)
                if hasattr(send_resp, "event_id"):
                    tree.add_message(
                        event_id=send_resp.event_id,
                        sender=self.bot_user_id or "",
                        content=reply_body,
                        timestamp=timestamp,
                        reply_to=proposal_event_id,
                        is_bot_message=True,
                    )
            except Exception as e:
                logger.debug(f"Failed to record confirmation message: {e}")

    async def on_reaction(self, room, event: ReactionEvent) -> None:
        """Handle reactions to messages."""
        if event.sender == self.bot_user_id:
            return

        if self.config.allowed_users and event.sender not in self.config.allowed_users:
            return

        # Check if it's a thumbs up on one of our messages
        reacted_to = (
            event.source.get("content", {}).get("m.relates_to", {}).get("event_id")
        )
        key = event.source.get("content", {}).get("m.relates_to", {}).get("key")

        logger.info(f"Reaction '{key}' to event {reacted_to} from {event.sender}")

        # Add reaction to conversation tree
        tree = self.conversation_mgr.get_tree(room.room_id)
        tree.add_reaction(reacted_to, key, event.sender)

        if self._is_thumbs_up(key):
            node = tree.nodes.get(reacted_to)

            # If not found, check if there's an edited version
            if not node:
                logger.debug(
                    f"Reaction target {reacted_to} not in tree. Checking for edits..."
                )
                for candidate_id, candidate_node in tree.nodes.items():
                    if candidate_node.replaces == reacted_to:
                        node = candidate_node
                        logger.info(
                            f"Found edited version of {reacted_to}: {candidate_id}"
                        )
                        break

            if not node:
                logger.debug(f"Thumbs up on unknown event {reacted_to}; ignoring.")
                return

            if not node.is_bot_message or not node.tool_proposal:
                logger.debug(
                    f"Thumbs up on non-proposal (is_bot={node.is_bot_message}, has_proposal={bool(node.tool_proposal)}); ignoring."
                )
                return

            logger.info(f"Executing proposal on {reacted_to}")
            # Execute the proposal
            await self._execute_proposal(
                room.room_id, reacted_to, node, event.sender, event.server_timestamp
            )

    async def on_redaction(self, room, event: RedactionEvent) -> None:
        """Handle message deletions with cascade for bot replies."""
        redacts = event.redacts
        logger.info(f"Redaction of event {redacts} in {room.room_id}")

        tree = self.conversation_mgr.get_tree(room.room_id)
        if redacts in tree.nodes:
            node = tree.nodes[redacts]
            # Cascade redaction to all descendants (bot and user)
            descendants = tree.get_descendants(redacts)
            logger.info(f"Cascading deletion to {len(descendants)} descendants")
            for desc_id in descendants:
                if desc_id in tree.nodes:
                    try:
                        if self.client:
                            await self.client.room_redact(room.room_id, desc_id)
                    except Exception as e:
                        logger.warning(f"Failed to redact descendant {desc_id}: {e}")
                    finally:
                        tree.remove_message(desc_id)
            # Remove original from tree
            tree.remove_message(redacts)

    async def _send_text_reply(
        self, room_id: str, event_id: str, text: str, tree=None, timestamp: int = 0
    ) -> Optional[str]:
        """Send a text response as a reply to a message.

        Returns:
            The event ID of the sent message, or None if failed.
        """
        if not self.client:
            return None

        content = {
            "msgtype": "m.text",
            "body": text,
            "m.relates_to": {"m.in_reply_to": {"event_id": event_id}},
        }

        response = await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )

        # Check if response is successful
        if not hasattr(response, "event_id"):
            logger.error(f"Failed to send text reply to {event_id}: {response}")
            return None

        # Add to conversation tree if tree was provided
        if tree:
            tree.add_message(
                event_id=response.event_id,
                sender=self.bot_user_id or "",
                content=text,
                timestamp=timestamp,
                reply_to=event_id,
                is_bot_message=True,
            )
            logger.info(
                f"Sent text reply to {event_id}, added to tree as {response.event_id}"
            )
        else:
            logger.info(f"Sent text reply to {event_id} (not added to tree)")

        return response.event_id

    async def _send_error_reply(self, room_id: str, event_id: str, error: str) -> None:
        """Send an error message as a reply."""
        if not self.client:
            return

        content = {
            "msgtype": "m.text",
            "body": f"❌ Error: {error}",
            "m.relates_to": {"m.in_reply_to": {"event_id": event_id}},
        }

        await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        logger.info(f"Sent error reply to {event_id}")

    async def _send_placeholder_reply(
        self, room_id: str, event_id: str, threaded: bool = False
    ) -> None:
        """Send a placeholder reply for testing."""
        if not self.client:
            return

        content = {
            "msgtype": "m.text",
            "body": "🤖 Processing your request...",
            "m.relates_to": {"m.in_reply_to": {"event_id": event_id}},
        }

        if threaded:
            # Start a new thread with this event as the root
            content["m.relates_to"]["rel_type"] = "m.thread"
            content["m.relates_to"]["event_id"] = event_id
            content["m.relates_to"]["is_falling_back"] = True
            # Replace reply with thread relation
            content["m.relates_to"] = {
                "rel_type": "m.thread",
                "event_id": event_id,
            }

        await self.client.room_send(
            room_id=room_id,
            message_type="m.room.message",
            content=content,
        )
        logger.info(f"Sent placeholder reply to {event_id}")

    async def stop(self) -> None:
        """Stop the client and cleanup."""
        if self.client:
            await self.client.close()
