"""Telegram file transfer tools for MASTERMIND v2.

Provides agent-accessible tools for:
- Sending files from the filesystem to Telegram chats
- Downloading files from Telegram chats to the filesystem
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger


async def telegram_send_file(
    absolute_path: str,
    chat_id: str,
    caption: str = "",
) -> dict[str, Any]:
    """Send a file from the local filesystem to a Telegram chat.

    Args:
        absolute_path: Absolute path to the file on the filesystem.
        chat_id: Telegram chat ID (numeric string) to send to.
        caption: Optional caption for the document.

    Returns:
        dict: {"ok": True, "result": {...}} on success,
              {"ok": False, "error": "..."} on failure.
    """
    if not absolute_path:
        return {"ok": False, "error": "absolute_path is required"}

    path = Path(absolute_path).resolve()
    if not path.exists():
        return {"ok": False, "error": f"File not found: {absolute_path}"}
    if not path.is_file():
        return {"ok": False, "error": f"Not a regular file: {absolute_path}"}

    from deep_agent_future.telegram_bot import get_bot

    bot = get_bot()
    if bot is None:
        return {"ok": False, "error": "Telegram bot not initialized"}

    logger.info(f"Telegram tool: sending file {path} to chat_id={chat_id}")
    result = await bot.send_document(chat_id, str(path), caption=caption)
    return result


async def telegram_download_file(
    file_id: str,
    destination_dir: str,
) -> dict[str, Any]:
    """Download a file from a Telegram chat by file_id to a local directory.

    Args:
        file_id: Telegram file ID to download.
        destination_dir: Directory to save the downloaded file.

    Returns:
        dict: {"ok": True, "path": "..."} on success,
              {"ok": False, "error": "..."} on failure.
    """
    if not file_id:
        return {"ok": False, "error": "file_id is required"}
    if not destination_dir:
        return {"ok": False, "error": "destination_dir is required"}

    dest = Path(destination_dir).resolve()
    if not dest.exists():
        return {"ok": False, "error": f"Destination directory not found: {destination_dir}"}
    if not dest.is_dir():
        return {"ok": False, "error": f"Destination is not a directory: {destination_dir}"}

    from deep_agent_future.telegram_bot import get_bot

    bot = get_bot()
    if bot is None:
        return {"ok": False, "error": "Telegram bot not initialized"}

    logger.info(f"Telegram tool: downloading file_id={file_id} to {dest}")
    result = await bot.download_file(file_id, str(dest))
    return result


# Tool definitions — must be AFTER function definitions
TOOL_DEFINITIONS: list[tuple] = [
    ("telegram_send_file", telegram_send_file,
     "Send a file from the local filesystem to a Telegram chat by absolute path",
     {
         "type": "object",
         "properties": {
             "absolute_path": {"type": "string", "description": "Absolute path to the file"},
             "chat_id": {"type": "string", "description": "Telegram chat ID (numeric string)"},
             "caption": {"type": "string", "description": "Optional caption for the file"},
         },
         "required": ["absolute_path", "chat_id"],
     }),
    ("telegram_download_file", telegram_download_file,
     "Download a file from a Telegram chat by file_id to a local directory",
     {
         "type": "object",
         "properties": {
             "file_id": {"type": "string", "description": "Telegram file ID to download"},
             "destination_dir": {"type": "string", "description": "Directory to save the downloaded file"},
         },
         "required": ["file_id", "destination_dir"],
     }),
]


def register_all(registry) -> None:
    """Register all Telegram tools with the given registry."""
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} Telegram tools")
