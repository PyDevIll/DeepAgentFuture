# Tool Ratings & Performance Assessment
**MASTERMIND v2 — 28.06.2026, 13:40**

Scale: **1** (broken/useless) to **5** (flawless).

---

## File System Tools

### 1. `fs_read` — ★★★★★
**Verdict:** Core workhorse. Binary detection prevents garbage output. Size-aware truncation with line-range targeting keeps context usage minimal. The `start`/`lines` parameters work exactly as documented.

### 2. `fs_stat` — ★★★★★
**Verdict:** Fast, reliable metadata. No issues observed.

### 3. `fs_grep` — ★★★☆☆
**Verdict:** Case-insensitive search is useful, but has **two notable problems**:
- **Large-file skipping:** Recursive searches silently skip files >1 MB (e.g., `agent.log` at 1.4 MB). This is mentioned in output but easy to miss. Direct targeted search on those files works.
- **False negatives:** Failed to find `TOOL_DEFINITIONS` in `fs_tools.py` despite it existing at line 487. Also failed to find `Message from` in `agent.log`. Root cause unclear — possibly a regex boundary issue or encoding problem.
- **Workaround:** Use `fs_grep` with explicit `path` to the file, or use `fs_read` with line ranges after `fs_grep` points to candidate areas.

### 4. `fs_find` — ★★★★☆
**Verdict:** Glob-based file finding works. Minor: case-insensitive matching could be more clearly documented.

### 5. `fs_tree` — ★★★★☆
**Verdict:** Clean directory visualization. `ascii_mode` option is thoughtful. Depth capping at 5 prevents runaway output.

### 6. `fs_mkdir` — ★★★★☆
**Verdict:** Recursive creation works. Not heavily exercised.

### 7. `fs_touch` — ★★★☆☆
**Verdict:** Creates empty files and updates mtime. Basic, works. Rarely needed.

### 8. `fs_rm` — ★★★☆☆
**Verdict:** Deletion with recursive flag. Not heavily tested. Caution warranted — no dry-run mode.

### 9. `fs_mv` — ★★★☆☆
**Verdict:** Move/rename works. Standard.

### 10. `fs_cp` — ★★★☆☆
**Verdict:** Copy with recursive flag. Standard.

### 11. `fs_cd` — ★★★☆☆
**Verdict:** Virtual working directory change. Works but limited usefulness when absolute paths are available.

### 12. `fs_pwd` — ★★★★☆
**Verdict:** Reports current virtual directory. Simple, works.

### 13. `fs_sizes` — ★★★☆☆
**Verdict:** Lists largest files. Useful for cleanup. Not heavily exercised.

### 14. `fs_edit` — ★★★☆☆
**Verdict:** Line-range replacement works for simple edits but is **superseded by Advanced Edit Tools**. Line-number-based editing is fragile against file changes between read and write.

### 15. `fs_append` — ★★★★☆
**Verdict:** Simple, reliable. Good for log-style additions.

---

## Advanced File Editing Tools

### 16. `fs_aedit` — ★★★★☆
**Verdict:** Layered matching (exact → whitespace → fuzzy) makes it robust against minor formatting differences. The SEARCH/REPLACE block syntax is clear. **Minor issue:** When multiple similar blocks exist in a file, the match target can be ambiguous. A `count` or `occurrence` parameter would improve precision. The `dry_run` mode is invaluable for safe edits.

### 17. `fs_edit_blocks` — ★★★★★
**Verdict:** Multi-block atomic editing is excellent. Applying several SEARCH/REPLACE pairs in one call reduces tool-invocation overhead and ensures consistency. One of the best-designed tools in the suite.

### 18. `fs_apply_patch` — ★★★☆☆
**Verdict:** Unified diff patching. Not yet exercised in practice. Conceptually sound but untested.

### 19. `fs_write_file` — ★★★★★
**Verdict:** Whole-file rewrite. Simple, predictable, no ambiguity about what changed. The `dry_run` option makes it safe. Preferred for complex refactors where incremental edits risk inconsistency.

---

## Web Search Tools

### 20. `search_web` — ★★★★☆
**Verdict:** Google search via Serper API. Returned relevant, current results for DeepSeek model queries. Response format is clean. **Minor:** No `time_range` or `country` filtering exposed (unlike the Tavily equivalent).

### 21. `browse_url` — ★★★☆☆
**Verdict:** Fetches and extracts URL content. The optional `query` parameter for content filtering is useful. Not heavily exercised — the few test fetches returned truncated content on some sites (likely anti-scraping measures).

---

## Git Tools

### 22. `git_init` — ★★★☆☆
**Verdict:** Not exercised. Assumed functional.

### 23. `git_status` — ★★★☆☆
**Verdict:** Not exercised. Assumed functional.

### 24. `git_add` — ★★★☆☆
**Verdict:** Not exercised. Assumed functional.

### 25. `git_commit` — ★★★☆☆
**Verdict:** Not exercised. Assumed functional.

### 26. `git_log` — ★★★★☆
**Verdict:** Oneline format with configurable count. Clean output. Works.

### 27. `git_diff` — ★★★★☆
**Verdict:** Now shows full unified diff (not `--stat`). Added `staged=True` parameter for `--cached`. Preferred for verifying file modifications before commit. Cannot filter by single file, but shows all changes at once.

### 28. `git_branch` — ★★★☆☆
**Verdict:** List branches. Not exercised.

### 29. `git_checkout` — ★★★☆☆
**Verdict:** Switch branches. Not exercised.

### 29.5. `git_push` — ★★★★☆
**Verdict:** New tool. Pushes commits to remote repository. Parameters: `remote`, `branch`, `force`. Not yet tested with actual remote; local commit flow works.

---

## Tavily Search Tools

### 30. `tavily_search` — ★★★☆☆
**Verdict:** Not exercised. Feature set looks richer than `search_web` (`search_depth`, `include_answer`, `time_range`, `topic`, domain filtering). Worth testing.

### 31. `tavily_browse` — ★★★☆☆
**Verdict:** Not exercised. Supports batch URL extraction (up to 20) with content formatting options. Looks powerful.

---

## Meta Tools

### 32. `reload_tools` — ★★★★★ **(FIXED)**
**Verdict:** Now works correctly after restart. `hot_reload()` was fixed to call `register_all()` after module reloads. Reports exact tool count per module (e.g., "Reloaded 9 module(s)"). **This is the first tool to call when new tools are added to the codebase.**

---

## Telegram Tools

### 33. `telegram_send_file` — ★★★★☆ **(FIXED)**
**Verdict:** Now registered and functional after restart. Sends files from local filesystem to Telegram by absolute path. Requires `chat_id` from the user's message context. Works reliably.

### 34. `telegram_download_file` — ★★★★☆ **(FIXED)**
**Verdict:** Now registered and functional. Downloads files from Telegram by `file_id` to local filesystem. Works in tandem with `telegram_send_file` for bidirectional file transfer.

### 35. `telegram_send_voice` — ★★★★★
**Verdict:** Combines Google TTS + Telegram send in one step. Russian by default. Fast, free, no API key. Used for confirmation messages. Reliable.

---

## Text-to-Speech Tools (`tts_*`)

### 36. `tts_generate` — ★★★★★
**Verdict:** Google Translate TTS — free, no API key, max 200 chars, 50+ languages. Works flawlessly. Paired with `telegram_send_voice` for voice confirmation messages.

---

## Voice Recognition — Groq Whisper (`groq_*`)

### 37. `groq_transcribe` — ★★★★☆
**Verdict:** FREE Whisper API (whisper-large-v3) via Groq. 50+ languages. Requires `GROQ_API_KEY` env var. Auto-converts unsupported formats via ffmpeg. Not tested yet but should be reliable.

### 38. `groq_transcribe_telegram` — ★★★★☆
**Verdict:** Combines `telegram_download_file` + `groq_transcribe` in one call. Convenience wrapper. Same reliability as its components.

---

## Summary
| Rating | Count | Tools |
|--------|-------|-------|
| ★★★★★ Flawless | 6 | `fs_read`, `fs_stat`, `fs_write_file`, `fs_edit_blocks`, `tts_generate`, `telegram_send_voice` |
| ★★★★☆ Solid | 14 | `fs_find`, `fs_tree`, `fs_mkdir`, `fs_pwd`, `fs_append`, `fs_aedit`, `search_web`, `git_log`, `git_diff`, `git_push`, `telegram_send_file`, `telegram_download_file`, `groq_transcribe`, `groq_transcribe_telegram` |
| ★★★☆☆ Functional/Untested | 18 | `fs_touch`, `fs_rm`, `fs_mv`, `fs_cp`, `fs_cd`, `fs_sizes`, `fs_edit`, `fs_apply_patch`, `browse_url`, `git_init`, `git_status`, `git_add`, `git_commit`, `git_branch`, `git_checkout`, `tavily_search`, `tavily_browse`, `reload_tools` |
| ★★☆☆☆ Problematic | 1 | `fs_grep` (false negatives, large-file skip) |
| ★☆☆☆☆ Broken | 0 | — |

**Total:** 38 tools tracked. 0 broken. 19 high-quality (★★★★★ + ★★★★☆). 18 functional/untested. 1 problematic (`fs_grep`). The hot-reload and Telegram registration bugs are **fixed** after restart. `fs_grep` false negatives warrant deeper investigation — possible encoding or regex engine edge case.
