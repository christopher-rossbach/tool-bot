# Matrix Tool Bot - Architecture & Implementation Guide

**Last Updated:** December 10, 2025

## Project Overview

A Python-based Matrix bot that uses LLM tool-calling (OpenAI) to propose and execute tasks like creating Anki flashcards and Todoist todos. Features threaded conversations, per-message edits with regeneration, reaction-based approvals (👍), voice message transcription (German, Spanish, English), and cascading deletions.

## Core Architecture

### Module Structure

```
src/tool_bot/
├── __init__.py           # Package init
├── main.py               # Entry point with asyncio runner
├── config.py             # Environment variable loader
├── matrix_client.py      # Matrix-nio async client wrapper
├── conversation.py       # In-memory conversation tree/DAG
├── llm_engine.py         # LLM tool-calling (OpenAI)
├── anki_client.py        # Anki-Connect JSON-RPC client
└── todoist_client.py     # Todoist REST API client
```

### Key Design Decisions

1. **State Management**: No external database. All conversation state is derived from Matrix room history and maintained in-memory via `ConversationTree` objects per room.

2. **Threading Model**: First message without `m.in_reply_to` or `m.thread` spawns a new thread. Bot replies use `m.thread` relation to group proposals.

3. **Tool Proposals**: LLM generates tool calls (e.g., 3 flashcard proposals). Each proposal is sent as a separate threaded message. User can:
   - React with 👍 to execute
   - Reply to adjust individual proposals (triggers regeneration)
   - Edit original message (triggers regeneration of all proposals)

4. **Cascade Deletions**: When user deletes a message, bot recursively deletes all its own replies and descendants in that conversation branch.

5. **Voice Messages**: Download `m.audio`, decrypt if E2EE, transcribe with Whisper (auto-detect DE/ES/EN), send transcript as reply, then pass to LLM.

## Implementation Status

### ✅ Completed

1. **Project Scaffold**
   - `requirements.txt` with dependencies (matrix-nio, openai, whisper, httpx, pydantic)
   - Dockerfile (multi-stage Python 3.12-slim)
   - `shell.nix` for NixOS dev with direnv integration
   - `.envrc.example` template with `use nix`
   - Scripts: `run_dev.sh`, `run_docker.sh`

2. **Configuration System** (`config.py`)
   - Loads from environment variables (via direnv)
   - Required: `MATRIX_HOMESERVER`, login credentials, `ALLOWED_USERS`, `OPENAI_API_KEY`
   - Optional: `TODOIST_TOKEN`, `WHISPER_MODEL`, `ENABLE_E2EE`

3. **Matrix Client Core** (`matrix_client.py`)
   - Async `matrix-nio` client with login (password or access token)
   - Event handlers: text messages, audio, reactions, edits (`m.replace`), redactions
   - Thread spawning: detects first message without reply, sends threaded response
   - Authorized user filtering

4. **Conversation Tree** (`conversation.py`)
   - `MessageNode`: stores event metadata, relations (reply_to, thread_root, replaces), children (replies, edits, reactions)
   - `ConversationTree`: per-room DAG with methods for:
     - `add_message()`: insert node and update parent relations
     - `add_reaction()`: track reactions by key and sender
     - `get_thread_context()`: walk up reply chain for LLM context
     - `get_descendants()`: recursive traversal for cascade deletions
     - `get_latest_edit()`: resolve edits to most recent version
   - `ConversationManager`: manages trees for all rooms

5. **Cascade Deletions**
   - `on_redaction()` handler: when user deletes message, find descendants, redact bot messages, remove from tree

6. **LLM Engine** (`llm_engine.py`)
   - `LLMEngine` class: interface for OpenAI
   - Tool schemas: `FlashcardCreate` (type, front, back, deck, tags), `TodoCreate` (content, due_string, priority, labels, project_name)
   - Methods:
     - `_get_tools_schema()`: format tools for OpenAI
     - `process_message(system_prompt, messages)`: returns (text, tool_calls)
   - Pydantic models for type safety

7. **Anki-Connect Client** (`anki_client.py`)
   - `AnkiConnectClient`: JSON-RPC to `localhost:8765`
   - Methods:
     - `add_basic_card()`, `add_basic_reversed_card()`, `add_cloze_card()`
     - `create_deck()`: ensure deck exists
     - `find_notes()`: query for deduplication

8. **Todoist Client** (`todoist_client.py`)
   - `TodoistClient`: REST API v2 with bearer token
   - Methods:
     - `create_task()`: with idempotency (`X-Request-Id`)
     - `get_projects()`, `create_project()`, `get_or_create_project()`
   - Natural date parsing via `due_string`
   - Results include title, body snippet, and URL for each search result

### 🚧 In Progress / TODO

9. **Room Prompt Management** (TODO #5)
   - On `on_invite()`: check room topic/description
   - If empty, set default system prompt (via `m.room.topic` state event)
   - Store prompt per room in `ConversationManager` or derive from room state
   - Allow users to edit room topic to customize bot behavior

10. **LLM Integration in Message Handler** (TODO #6)
    - Wire `LLMEngine` into `MatrixBot`
    - On user message:
      - Build context from `get_thread_context()`
      - Format as LLM messages (role: user/assistant)
      - Call `process_message()` with room system prompt
      - Handle tool calls: send proposals as threaded replies
      - Store tool metadata in `MessageNode.tool_proposal`

11. **Flashcard Proposal Flow** (TODO #7)
    - When LLM returns `create_flashcards`:
      - Parse list of `FlashcardCreate` objects
      - Send 3 separate threaded messages (each a proposal)
      - Format: "**Flashcard Proposal**\nType: basic\nFront: ...\nBack: ...\nDeck: ...\n\nReact with 👍 to create"
    - On 👍 reaction:
      - Check if message has `tool_proposal` metadata
      - Execute via `AnkiConnectClient.add_basic_card()` etc.
      - Reply with confirmation or error
    - On reply to proposal:
      - Regenerate that specific card with adjustments
      - Send new proposal message

12. **Todoist Integration** (TODO #8)
    - Similar flow to flashcards
    - Format proposal: "**Todo Proposal**\nTask: ...\nDue: ...\nPriority: ...\nProject: ...\n\nReact with 👍 to create"
    - On 👍: execute via `TodoistClient.create_task()`
    - Handle project creation if specified

13. **Voice Transcription** (TODO #9)
    - Install `openai-whisper` (already in deps)
    - On `on_audio()`:
      - Download media via `client.download()`
      - Decrypt if `content.file` (E2EE) using keys from `content.file`
      - Save to temp file
      - Load Whisper model: `whisper.load_model(config.whisper_model)`
      - Transcribe: `model.transcribe(audio_file, language=None)` (auto-detect)
      - Constrain to DE/ES/EN via `language` param if needed
      - Send transcript as threaded reply
      - Pass transcript to LLM for tool execution

14. **Edit/Regenerate Logic** (TODO #10)
    - On `m.replace` detection:
      - Find original message in tree
      - Get all direct bot replies (proposals)
      - Delete old proposals (send redactions)
      - Re-run LLM with edited prompt
      - Send new proposals as replies to the edited message
      - Preserve thread structure

15. **Permissions & Safety** (TODO #12)
    - Already implemented: `allowed_users` check in handlers
    - Add rate limiting: track requests per user per time window
    - Idempotency: use event IDs as dedup keys for tool execution
    - E2EE support:
      - Enable with `ENABLE_E2EE=true`
      - Store device keys in persistent volume (SQLite via nio store)
      - Verify devices on first join
      - Handle decryption errors gracefully

16. **Tests & Linting** (TODO #15)
    - Add `pytest`, `ruff`, `black` to dev dependencies
    - Unit tests:
      - `test_conversation.py`: tree operations, descendants, context retrieval
      - `test_llm_engine.py`: mock LLM responses, tool parsing
      - `test_anki_client.py`: mock httpx, verify payloads
      - `test_todoist_client.py`: mock httpx, idempotency headers
    - Integration tests: mock Matrix events, verify handler logic

17. **README Walkthrough** (TODO #16)
    - Quick start section:
      ```bash
      cp .envrc.example .envrc
      # Edit .envrc with credentials
      direnv allow .
      nix-shell  # auto-creates venv and installs deps
      ```
    - Example prompts:
      - "Create flashcards for the capitals of France, Germany, and Spain"
      - "Add todos for buying groceries tomorrow and calling dentist"
    - Behavior demos:
      - Thumbs up approval
      - Editing original message regenerates proposals
      - Deleting message removes bot responses

## Message Flow Diagrams

### Flashcard Creation Flow

```
User: "Create flashcards for NYC (8.3M), Denver (715K), Miami (455K)"
  ↓
Bot LLM: Parses request, calls create_flashcards tool
  ↓
Bot sends 3 threaded proposals:
  - Proposal 1: NYC population flashcard
  - Proposal 2: Denver population flashcard
  - Proposal 3: Miami population flashcard
  ↓
User reacts 👍 to Proposal 1
  ↓
Bot: Executes Anki-Connect, creates card, replies "✅ Flashcard created in Anki"
```

### Edit/Regenerate Flow

```
User: "Create flashcards for NYC, Denver, Miami" [event_id: e1]
  ↓
Bot: [3 proposals: p1, p2, p3]
  ↓
User edits e1: "Create flashcards for NYC (8.3M), LA (4M), Chicago (2.7M)"
  ↓
Bot: Detects m.replace
  - Redacts old proposals [p1, p2, p3]
  - Re-runs LLM with edited prompt
  - Sends 3 new proposals: [p4, p5, p6] as replies to edited e1
```

### Cascade Deletion Flow

```
User: [message m1]
  ↓
Bot: [reply b1 to m1]
  ↓
User: [reply m2 to b1]
  ↓
Bot: [reply b2 to m2]
  ↓
User deletes m1
  ↓
Bot: get_descendants(m1) → [b1, m2, b2]
  - Filters bot messages: [b1, b2]
  - Sends redactions for b1 and b2
  - Removes from tree
```

## Environment Variables Reference

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `MATRIX_HOMESERVER` | Yes | Homeserver URL | `https://matrix.org` |
| `MATRIX_USER` | Yes* | Bot user ID | `@bot:example.org` |
| `MATRIX_PASSWORD` | Yes* | Bot password | `secret` |
| `MATRIX_ACCESS_TOKEN` | Yes* | Access token (alternative to password) | `syt_...` |
| `ALLOWED_USERS` | Yes | Comma-separated MXIDs | `@user1:example.org,@user2:example.org` |
| `OPENAI_API_KEY` | Yes | OpenAI API key | `sk-...` |
| `TODOIST_TOKEN` | No | Todoist API token | `abc123...` |
| `WHISPER_MODEL` | No | Whisper model size | `base` (default), `small`, `medium`, `large` |
| `ENABLE_E2EE` | No | Enable encryption support | `true` or `false` (default) |

*Either `MATRIX_PASSWORD` or `MATRIX_ACCESS_TOKEN` required

## Development Workflow

### Initial Setup

```bash
cd /path/to/tool-bot
cp .envrc.example .envrc
# Edit .envrc with your credentials
direnv allow .
nix-shell
```

The Nix shell will:
- Provide Python 3.12, direnv, git, openssl
- Auto-create `.venv` if missing
- Activate venv
- Install/upgrade all dependencies from `requirements.txt`

### Running Locally

```bash
./scripts/run_dev.sh
```

Or manually:
```bash
source .venv/bin/activate
python -m tool_bot.main
```

### Docker

Build:
```bash
docker build -t tool-bot:dev .
```

Run:
```bash
docker run --rm \
  -e MATRIX_HOMESERVER="$MATRIX_HOMESERVER" \
  -e MATRIX_USER="$MATRIX_USER" \
  -e MATRIX_PASSWORD="$MATRIX_PASSWORD" \
  -e ALLOWED_USERS="$ALLOWED_USERS" \
  -e LLM_PROVIDER="$LLM_PROVIDER" \
  -e OPENAI_API_KEY="$OPENAI_API_KEY" \
  tool-bot:dev
```

Or use the provided script:
```bash
./scripts/run_docker.sh
```

## Next Steps for Implementation

1. **Immediate**: Wire LLM engine into message handler
   - Create `process_user_message()` method in `MatrixBot`
   - Build message context from conversation tree
   - Call `LLMEngine.process_message()`
   - Send tool proposals as threaded replies

2. **Core Features**: Implement proposal approval flow
   - Store tool metadata in conversation tree
   - On 👍 reaction, execute tool (Anki/Todoist)
   - Send confirmation reply

3. **Regeneration**: Handle edits and per-proposal adjustments
   - Detect `m.replace`, redact old proposals, regenerate
   - On reply to proposal, regenerate single card

4. **Voice**: Add Whisper transcription
   - Download + decrypt audio
   - Transcribe with language detection
   - Feed to LLM

5. **Polish**: Add room prompt management, rate limiting, E2EE, tests

## Common Patterns

### Sending Threaded Reply

```python
content = {
    "msgtype": "m.text",
    "body": "Your message",
    "m.relates_to": {
        "rel_type": "m.thread",
        "event_id": thread_root_id,  # First message in thread
    }
}
await client.room_send(room_id, "m.room.message", content)
```

### Sending Normal Reply

```python
content = {
    "msgtype": "m.text",
    "body": "Your reply",
    "m.relates_to": {
        "m.in_reply_to": {"event_id": parent_event_id}
    }
}
await client.room_send(room_id, "m.room.message", content)
```

### Redacting a Message

```python
await client.room_redact(room_id, event_id, reason="Bot cleanup")
```

## Troubleshooting

### "MATRIX_HOMESERVER is required"
- Ensure `.envrc` exists and has `export MATRIX_HOMESERVER=...`
- Run `direnv allow .`
- Check `echo $MATRIX_HOMESERVER` returns the URL

### "Login failed"
- Verify `MATRIX_USER` and `MATRIX_PASSWORD` or `MATRIX_ACCESS_TOKEN`
- Test login manually with `matrix-nio` CLI

### "Anki-Connect request failed"
- Ensure Anki is running with Anki-Connect plugin installed
- Test: `curl -X POST http://localhost:8765 -d '{"action":"version","version":6}'`
- Should return: `{"result":6,"error":null}`

### "Failed to create task" (Todoist)
- Verify `TODOIST_TOKEN` is valid
- Test: `curl https://api.todoist.com/rest/v2/tasks -H "Authorization: Bearer $TODOIST_TOKEN"`

### Dependencies not installing in Nix shell
- Delete `.venv` and re-enter nix-shell
- Manually: `rm -rf .venv && nix-shell`

## API References

- **Matrix Client-Server API**: https://spec.matrix.org/v1.9/client-server-api/
- **matrix-nio docs**: https://matrix-nio.readthedocs.io/
- **Anki-Connect**: https://foosoft.net/projects/anki-connect/
- **Todoist REST API**: https://developer.todoist.com/rest/v2/
- **OpenAI API**: https://platform.openai.com/docs/api-reference
- **Whisper**: https://github.com/openai/whisper

## Project Metadata

- **Language**: Python 3.9+
- **Async Framework**: asyncio
- **Matrix Client**: matrix-nio
- **LLM Provider**: OpenAI (gpt-4o-mini)
- **Voice Transcription**: OpenAI Whisper
- **External APIs**: Anki-Connect (local), Todoist (cloud)
- **Config Management**: direnv + environment variables
- **Dev Environment**: Nix shell + venv
- **Containerization**: Docker (multi-stage)
- **License**: (Not specified - add if needed)
