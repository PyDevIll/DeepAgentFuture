## **CAPABILITIES**
- **File System**: Full read/write/navigate via fs_tools. Tree view, search, edit, append.
- **Web**: Search via Serper API, browse URLs.
- **Tools**: Hot-reload tool system. New tools loaded without restart.
- **Memory**: Context compression, crash recovery, emergency saves every 5 messages.
- **Telegram**: Responds to each incoming message. Reasoning output to separate chat.

## **RULES**
- **Async-first**: All tool calls parallel where possible.
- **Context awareness**: Monitor context size. Request compression when needed.
- **Error handling**: Tools return error strings, never crash the agent.
- **DeepSeek cache**: Keep system prompt + tools static for prefix caching.
