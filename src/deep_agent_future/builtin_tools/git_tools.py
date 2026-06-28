"""Git operations tools for MASTERMIND v2 — async subprocess-based."""

import asyncio
import os
from pathlib import Path
from typing import Optional

from loguru import logger


async def _run_git(path: str, *args: str, timeout: int = 30) -> str:
    """Run a git command asynchronously and return stdout+stderr."""
    p = Path(path).resolve()
    if not p.exists():
        p.mkdir(parents=True, exist_ok=True)
    try:
        proc = await asyncio.create_subprocess_exec(
            'git', *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(p),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        result = stdout.decode('utf-8', errors='replace')
        if proc.returncode != 0:
            err = stderr.decode('utf-8', errors='replace')
            result += f"\n[stderr]: {err}"
        return result.strip() or "(no output)"
    except asyncio.TimeoutError:
        return f"Git command timed out ({timeout}s)"


async def git_init(path: str = ".") -> str:
    """Initialize a git repository at the given path."""
    return await _run_git(path, "init")


async def git_status(path: str = ".") -> str:
    """Show working tree status."""
    return await _run_git(path, "status", "--short")


async def git_add(path: str = ".", files: str = ".") -> str:
    """Add file contents to the index."""
    return await _run_git(path, "add", files)


async def git_commit(path: str = ".", message: str = "") -> str:
    """Record changes to the repository."""
    return await _run_git(path, "commit", "-m", message)


async def git_log(path: str = ".", count: int = 10) -> str:
    """Show last N commit logs (oneline format)."""
    return await _run_git(path, "log", f"-{count}", "--oneline")


async def git_diff(path: str = ".", staged: bool = False) -> str:
    """Show changes (unified diff format). Use staged=True for --cached."""
    args = ["diff", "--cached" if staged else None]
    args = [a for a in args if a]  # filter None
    return await _run_git(path, *args)


async def git_branch(path: str = ".") -> str:
    """List branches."""
    return await _run_git(path, "branch")


async def git_checkout(path: str = ".", branch: str = "main") -> str:
    """Switch branches."""
    return await _run_git(path, "checkout", branch)


async def git_push(path: str = ".", remote: str = "origin", branch: str = "", force: bool = False) -> str:
    """Push commits to remote repository."""
    args = ["push", remote]
    if force:
        args.append("--force")
    if branch:
        args.append(branch)
    return await _run_git(path, *args)


TOOL_DEFINITIONS = [
    ("git_init", git_init, "Initialize a git repository at the given path", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path (default: .)"},
        },
    }),
    ("git_status", git_status, "Show working tree status", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
        },
    }),
    ("git_add", git_add, "Add file contents to the index", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
            "files": {"type": "string", "description": "Files to add (default: .)"},
        },
    }),
    ("git_commit", git_commit, "Record changes to the repository", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
            "message": {"type": "string", "description": "Commit message"},
        },
        "required": ["message"],
    }),
    ("git_log", git_log, "Show last N commit logs (oneline format)", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
            "count": {"type": "integer", "description": "Number of commits (default: 10)"},
        },
    }),
    ("git_diff", git_diff, "Show changes (unified diff format). Use staged=True for --cached", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
            "staged": {"type": "boolean", "description": "Show staged changes (--cached) (default: false)"},
        },
    }),
    ("git_branch", git_branch, "List branches", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
        },
    }),
    ("git_checkout", git_checkout, "Switch branches", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
            "branch": {"type": "string", "description": "Branch name (default: main)"},
        },
        "required": ["branch"],
    }),
    ("git_push", git_push, "Push commits to remote repository", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Repository path (default: .)"},
            "remote": {"type": "string", "description": "Remote name (default: origin)"},
            "branch": {"type": "string", "description": "Branch name (default: current)"},
            "force": {"type": "boolean", "description": "Force push (default: false)"},
        },
    }),
]


def register_all(registry):
    """Register all git tools with the given registry."""
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} git tools")
