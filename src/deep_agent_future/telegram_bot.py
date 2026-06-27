"""Async Telegram bot with reasoning-to-separate-chat for MASTERMIND v2."""

from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable

import httpx
from loguru import logger

MIN_POLL_PERIOD = timedelta(seconds=3)
LONG_POLL_TIMEOUT = 60


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

    async def _poll_updates(self) -> list[dict]:
        """Fetch new updates via long polling."""
        params = {
            "offset": self._offset,
            "timeout": LONG_POLL_TIMEOUT,
            "allowed_updates": ["message"],
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
                        # Only handle text messages
                        if "text" in msg:
                            await self._message_queue.put(msg)

                # Process queue
                while not self._message_queue.empty():
                    msg = await self._message_queue.get()
                    await message_handler(msg)

            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(5)

        logger.info("Telegram polling stopped")

    def stop(self) -> None:
        self._running = False

    def get_message(self) -> Optional[dict]:
        """Get next message from queue (non-blocking, for sync compatibility)."""
        try:
            return self._message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
