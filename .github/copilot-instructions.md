# Coding
## Comments
- Don't use comments to express the content of code sections.
- Use comments only to explain complex logic that isn't immediately clear from the code.
- Focus comments on the "why" rather than the "what".
- Avoid obvious comments that do not add value.
- Document async operations, Matrix protocol specifics, and API interactions where helpful.

## Imports
- Always import at the top of the file.
- Group imports: standard library, third-party, local modules.
- Use absolute imports for tool_bot modules (e.g., `from tool_bot.config import Config`).

## Packages
- This project uses Nix for system dependencies and pip for Python packages.
- Python packages should be added to requirements.txt.
- To install packages, update requirements.txt and run `pip install -r requirements.txt` inside the venv.
- When using Nix shell, dependencies are automatically installed via the shellHook in shell.nix.

## Async Code
- All Matrix client operations are async and must be awaited.
- Use `asyncio` patterns consistently.
- Handle async exceptions appropriately.

## Error Handling
- Provide helpful error messages when external services (Anki-Connect, Todoist) are unavailable.
- Log errors with appropriate context.
- Don't let exceptions crash the bot; handle them gracefully.

# Documentation
- In Markdown files, write one sentence per line.
- Every sentence starts a new line.
- This improves diff readability and makes version control easier.
