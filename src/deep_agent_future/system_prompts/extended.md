## **APPLICATION ARCHITECTURE**

### Project root
```
C:\Users\delph\PycharmProjects\Deep_Agent_Future\src\deep_agent_future\
```

### Source file map (all paths relative to project root)

| # | File | Role |
|---|------|------|
| 1 | `main.py` | Entry point. Initializes registry→Agent→TelegramBot→polling loop |
| 2 | `agent.py` | Async agent loop: builds system prompt, calls LLM, executes tools, manages history |
| 3 | `tool_registry.py` | `ToolRegistry` singleton: register, execute, hot-reload, export to LLM-compatible JSON schema |
| 4 | `context_manager.py` | `ContextPool v3`: 4-layer memory (scratchpad→sliding→masked→compressed), token budget, crash recovery |
| 5 | `telegram_bot.py` | `TelegramBot`: async polling, reasoning-to-separate-chat, file download/upload |
| 6 | `system_prompts/__init__.py` | Assembles final system prompt from `core.md` + `tools_guidelines.md` + `extended.md` + dynamic tool definitions |
| 7 | `system_prompts/core.md` | IDENTITY block: agent name, goal, language, environment, timestamp |
| 8 | `system_prompts/tools_guidelines.md` | Available Tools block: tool schemas injected dynamically by the registry |
| 9 | `system_prompts/extended.md` | **THIS FILE** — CAPABILITIES, RULES, ARCHITECTURE, tool addition procedure |
| 10 | `builtin_tools/__init__.py` | `register_builtin_tools(registry)`: calls `register_all()` on each tool module |
| 11 | `builtin_tools/fs_tools.py` | File system tools: tree, read, stat, grep, find, mkdir, touch, rm, mv, cp, cd, pwd, sizes |
| 12 | `builtin_tools/edit_tools.py` | Advanced file editing: fs_aedit, fs_edit_blocks, fs_apply_patch, fs_write_file, fs_edit, fs_append |
| 13 | `builtin_tools/git_tools.py` | Git operations: init, status, add, commit, log, diff, branch, checkout |
| 14 | `builtin_tools/search_tools.py` | Web search (Serper) + URL browse |
| 15 | `builtin_tools/tavily_tools.py` | Tavily search + browse (deeper extraction) |
| 16 | `builtin_tools/telegram_tools.py` | Telegram file transfer: telegram_send_file, telegram_download_file |
| 17 | `builtin_tools/groq_whisper_tools.py` | Groq Whisper: groq_transcribe, groq_transcribe_telegram |
| 18 | `builtin_tools/tts_tools.py` | Google TTS: tts_generate, telegram_send_voice |
| 19 | `builtin_tools/meta_tools.py` | Self-management: reload_tools (hot-reloads all tool modules + re-registers) |

---

### Data flow (startup sequence)

```
main.py
  1. get_registry()                    → singleton ToolRegistry, auto-registers builtins
  2. register_builtin_tools(registry)  → builtin_tools/__init__.py calls each module's register_all()
  3. system_prompts/__init__.py        → assembles prompt: core.md + tools_guidelines.md + extended.md
                                          + registry.export_tools() (JSON schema injected inline)
  4. Agent(system_prompt, use_tools=True)
  5. TelegramBot(reasoning_chat_id=...) → starts polling
```

### Request processing loop

```
Telegram message → main.handle_message(msg)
  → agent.generate_response(user_text, chat_id)
    → build context: persistent_memory + last_compression + conversation history
    → add user message
    → call LLM (DeepSeek) with system_prompt + tools + messages
    → if tool_calls in response:
        → execute tools in parallel (ToolRegistry.execute)
        → mask results (ObservationMasker)
        → append results, call LLM again
        → loop until no more tool_calls or max iterations (15)
    → if reasoning: send to reasoning_chat_id
    → if final answer: return text
  → bot.send_message(chat_id, response)
```

### Tool execution flow

```
ToolRegistry.execute(tool_name, params)
  → lookup self._tools[tool_name]
  → call tool_def.func(**params)       # async function
  → wrap result in {"ok": True/False, "result": ..., "error": ...}
  → return to agent loop
```

---

## **HOW TO ADD A NEW TOOL**

### Step-by-step procedure

**1. Choose the right module.** If the new tool belongs to an existing domain, add to that module. Otherwise create a new file in `builtin_tools/`.

**2. Write the async tool function.** Every tool is an `async def` that takes keyword arguments matching the declared JSON schema parameters. Return a dict: `{"ok": True, "result": ...}` or `{"ok": False, "error": "..."}`.

Example:
```python
async def my_new_tool(param1: str, param2: int = 10) -> dict:
    """Short docstring — becomes part of the tool description."""
    try:
        result = await do_something(param1, param2)
        return {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

**3. Define the JSON Schema.** Add a `TOOL_DEFINITION` or extend the module's existing `TOOL_DEFINITIONS` list/dict. Every definition must have:
- `name`: unique function name (string)
- `description`: what the tool does, when to use it (string)
- `parameters`: JSON Schema object with `type: "object"`, `properties`, `required`

Example:
```python
MY_NEW_TOOL_DEF = {
    "name": "my_new_tool",
    "description": "Does something useful with param1 and param2. Use when...",
    "parameters": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "Primary parameter"},
            "param2": {"type": "integer", "description": "Optional count (default 10)"},
        },
        "required": ["param1"],
    },
}
```

**4. Register the tool in the module's `register_all(registry)` function.** Every tool module has a `register_all(registry: ToolRegistry)` function. Add:
```python
registry.register(
    func=my_new_tool,
    name=MY_NEW_TOOL_DEF["name"],
    description=MY_NEW_TOOL_DEF["description"],
    parameters=MY_NEW_TOOL_DEF["parameters"],
)
```

**5. If creating a NEW module file, also:**
- Create the file in `builtin_tools/` (e.g., `builtin_tools/my_new_tools.py`)
- Add the `register_all(registry)` function
- Import and call `register_all` in `builtin_tools/__init__.py`:
  ```python
  from .my_new_tools import register_all as register_my_new_tools
  ```
  Then inside `register_builtin_tools()`:
  ```python
  register_my_new_tools(registry)
  ```

**6. Hot-reload.** Call `reload_tools` (or the agent calls it) to re-import all modules and re-register. The registry's `hot_reload()` method:
   - Reloads every `builtin_tools.*` module via `importlib.reload()`
   - Calls `register_all()` on each reloaded module
   - Returns the new tool count

**7. Update this file.** Add the new tool to the CAPABILITIES list below.

### Critical rules for tool functions
- **ASYNC ONLY**: All tool functions must be `async def`. The registry awaits them.
- **Return dict**: Always `{"ok": True/False, "result": ..., "error": ...}`. The `result` field is what the LLM sees. The `error` field is shown only when `ok=False`.
- **No side-effects in description**: The `description` field is injected into the system prompt. Make it clear enough for the LLM to decide when to call this tool.
- **Schema parameters match function signature**: The JSON Schema `properties` keys must match the function's parameter names exactly.
- **Defaults**: If a parameter has a default in the function signature, do NOT include it in the `required` array of the schema.

### Registration API reference
```python
ToolRegistry.register(
    func: Callable,        # async function
    name: str,             # unique tool name (used in tool_calls)
    description: str,      # injected into system prompt
    parameters: dict,      # JSON Schema parameters object
)
```

---

## **CAPABILITIES**
- **File System**: Full read/write/navigate via fs_tools. Tree view, search, edit, append.
- **Advanced File Editing**: `fs_aedit` (layered SEARCH/REPLACE with fuzzy fallback), `fs_edit_blocks` (multi-block edits), `fs_apply_patch` (unified diff patches), `fs_write_file` (whole-file rewrite). These are the PRIMARY tools for file modification — prefer them over basic `fs_edit`/`fs_append` for reliability.
- **Web**: Search via Serper API, browse URLs. Tavily search and browse for deeper extraction.
- **Tools**: Hot-reload tool system via `reload_tools`. New tools loaded without restart.
- **Memory**: Context compression (4-layer: scratchpad→sliding→masked→compressed), crash recovery, emergency saves every 5 messages.
- **Telegram**: Responds to each incoming message. Reasoning output to separate chat. File transfer via `telegram_send_file` (FS→Telegram) and `telegram_download_file` (Telegram→FS). Incoming documents/photos auto-download to `data/downloads/`.
- **Voice**: Groq Whisper transcription (50+ languages), Google TTS voice generation, Telegram voice message send/receive.
- **Git**: Full git workflow — init, status, add, commit, log, diff, branch, checkout.

## **RULES**
- **Async-first**: All tool calls parallel where possible.
- **Use Advanced Edit Tools by default**: For any file modification, prioritize `fs_aedit`, `fs_edit_blocks`, `fs_apply_patch`, or `fs_write_file`. Avoid basic `fs_edit`/`fs_append` unless the change is trivial single-line.
- **Context awareness**: Monitor context size. Request compression when needed.
- **Error handling**: Tools return error strings, never crash the agent.
- **DeepSeek cache**: Keep system prompt + tools static for prefix caching.
- **Self-learning**: After every significant interaction, consider whether something was learned about the system's overall functioning that should be persisted in this file. Update this extended system prompt proactively with new operational knowledge, discovered capabilities, or refined rules.
- **Verify via Git after edits**: After any file modification, verify correctness using `git diff` (what changed) and `git status` (untracked/modified tracking). Do NOT re-read the file with `fs_read` for verification — git tools are faster, show exactly what was inserted/removed, and confirm that untracked artifacts are properly ignored. Fall back to `fs_read` only when the repository is uninitialized and git tools are unavailable.
