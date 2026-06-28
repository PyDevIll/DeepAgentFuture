## Available Tools — Guidelines & Best Practices

### File System (`fs_*`)
Certainly. Below is the revised `tools_guidelines.md` in formal English, preserving all the added ratings, notes, and best practices from your agent's modifications, while restoring a clear, instructional, and professional tone.

---

## Available Tools — Guidelines & Best Practices

This document describes all built‑in tools available to the MASTERMIND v2 agent, along with practical usage notes, reliability ratings, and critical warnings.

---

### File System Tools (`fs_*`)

| Tool | Rating | Notes                                                                                                                                                           |
|------|--------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `fs_read` | ★★★★★ | Primary file reader. Detects binary content, truncates large files. Parameters `start` and `lines` work reliably.                                               |
| `fs_stat` | ★★★★★ | Quick metadata retrieval. No known issues.                                                                                                                      |
| `fs_grep` | ★★★☆☆ | Case‑insensitive recursive text search. **Caveats:** silently skips files >1 MB; occasional false negatives. **Workaround:** target a specific file via `path`. |
| `fs_find` | ★★★★☆ | Glob‑based file search. Reliable for locating files by name patterns.                                                                                           |
| `fs_tree` | ★★★★☆ | Recursive directory listing with sizes and dates. `ascii_mode` prevents encoding issues. Maximum depth 5.                                                       |
| `fs_mkdir` | ★★★★☆ | Creates directories recursively.                                                                                                                                |
| `fs_touch` | ★★★☆☆ | Creates an empty file or updates modification time. Infrequently used.                                                                                          |
| `fs_rm` | ★★★☆☆ | Deletes files or directories. **Caution:** no dry‑run mode; use with care.                                                                                      |
| `fs_mv` | ★★★☆☆ | Moves or renames files/directories.                                                                                                                             |
| `fs_cp` | ★★★☆☆ | Copies files (use `recursive=True` for directories).                                                                                                            |
| `fs_cd` | ★★★☆☆ | Changes the agent’s virtual working directory. Rarely needed when using absolute paths.                                                                         |
| `fs_pwd` | ★★★★☆ | Prints the current virtual working directory. Simple and effective.                                                                                             |
| `fs_sizes` | ★★★☆☆ | Lists largest files in a directory – useful for clean‑up.                                                                                                       |
| `fs_edit` | ★★★☆☆ | Line‑range replacement (1‑indexed). **Deprecated:** prefer `fs_aedit` or `fs_edit_blocks` – brittle due to line‑number drift between reads and writes.          |
| `fs_append` | ★★★★☆ | Appends text to the end of a file. Simple and reliable.                                                                                                         |

---

### Advanced File Editing (`fs_a*`, `fs_w*`, `fs_apply_patch`, `fs_edit_blocks`)

| Tool | Rating | Notes |
|------|--------|-------|
| `fs_aedit` | ★★★★☆ | SEARCH/REPLACE with layered matching (exact → whitespace‑normalised → fuzzy). Superior to `fs_edit`. `dry_run` provides safe previews. |
| `fs_edit_blocks` | ★★★★★ | **Recommended editor.** Applies multiple SEARCH/REPLACE blocks atomically in a single call – reduces round‑trips and ensures consistency. |
| `fs_apply_patch` | ★★★☆☆ | Applies unified diff patches. Not yet thoroughly tested in production. |
| `fs_write_file` | ★★★★★ | Overwrites an entire file. Predictable and safe. Use `dry_run` before committing changes. |

---

### Web Search & Browse

| Tool | Rating | Notes |
|------|--------|-------|
| `search_web` | ★★★★☆ | Google search via Serper API. Returns relevant results but lacks time/country filters (available in Tavily). |
| `browse_url` | ★★★☆☆ | Extracts content from a given URL. Optional `query` filters relevant text. May be truncated on some sites (anti‑scraping measures). |
| `tavily_search` | ★★★☆☆ | **Not yet tested.** On paper more powerful than `search_web`: supports `search_depth`, `include_answer`, `time_range`, `topic`, and domain filters. |
| `tavily_browse` | ★★★☆☆ | **Not yet tested.** Batch extraction for up to 20 URLs. Outputs Markdown or plain text. Looks promising. |

---

### Git

| Tool | Rating | Notes |
|------|--------|-------|
| `git_init` | ★★★☆☆ | Initialises a new Git repository. Not yet tested. |
| `git_status` | ★★★☆☆ | Shows working tree status. Not yet tested. |
| `git_add` | ★★★☆☆ | Stages files for commit. Not yet tested. |
| `git_commit` | ★★★☆☆ | Records changes with a message. Not yet tested. |
| `git_log` | ★★★★☆ | Displays commit logs in oneline format. Output is clean and readable. |
| `git_diff` | ★★★★☆ | Shows changes as unified diff. Use `staged=True` for `--cached`. Displays all changes at once. |
| `git_branch` | ★★★☆☆ | Lists branches. Not yet tested. |
| `git_checkout` | ★★★☆☆ | Switches branches. Not yet tested. |
| `git_push` | ★★★★☆ | Pushes commits to a remote. Parameters: `remote`, `branch`, `force`. Local workflow is functional. |

---

### Telegram (`telegram_*`)

| Tool | Rating | Notes |
|------|--------|-------|
| `telegram_send_file` | ★★★★☆ | Sends a file by absolute path. Requires `chat_id` obtained from the user’s message context. |
| `telegram_download_file` | ★★★★☆ | Downloads a file from Telegram using a `file_id`. |
| `telegram_send_voice` | ★★★★★ | Combines Google TTS and Telegram voice send in one call. Default language: Russian. **Important:** input text must be TTS‑ready – no special characters (e.g., `\`, `:`, `;`, `_`), no code, no URLs. |

---

### Text‑to‑Speech (`tts_*`)

| Tool | Rating | Notes |
|------|--------|-------|
| `tts_generate` | ★★★★★ | Generates MP3 audio from text using Google Translate TTS. **Completely free**, no API key required. Max 200 characters. Supports 50+ languages. |

---

### Voice Recognition — Groq Whisper (`groq_*`)

| Tool | Rating | Notes |
|------|--------|-------|
| `groq_transcribe` | ★★★★☆ | Transcribes audio via Groq’s free Whisper API (whisper‑large‑v3). 50+ languages. Requires `GROQ_API_KEY` environment variable. Auto‑converts unsupported formats via ffmpeg. |
| `groq_transcribe_telegram` | ★★★★☆ | Downloads a Telegram voice message by `file_id` and transcribes it in a single combined call. Convenient for voice workflows. |

---

### REST API (`rest_api_call`)

| Tool | Rating | Notes |
|------|--------|-------|
| `rest_api_call` | ★★★★★ | **Universal REST client.** Supports GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS. Features: query parameters, headers, JSON/form/multipart bodies, authentication (Basic/Bearer), cookies, proxy, SSL verification, and timeout. Default proxy: `socks5://127.0.0.1:1080` (external IP in Germany). |

---

### Shell & Python (`exec_*`)

| Tool | Rating | Notes |
|------|--------|-------|
| `exec_python` | ★★★★☆ | Executes Python code: inline via `-c` or from a `.py` file. |
| `exec_shell` | ★★★★★ | **Full shell access** on Windows (cmd.exe /c). Supports pipes, redirects, batch scripts. **⚠️ Caution:** provides full system access – use responsibly. |

---

### Meta

| Tool | Rating | Notes |
|------|--------|-------|
| `reload_tools` | ★★★★★ | **Always call first after adding or modifying tools.** Hot‑reloads all built‑in modules and re‑runs `register_all()`. Reports "Reloaded N module(s)" and shows the tool list. |
| `ping` | ★★★★★ | Simple health‑check. Returns "pong" with a timestamp. |

---

## Tool Execution — General Rules

- **All tools are asynchronous** — independent calls can be executed in parallel for efficiency.
- **Return value:** every tool returns a **string** result. On error, the tool returns a descriptive error message (exceptions are never propagated to the agent).
- **Hot‑reload:** after creating or editing any tool module, call `reload_tools` to load the changes without restarting the agent.

---

## General Best Practices

1. **Editing files:** always `fs_read` first, then use `fs_aedit` or `fs_edit_blocks` with `dry_run=True` to preview changes, then apply without `dry_run`.
2. **Searching:** for `fs_grep`, prefer targeting a specific file first; then use recursive search if needed. Remember the 1 MB size limit.
3. **Web requests:** the default proxy `socks5://127.0.0.1:1080` provides a Frankfurt‑based external IP (`45.43.89.52`). Use it when necessary.
4. **Git:** use `git_diff` before `git_commit` to review changes.
5. **New tools:** after adding any new tool module, immediately call `reload_tools` to make it available.

---

This guide serves as the authoritative reference for tool capabilities, reliability, and safe usage.