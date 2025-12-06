# Matrix Tool Bot

A Python Matrix bot powered by LLM tool-calling (OpenAI/Anthropic) that proposes and executes tasks like creating Anki flashcards and Todoist todos.
Features include web search capabilities, threaded conversations, message edits with regeneration, reaction-based approvals (all thumbs-up variants), voice message transcription (DE/ES/EN), cascading deletions, and restart-safe state management.

## ✨ Features

- **LLM Tool Calling**: Uses OpenAI (gpt-4o-mini) or Anthropic (claude-3.5-sonnet) with function/tool calling
- **Web Search**: Search the web using DuckDuckGo to enrich context with up-to-date information
- **Anki Integration**: Creates flashcards via Anki-Connect with automatic deck hierarchy (`Active::Bot`)
- **Todoist Integration**: Creates tasks with natural language due dates and project management
- **Threaded Context**: First message spawns a thread; maintains conversation context
- **Edit & Regenerate**: Edit your message to regenerate proposals; bot deletes old ones
- **Reaction Approvals**: React with any thumbs-up variant (👍 👍🏻 👍🏼 👍🏽 👍🏾 👍🏿) to execute
- **Voice Transcription**: Transcribes voice messages in German, Spanish, and English via OpenAI Whisper API
- **Cascade Deletions**: Deleting a message removes all bot replies in that thread
- **Restart Safe**: Loads room history on startup; won't re-process old messages
- **Room Prompts**: System prompt from room topic; sets sensible default on join
- **Graceful Fallbacks**: Helpful error messages when Anki-Connect is unavailable

## 🚀 Quick Start

### Prerequisites

- Python 3.9+ (or use Nix shell)
- Anki with [Anki-Connect](https://ankiweb.net/shared/info/2055492159) installed (if using flashcards)
- OpenAI or Anthropic API key
- Todoist API token (optional)
- direnv (optional but recommended)

### Setup

1. **Clone and configure**:
   \`\`\`bash
   git clone <repo-url>
   cd tool-bot
   cp .envrc.example .envrc
   # Edit .envrc with your credentials
   direnv allow .
   \`\`\`

2. **Enter Nix shell** (or use your own Python 3.9+):
   \`\`\`bash
   nix-shell  # Auto-creates venv and installs deps
   \`\`\`

3. **Generate access token** (optional but recommended):
   \`\`\`bash
   python scripts/generate_token.py --update
   \`\`\`
   This will log in with your credentials and save the access token to your config file.

4. **Run the bot**:
   \`\`\`bash
   ./scripts/run_dev.sh
   \`\`\`

5. **Invite the bot** to a Matrix room and start chatting!

### Example Usage

**Creating flashcards:**
\`\`\`
You: Create a flashcard: "What is the capital of France?" → "Paris"
Bot: [Flashcard Proposal]
     Type: basic
     Front: What is the capital of France?
     Back: Paris
     Deck: Default
     
     React with 👍 to create.
You: 👍
Bot: ✅ Flashcard created in Anki (note id: 1234567890)
\`\`\`

**Creating todos:**
```
You: Remind me to review flashcards tomorrow at 7pm
Bot: [Todo Proposal]
     Task: Review flashcards
     Due: tomorrow at 7pm
     Priority: 1
     
     React with 👍 to create.
You: 👍
Bot: ✅ Todo created in Todoist (task id: 7890123456)
```

**Web search:**
```
You: What are the latest developments in quantum computing?
Bot: 🔍 Web Search Results for: latest developments in quantum computing

     1. **Quantum Computing Breakthrough 2024**
        Scientists achieve new milestone in error correction...
        https://example.com/quantum-news

     2. **IBM Announces 1000-Qubit Processor**
        Major advancement in quantum processor technology...
        https://example.com/ibm-quantum
     
     [Additional results...]
```

**Voice messages:**
\`\`\`
You: [sends voice message in German]
Bot: 🎤 Transcript:
     Erstelle eine Karteikarte für Photosynthese
Bot: [Flashcard Proposal]
     ...
\`\`\`

**Edit and regenerate:**
\`\`\`
You: Create flashcards for NYC, Denver, Miami
Bot: [3 proposals]
You: [edits message] Create flashcards for NYC (8.3M), LA (4M), Chicago (2.7M)
Bot: [deletes old proposals, sends 3 new ones with updated info]
\`\`\`

## ⚙️ Configuration

All configuration via environment variables (see \`.envrc.example\`):

### Required
- \`MATRIX_HOMESERVER\` - Matrix homeserver URL (e.g., \`https://matrix.org\`)
- \`MATRIX_USER\` - Bot's Matrix ID (e.g., \`@bot:example.org\`)
- \`MATRIX_PASSWORD\` or \`MATRIX_ACCESS_TOKEN\` - Authentication
- \`ALLOWED_USERS\` - Comma-separated Matrix IDs allowed to use bot
- \`LLM_PROVIDER\` - \`openai\` or \`anthropic\`
- \`OPENAI_API_KEY\` or \`ANTHROPIC_API_KEY\` - Depending on provider

### Optional
- `TODOIST_TOKEN` - Todoist API token for todo creation
- `ENABLE_ANKI` - Enable/disable Anki integration (default: `true`)
- `ANKI_CONNECT_URL` - Anki-Connect URL (default: `http://localhost:8765`)
- `WHISPER_MODEL` - Whisper model size (default: `base`). Options: `tiny`, `tiny.en`, `base`, `base.en`, `small`, `small.en`, `medium`, `medium.en`, `large-v1`, `large-v2`, `large-v3`, `large`
- `ENABLE_E2EE` - Enable E2EE support (default: `false`)

### System Prompt
- Taken from room topic/description
- Bot sets sensible default on first join
- Edit room topic to customize bot behavior per room

## 🛠️ Development

### Project Structure
\`\`\`
src/tool_bot/
├── main.py              # Entry point
├── config.py            # Environment config loader
├── matrix_client.py     # Matrix event handlers & bot logic
├── conversation.py      # In-memory conversation DAG
├── llm_engine.py        # OpenAI/Anthropic tool calling
├── anki_client.py       # Anki-Connect JSON-RPC client
└── todoist_client.py    # Todoist REST API client

scripts/
├── generate_token.py    # Generate Matrix access token
├── run_dev.sh          # Development run script
└── run_docker.sh       # Docker run script
\`\`\`

### Generating Access Tokens

The `scripts/generate_token.py` script logs into Matrix using your credentials and generates an access token:

\`\`\`bash
# Generate token and display it
python scripts/generate_token.py

# Generate token and automatically update config.json
python scripts/generate_token.py --update

# Use a different config file
python scripts/generate_token.py --config /path/to/config.json --update
\`\`\`

Using access tokens instead of passwords is recommended for security and to avoid repeated login attempts.

### Running Tests
\`\`\`bash
pytest  # Coming soon
\`\`\`

### Code Quality
\`\`\`bash
ruff check src/
black src/
\`\`\`

## 🐳 Docker

Build and run with Docker:

\`\`\`bash
docker build -t tool-bot:latest .
docker run --rm \\
  -e MATRIX_HOMESERVER="https://matrix.org" \\
  -e MATRIX_USER="@bot:example.org" \\
  -e MATRIX_PASSWORD="secret" \\
  -e ALLOWED_USERS="@user:example.org" \\
  -e LLM_PROVIDER="openai" \\
  -e OPENAI_API_KEY="sk-..." \\
  tool-bot:latest
\`\`\`

## 🏗️ Architecture

- **State Management**: No external database; builds conversation tree from Matrix history
- **Threading**: First message without reply spawns thread; proposals are threaded replies
- **Tool Proposals**: LLM generates structured proposals; user approves via reaction
- **Edit/Regenerate**: On message edit, old proposals are deleted and new ones generated
- **Cascade Deletions**: Deleting user message triggers recursive deletion of bot replies
- **Voice Pipeline**: Download → Transcribe (Whisper API) → Reply with transcript → Process with LLM
- **Restart Safety**: Loads last 100 messages per room on startup; tracks processed messages

See \`ARCHITECTURE.md\` for detailed implementation guide.

## 📝 License

[Add your license here]

## 🤝 Contributing

Contributions welcome! Please open an issue or PR.
