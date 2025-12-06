"""In-memory conversation tree for tracking message relations."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class MessageNode:
    """Represents a message in the conversation tree."""
    event_id: str
    room_id: str
    sender: str
    content: str
    timestamp: int
    
    # Relations
    reply_to: Optional[str] = None  # m.in_reply_to
    thread_root: Optional[str] = None  # m.thread root event_id
    replaces: Optional[str] = None  # m.replace (edit)
    
    # Children
    replies: List[str] = field(default_factory=list)
    edits: List[str] = field(default_factory=list)
    reactions: Dict[str, List[str]] = field(default_factory=dict)  # key -> [sender, ...]
    
    # Metadata
    is_bot_message: bool = False
    tool_proposal: Optional[Dict] = None  # For flashcard/todo proposals


class ConversationTree:
    """Manages the conversation tree for a room."""
    
    def __init__(self, room_id: str):
        self.room_id = room_id
        self.nodes: Dict[str, MessageNode] = {}
        self.thread_roots: Set[str] = set()
    
    def add_message(
        self,
        event_id: str,
        sender: str,
        content: str,
        timestamp: int,
        reply_to: Optional[str] = None,
        thread_root: Optional[str] = None,
        replaces: Optional[str] = None,
        is_bot_message: bool = False,
    ) -> MessageNode:
        """Add a message to the tree."""
        node = MessageNode(
            event_id=event_id,
            room_id=self.room_id,
            sender=sender,
            content=content,
            timestamp=timestamp,
            reply_to=reply_to,
            thread_root=thread_root,
            replaces=replaces,
            is_bot_message=is_bot_message,
        )
        
        self.nodes[event_id] = node
        
        # Update parent relations
        if reply_to and reply_to in self.nodes:
            self.nodes[reply_to].replies.append(event_id)
        
        if replaces and replaces in self.nodes:
            self.nodes[replaces].edits.append(event_id)
        
        if thread_root:
            self.thread_roots.add(thread_root)
        elif not reply_to:
            # First message without reply becomes a potential thread root
            self.thread_roots.add(event_id)
        
        return node
    
    def add_reaction(self, event_id: str, key: str, sender: str) -> None:
        """Add a reaction to a message."""
        if event_id in self.nodes:
            if key not in self.nodes[event_id].reactions:
                self.nodes[event_id].reactions[key] = []
            if sender not in self.nodes[event_id].reactions[key]:
                self.nodes[event_id].reactions[key].append(sender)
    
    def get_thread_context(self, event_id: str, max_depth: int = 10) -> List[MessageNode]:
        """Get the conversation context for a message (up the reply chain)."""
        context = []
        current = event_id
        depth = 0
        
        while current and current in self.nodes and depth < max_depth:
            context.append(self.nodes[current])
            node = self.nodes[current]
            current = node.reply_to or node.thread_root
            depth += 1
        
        return list(reversed(context))
    
    def get_descendants(self, event_id: str) -> List[str]:
        """Get all descendant event IDs recursively, including:
        - Direct replies (m.in_reply_to)
        - Messages in threads where `thread_root` points to the current node
        """
        if event_id not in self.nodes:
            return []

        descendants: List[str] = []
        to_process: List[str] = [event_id]

        while to_process:
            current = to_process.pop()
            if current not in self.nodes:
                continue

            # 1) Traverse replies edges
            for reply_id in self.nodes[current].replies:
                if reply_id not in descendants:
                    descendants.append(reply_id)
                    to_process.append(reply_id)

            # 2) Traverse thread children (messages with thread_root == current)
            for child_id, node in self.nodes.items():
                if node.thread_root == current and child_id not in descendants:
                    descendants.append(child_id)
                    to_process.append(child_id)

        return descendants

    def has_bot_response(self, event_id: str) -> bool:
        """Return True if the message has any bot-authored descendants."""
        for desc_id in self.get_descendants(event_id):
            node = self.nodes.get(desc_id)
            if node and node.is_bot_message:
                return True
        return False

    def pending_user_messages(self) -> List[MessageNode]:
        """Return user messages that do not yet have a bot response."""
        pending = [
            node
            for node in self.nodes.values()
            if not node.is_bot_message and not self.has_bot_response(node.event_id)
        ]
        return sorted(pending, key=lambda n: n.timestamp)
    
    def get_latest_edit(self, event_id: str) -> Optional[str]:
        """Get the latest edit of a message."""
        if event_id not in self.nodes:
            return None
        
        edits = self.nodes[event_id].edits
        if not edits:
            return event_id
        
        # Return the most recent edit (last in the list)
        return edits[-1]
    
    def remove_message(self, event_id: str) -> None:
        """Remove a message from the tree (for redactions)."""
        if event_id in self.nodes:
            del self.nodes[event_id]
            self.thread_roots.discard(event_id)


class ConversationManager:
    """Manages conversation trees for all rooms."""
    
    def __init__(self):
        self.trees: Dict[str, ConversationTree] = {}
    
    def get_tree(self, room_id: str) -> ConversationTree:
        """Get or create a conversation tree for a room."""
        if room_id not in self.trees:
            self.trees[room_id] = ConversationTree(room_id)
        return self.trees[room_id]
