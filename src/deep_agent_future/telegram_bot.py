"""Async Telegram bot with reasoning-to-separate-chat for MASTERMIND v2."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Callable, Awaitable

import httpx
from loguru import logger

MIN_POLL_PERIOD = timedelta(seconds=3)
LONG_POLL_TIMEOUT = 60


# # --- Module-level singleton for tool access ---
# _bot_instance: Optional['TelegramBot'] = None
#
#
# def get_bot() -> Optional['TelegramBot']:
#     """Get the current TelegramBot instance (for tool access)."""
#     return _bot_instance
#
#
# def set_bot(bot: 'TelegramBot') -> None:
#     """Set the global TelegramBot instance."""
#     global _bot_instance
#     _bot_instance = bot
#

def _escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    result = []
    for char in text:
        if char in special_chars:
            result.append('\\' + char)
        else:
            result.append(char)
    return ''.join(result)


class TelegramBot:
    """Async Telegram bot with long polling and separate reasoning chat."""

    def __init__(
        self,
        token: Optional[str] = None,
        reasoning_chat_id: Optional[int] = None,
    ):
        self._token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._reasoning_chat_id = reasoning_chat_id or int(
            os.environ.get("REASONING_CHAT_ID", "0")
        )
        self._base_url = f"https://api.telegram.org/bot{self._token}"
        self._offset: int = 0
        self._running: bool = False
        self._message_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._file_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._file_handler: Optional[Callable[[dict], Awaitable[None]]] = None

        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN not set!")
        if not self._reasoning_chat_id:
            logger.warning("REASONING_CHAT_ID not set!")

    async def _api_call(self, method: str, params: dict) -> dict:
        """Make an async Telegram API call."""
        url = f"{self._base_url}/{method}"
        try:
            async with httpx.AsyncClient(proxy="socks5://127.0.0.1:1080") as client:
                resp = await client.post(url, json=params, timeout=30.0)
                return resp.json()
        except Exception as e:
            logger.error(f"Telegram API error ({method}): {e}")
            return {"ok": False, "error": str(e)}

    async def send_message(self, chat_id: int, text: str) -> Optional[dict]:
        """Send a message to a chat."""
        if not text:
            return None
        # Truncate if too long (Telegram limit: 4096)
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (truncated)"
        result = await self._api_call("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
        })
        if not result.get("ok"):
            # Retry without markdown
            result = await self._api_call("sendMessage", {
                "chat_id": chat_id,
                "text": text,
            })
        return result

    async def send_reasoning(self, text: str) -> None:
        """Send reasoning thought to the dedicated reasoning chat."""
        if not self._reasoning_chat_id or not text:
            return
        await self.send_message(self._reasoning_chat_id, f"🧠 *Reasoning:*\n{text[:3800]}")

    async def send_reply(self, chat_id: int, text: str) -> None:
        """Reply to a user in their chat."""
        await self.send_message(chat_id, text)

    # --- File transfer methods ---

    async def send_document(
        self,
        chat_id: int,
        file_path: str,
        caption: Optional[str] = None,
    ) -> dict:
        """
        Send a document from local filesystem to a Telegram chat.

        Args:
            chat_id: Telegram chat ID
            file_path: Absolute path to file on filesystem
            caption: Optional caption text

        Returns:
            API response dict with file_id etc.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            return {"ok": False, "error": f"File not found: {file_path}"}
        if not path.is_file():
            return {"ok": False, "error": f"Not a regular file: {file_path}"}

        file_size = path.stat().st_size
        max_size = 50 * 1024 * 1024  # 50 MB Telegram limit

        if file_size > max_size:
            return {
                "ok": False,
                "error": f"File too large: {file_size} bytes (max {max_size})",
            }

        url = f"{self._base_url}/sendDocument"

        # Read file in thread to avoid blocking
        file_bytes = await asyncio.to_thread(path.read_bytes)

        try:
            async with httpx.AsyncClient(proxy="socks5://127.0.0.1:1080") as client:
                data = {"chat_id": str(chat_id)}
                if caption:
                    data["caption"] = caption

                resp = await client.post(
                    url,
                    data=data,
                    files={"document": (path.name, file_bytes)},
                    timeout=120.0,
                )
                result = resp.json()
                if result.get("ok"):
                    logger.info(f"Sent document '{path.name}' to chat {chat_id}")
                else:
                    logger.error(f"sendDocument failed: {result}")
                return result
        except Exception as e:
            logger.error(f"sendDocument error: {e}")
            return {"ok": False, "error": str(e)}

    async def send_voice(
        self,
        chat_id: int,
        voice_path: str,
        caption: Optional[str] = None,
        duration: Optional[int] = None,
    ) -> dict:
        """
        Send a voice message (OPUS/OGG/MP3) to a Telegram chat.

        Args:
            chat_id: Telegram chat ID
            voice_path: Absolute path to audio file
            caption: Optional caption text
            duration: Audio duration in seconds (optional)

        Returns:
            API response dict
        """
        path = Path(voice_path).resolve()
        if not path.exists():
            return {"ok": False, "error": f"File not found: {voice_path}"}
        if not path.is_file():
            return {"ok": False, "error": f"Not a regular file: {voice_path}"}

        file_size = path.stat().st_size
        max_size = 50 * 1024 * 1024  # 50 MB

        if file_size > max_size:
            return {"ok": False, "error": f"File too large: {file_size} bytes (max {max_size})"}

        url = f"{self._base_url}/sendVoice"
        voice_bytes = await asyncio.to_thread(path.read_bytes)

        try:
            async with httpx.AsyncClient(proxy="socks5://127.0.0.1:1080") as client:
                data = {"chat_id": str(chat_id)}
                if caption:
                    data["caption"] = caption
                if duration is not None:
                    data["duration"] = str(duration)

                resp = await client.post(
                    url,
                    data=data,
                    files={"voice": (path.name, voice_bytes)},
                    timeout=120.0,
                )
                result = resp.json()
                if result.get("ok"):
                    logger.info(f"Sent voice '{path.name}' to chat {chat_id}")
                else:
                    logger.error(f"sendVoice failed: {result}")
                return result
        except Exception as e:
            logger.error(f"sendVoice error: {e}")
            return {"ok": False, "error": str(e)}

    async def _get_file_info(self, file_id: str) -> Optional[dict]:
        """Get file info from Telegram by file_id."""
        result = await self._api_call("getFile", {"file_id": file_id})
        if result.get("ok"):
            return result["result"]
        logger.error(f"getFile failed for {file_id}: {result}")
        return None

    async def download_file(
        self,
        file_id: str,
        destination: str,
    ) -> dict:
        """
        Download a file from Telegram and save to filesystem.

        Args:
            file_id: Telegram file ID
            destination: Absolute path or directory to save file.
                         If directory, original filename is appended.

        Returns:
            dict with ok, path, file_size, file_name
        """
        # Resolve file info
        file_info = await self._get_file_info(file_id)
        if not file_info:
            return {"ok": False, "error": f"Could not get file info for {file_id}"}

        file_path = file_info.get("file_path")
        if not file_path:
            return {"ok": False, "error": "No file_path in response"}

        file_size = file_info.get("file_size", 0)
        orig_name = Path(file_path).name

        # Determine destination path
        dest = Path(destination).resolve()
        if dest.is_dir():
            dest = dest / orig_name
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Download from Telegram file server
        download_url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"

        try:
            async with httpx.AsyncClient(proxy="socks5://127.0.0.1:1080") as client:
                resp = await client.get(download_url, timeout=300.0)
                resp.raise_for_status()
                # Write to disk in thread to avoid blocking
                await asyncio.to_thread(dest.write_bytes, resp.content)

            logger.info(f"Downloaded '{orig_name}' ({file_size} bytes) → {dest}")
            return {
                "ok": True,
                "path": str(dest),
                "file_size": file_size,
                "file_name": orig_name,
            }
        except Exception as e:
            logger.error(f"Download error: {e}")
            return {"ok": False, "error": str(e)}

    async def _poll_updates(self):
        """Fetch new updates via long polling."""
        params = {
            "offset": self._offset,
            "timeout": LONG_POLL_TIMEOUT,
            "allowed_updates": ["message", "callback_query", "inline_query", "chosen_inline_result"],
            # Note: Telegram API accepts list; documents come as message type
        }
        result = await self._api_call("getUpdates", params)
        if result.get("ok"):
            return result.get("result", [])
        return []

    async def start_polling(
        self,
        message_handler: Callable[[dict], Awaitable[None]],
    ) -> None:
        """
        Start the polling loop.
        message_handler: async function receiving message dict.
        """
        self._running = True
        logger.info("Telegram polling started")

        while self._running:
            try:
                updates = await self._poll_updates()
                for update in updates:
                    self._offset = update["update_id"] + 1
                    if "message" in update:
                        msg = update["message"]
                        # Handle text/caption — may coexist with media
                        has_text = bool(msg.get("text") or msg.get("caption"))
                        has_media = bool(
                            msg.get("document")
                            or msg.get("photo")
                            or msg.get("voice")
                        )

                        if has_text:
                            # Inject synthesised "text" so downstream sees unified key
                            if "caption" in msg and "text" not in msg:
                                msg["text"] = msg["caption"]
                            await self._message_queue.put(msg)

                        if has_media:
                            await self._file_queue.put(msg)

                # Process text message queue
                while not self._message_queue.empty():
                    msg = await self._message_queue.get()
                    await message_handler(msg)

                # Process file queue
                while not self._file_queue.empty():
                    msg = await self._file_queue.get()
                    if self._file_handler:
                        await self._file_handler(msg)
                    else:
                        logger.warning(
                            f"Received file but no file_handler set: "
                            f"{msg.get('document', msg.get('photo', {}))}"
                        )

            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)

        logger.info("Telegram polling stopped")

    def set_file_handler(
        self,
        handler: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Set handler for incoming file messages (documents/photos)."""
        self._file_handler = handler

    def stop(self) -> None:
        self._running = False

    def get_message(self) -> Optional[dict]:
        """Get next message from queue (non-blocking, for sync compatibility)."""
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
