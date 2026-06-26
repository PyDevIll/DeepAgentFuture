"""File system tools for MASTERMIND v2 — async, registry-integrated."""

import os
import stat
import fnmatch
import shutil
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

_current_dir: Path = Path.cwd()


def _safe_path(path: str) -> Path:
    """Resolve path relative to agent's virtual cwd."""
    p = Path(path)
    if not p.is_absolute():
        p = _current_dir / p
    return p.resolve()


def human_size(size_bytes: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _is_binary(filepath: str, sample_size: int = 1024) -> bool:
    try:
        with open(filepath, 'rb') as f:
            data = f.read(sample_size)
    except Exception:
        return False
    if not data:
        return False
    if b'\x00' in data:
        return True
    printable = set(range(0x20, 0x7f)) | {0x09, 0x0a, 0x0d}
    non_printable = sum(1 for b in data if b not in printable)
    return (non_printable / len(data)) > 0.30


async def fs_tree(path: str = ".", depth: int = 2, ascii_mode: bool = False) -> str:
    """Recursive directory listing with sizes and dates."""
    p = _safe_path(path)
    if not p.exists():
        return f"Path not found: {path}"
    lines = []

    def _tree(current: Path, d: int, prefix: str) -> None:
        if d < 0:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            lines.append(f"{prefix}Permission denied: {current}")
            return
        for i, entry in enumerate(entries):
            is_last = (i == len(entries) - 1)
            connector = "`-- " if (ascii_mode and is_last) else ("|-- " if ascii_mode else ("\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "))
            size_str = human_size(entry.stat().st_size) if entry.is_file() else "0.0 B"
            mod_str = datetime.fromtimestamp(entry.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"{prefix}{connector}{entry.name}  {size_str}  {mod_str}")
            if entry.is_dir() and not entry.name.startswith('.'):
                sub_prefix = prefix + ("    " if is_last else ("    " if ascii_mode else "\u2502   "))
                _tree(entry, d - 1, sub_prefix)

    _tree(p, min(depth, 5), "")
    return '\n'.join(lines)


async def fs_read(file: str, lines: int = 30, start: int = 1) -> str:
    """Read file content with binary detection and size-aware truncation."""
    p = _safe_path(file)
    if not p.exists():
        return f"File not found: {file}"
    if lines > 80:
        lines = 80
    try:
        size = p.stat().st_size
    except OSError as e:
        return f"Error: {e}"
    if _is_binary(str(p)):
        return f"Binary file detected ({human_size(size)})"
    try:
        content = p.read_text(encoding='utf-8', errors='replace')
    except Exception as e:
        return f"Error reading file: {e}"
    all_lines = content.split('\n')
    total = len(all_lines)
    if size > 50 * 1024:
        first = all_lines[:20]
        last = all_lines[-10:] if total >= 10 else []
        out = [f"File is {human_size(size)} (>50KB). First 20 + last 10 lines:"]
        for i, line in enumerate(first, 1):
            out.append(f"{i:>6}: {line}")
        if total > 30:
            out.append(f"... ({total - 30} lines omitted)")
        for i, line in enumerate(last, max(1, total - 9)):
            out.append(f"{i:>6}: {line}")
        return '\n'.join(out)
    start_idx = max(0, start - 1)
    end_idx = min(total, start_idx + lines)
    out = []
    for i in range(start_idx, end_idx):
        out.append(f"{i+1:>6}: {all_lines[i]}")
    if end_idx < total:
        out.append(f"... ({total - end_idx} more lines)")
    return '\n'.join(out)


async def fs_stat(path: str) -> str:
    """File/directory metadata."""
    p = _safe_path(path)
    if not p.exists():
        return f"Not found: {path}"
    st = p.stat()
    ftype = "directory" if p.is_dir() else "file"
    lines = [
        f"Path: {p}",
        f"Type: {ftype}",
        f"Size: {human_size(st.st_size)}",
        f"Modified: {datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d %H:%M:%S')}",
        f"Permissions: {stat.filemode(st.st_mode)}",
    ]
    if not p.is_dir():
        try:
            line_count = p.read_text(encoding='utf-8', errors='replace').count('\n')
            lines.append(f"Lines: {line_count}")
        except Exception:
            pass
    return '\n'.join(lines)


async def fs_grep(pattern: str, path: str = ".", ext: str = "") -> str:
    """Recursive case-insensitive text search."""
    p = _safe_path(path)
    if not p.exists():
        return f"Path not found: {path}"
    pattern_lower = pattern.lower()
    matches = []
    for fp in p.rglob("*"):
        if fp.is_file():
            if ext and not fp.name.endswith(ext):
                continue
            try:
                for lineno, line in enumerate(fp.read_text(encoding='utf-8', errors='replace').split('\n'), 1):
                    if pattern_lower in line.lower():
                        matches.append(f"{fp}:{lineno}:{line.rstrip()}")
            except Exception:
                pass
    if not matches:
        return f"No matches for '{pattern}' in {path}"
    return '\n'.join(matches[:100])


async def fs_find(path: str = ".", name: str = "*") -> str:
    """Find files by case-insensitive glob pattern."""
    p = _safe_path(path)
    if not p.exists():
        return f"Path not found: {path}"
    pattern_lower = name.lower()
    matches = []
    for fp in p.rglob("*"):
        if fnmatch.fnmatch(fp.name.lower(), pattern_lower):
            matches.append(str(fp))
    if not matches:
        return f"No matches for '{name}' in {path}"
    return '\n'.join(matches[:100])


async def fs_mkdir(path: str) -> str:
    """Create directory recursively."""
    p = _safe_path(path)
    p.mkdir(parents=True, exist_ok=True)
    return f"Created directory: {p}"


async def fs_touch(path: str) -> str:
    """Create empty file or update mtime."""
    p = _safe_path(path)
    if p.exists():
        p.touch()
        return f"Updated mtime: {p}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch()
    return f"Created empty file: {p}"


async def fs_rm(path: str, recursive: bool = False) -> str:
    """Delete file or directory."""
    p = _safe_path(path)
    if not p.exists():
        return f"Not found: {path}"
    if p.is_dir():
        if recursive:
            shutil.rmtree(str(p))
            return f"Removed directory: {p}"
        return f"Cannot remove directory without recursive=True: {p}"
    p.unlink()
    return f"Removed file: {p}"


async def fs_mv(src: str, dst: str) -> str:
    """Move/rename file or directory."""
    sp = _safe_path(src)
    dp = _safe_path(dst)
    if not sp.exists():
        return f"Source not found: {src}"
    dp.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(sp), str(dp))
    return f"Moved: {sp} -> {dp}"


async def fs_cp(src: str, dst: str, recursive: bool = False) -> str:
    """Copy file or directory."""
    sp = _safe_path(src)
    dp = _safe_path(dst)
    if not sp.exists():
        return f"Source not found: {src}"
    dp.parent.mkdir(parents=True, exist_ok=True)
    if sp.is_dir():
        if recursive:
            shutil.copytree(str(sp), str(dp), dirs_exist_ok=True)
            return f"Copied directory: {sp} -> {dp}"
        return f"Cannot copy directory without recursive=True: {sp}"
    shutil.copy2(str(sp), str(dp))
    return f"Copied file: {sp} -> {dp}"


async def fs_cd(path: str) -> str:
    """Change agent's virtual working directory."""
    global _current_dir
    p = _safe_path(path)
    if not p.exists():
        return f"Path not found: {path}"
    if not p.is_dir():
        return f"Not a directory: {path}"
    _current_dir = p
    return f"Changed directory to: {p}"


async def fs_pwd() -> str:
    """Print agent's virtual working directory."""
    return str(_current_dir)


async def fs_sizes(path: str = ".", top: int = 20) -> str:
    """List largest files in directory."""
    p = _safe_path(path)
    if not p.exists():
        return f"Path not found: {path}"
    entries = []
    for fp in p.rglob("*"):
        if fp.is_file():
            try:
                entries.append((fp.stat().st_size, str(fp)))
            except OSError:
                pass
    entries.sort(key=lambda x: -x[0])
    lines = []
    for sz, fp in entries[:top]:
        lines.append(f"{human_size(sz):>10}  {fp}")
    if len(entries) > top:
        lines.append(f"... ({len(entries) - top} more files)")
    return '\n'.join(lines)


async def fs_edit(file: str, start_line: int, end_line: int, new_content: str) -> str:
    """Replace lines in a text file. Line numbers are 1-indexed, inclusive."""
    p = _safe_path(file)
    if not p.exists():
        return f"File not found: {file}"
    if _is_binary(str(p)):
        return "Cannot edit binary file"
    try:
        content = p.read_text(encoding='utf-8')
    except Exception as e:
        return f"Error reading file: {e}"
    lines_list = content.split('\n')
    if start_line < 1:
        start_line = 1
    if end_line > len(lines_list):
        end_line = len(lines_list)
    if start_line > end_line:
        return f"Invalid range: {start_line}-{end_line}"
    new_lines = new_content.split('\n')
    result = lines_list[:start_line - 1] + new_lines + lines_list[end_line:]
    p.write_text('\n'.join(result), encoding='utf-8')
    return f"Edited {file}: replaced lines {start_line}-{end_line} ({len(new_lines)} lines inserted)"


async def fs_append(file: str, content: str) -> str:
    """Append text to end of file."""
    p = _safe_path(file)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(content)
    return f"Appended to {file}"


TOOL_DEFINITIONS = [
    ("fs_tree", fs_tree, "Recursive directory listing with sizes and dates", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path (default: .)"},
            "depth": {"type": "integer", "description": "Depth level (default 2, max 5)"},
            "ascii_mode": {"type": "boolean", "description": "Use ASCII characters for tree"},
        },
    }),
    ("fs_read", fs_read, "Read file content with binary detection and size-aware truncation", {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "File path"},
            "lines": {"type": "integer", "description": "Number of lines (default 30, max 80)"},
            "start": {"type": "integer", "description": "Starting line (1-indexed)"},
        },
        "required": ["file"],
    }),
    ("fs_stat", fs_stat, "File/directory metadata", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Path"}},
        "required": ["path"],
    }),
    ("fs_grep", fs_grep, "Recursive case-insensitive text search", {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Search pattern"},
            "path": {"type": "string", "description": "Directory to search (default: .)"},
            "ext": {"type": "string", "description": "File extension filter (e.g. .py)"},
        },
        "required": ["pattern"],
    }),
    ("fs_find", fs_find, "Find files by case-insensitive glob pattern", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to search (default: .)"},
            "name": {"type": "string", "description": "Glob pattern (default: *)"},
        },
    }),
    ("fs_mkdir", fs_mkdir, "Create directory recursively", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path"}},
        "required": ["path"],
    }),
    ("fs_touch", fs_touch, "Create empty file or update mtime", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "File path"}},
        "required": ["path"],
    }),
    ("fs_rm", fs_rm, "Delete file or directory", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to remove"},
            "recursive": {"type": "boolean", "description": "Remove directories recursively"},
        },
        "required": ["path"],
    }),
    ("fs_mv", fs_mv, "Move/rename file or directory", {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source path"},
            "dst": {"type": "string", "description": "Destination path"},
        },
        "required": ["src", "dst"],
    }),
    ("fs_cp", fs_cp, "Copy file or directory", {
        "type": "object",
        "properties": {
            "src": {"type": "string", "description": "Source path"},
            "dst": {"type": "string", "description": "Destination path"},
            "recursive": {"type": "boolean", "description": "Copy directories recursively"},
        },
        "required": ["src", "dst"],
    }),
    ("fs_cd", fs_cd, "Change agent's virtual working directory", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path"}},
        "required": ["path"],
    }),
    ("fs_pwd", fs_pwd, "Print agent's virtual working directory", {
        "type": "object",
        "properties": {},
    }),
    ("fs_sizes", fs_sizes, "List largest files in directory", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to scan (default: .)"},
            "top": {"type": "integer", "description": "Number of entries (default 20)"},
        },
    }),
    ("fs_edit", fs_edit, "Replace lines in a text file (line numbers 1-indexed, inclusive)", {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "File path"},
            "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
            "end_line": {"type": "integer", "description": "End line (1-indexed, inclusive)"},
            "new_content": {"type": "string", "description": "New content to insert"},
        },
        "required": ["file", "start_line", "end_line", "new_content"],
    }),
    ("fs_append", fs_append, "Append text to end of file", {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Content to append"},
        },
        "required": ["file", "content"],
    }),
]


def register_all(registry):
    """Register all file system tools with the given registry."""
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} FS tools")
