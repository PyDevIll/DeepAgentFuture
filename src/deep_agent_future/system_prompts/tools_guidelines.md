## **Available Tools**

### File System (`fs_*`)
- `fs_tree` — Recursive directory listing
- `fs_read` — Read file (binary detect, auto-truncate >50KB)
- `fs_stat` — File/directory metadata
- `fs_grep` — Recursive text search
- `fs_find` — Find by glob pattern
- `fs_mkdir` — Create directory
- `fs_touch` — Create/update file
- `fs_rm` — Delete (--recursive for dirs)
- `fs_mv` — Move/rename
- `fs_cp` — Copy
- `fs_cd` — Change working directory
- `fs_pwd` — Print working directory
- `fs_sizes` — Largest files
- `fs_edit` — Replace lines in file
- `fs_append` — Append to file

### Web
- `search_web` — Google search via Serper
- `browse_url` — Fetch URL content

## **Tool Execution**
- Tools are async — multiple independent calls run in parallel.
- Each tool returns a string result.
- On error, tool returns error message (never exception to agent).
- Hot-reload: registry.check_version() before each agent iteration.
