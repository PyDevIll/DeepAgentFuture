## **Available Tools**

### File System (`fs_*`)
- `fs_tree` — Recursive directory listing with sizes and dates
- `fs_read` — Read file content with binary detection and size-aware truncation
- `fs_stat` — File/directory metadata
- `fs_grep` — Recursive case-insensitive text search
- `fs_find` — Find files by case-insensitive glob pattern
- `fs_mkdir` — Create directory recursively
- `fs_touch` — Create empty file or update mtime
- `fs_rm` — Delete file or directory
- `fs_mv` — Move/rename file or directory
- `fs_cp` — Copy file or directory
- `fs_cd` — Change agent's virtual working directory
- `fs_pwd` — Print agent's virtual working directory
- `fs_sizes` — List largest files in directory
- `fs_edit` — Replace lines in a text file (line numbers 1-indexed, inclusive)
- `fs_append` — Append text to end of file

### Web Search & Browse
- `search_web` — Search the web using Google via Serper API
- `browse_url` — Fetch and extract content from a URL
- `tavily_search` — Search the web using Tavily Search API (advanced, images, raw content, domain filters)
- `tavily_browse` — Browse and extract clean content from URLs using Tavily Extract (Markdown/text)

### Git
- `git_init` — Initialize a git repository
- `git_status` — Show working tree status
- `git_add` — Add file contents to the index
- `git_commit` — Record changes to the repository
- `git_log` — Show last N commit logs (oneline format)
- `git_diff` — Show changes (--stat format)
- `git_branch` — List branches
- `git_checkout` — Switch branches

### Advanced File Editing (`fs_a*`, `fs_w*`, `fs_apply_patch`, `fs_edit_blocks`)
- `fs_aedit` — Advanced file editing with layered matching (exact→whitespace→fuzzy)
- `fs_apply_patch` — Apply unified diff patch to a file
- `fs_write_file` — Write complete file content (whole-file rewrite)
- `fs_edit_blocks` — Apply multiple SEARCH/REPLACE edit blocks at once

### Meta
- `reload_tools` — Hot-reload all builtin tool modules without restarting

## **Tool Execution**
- Tools are async — multiple independent calls run in parallel.
- Each tool returns a string result.
- On error, tool returns error message (never exception to agent).
- Hot-reload: call `reload_tools` after creating/editing tool files to pick up changes without restart.

