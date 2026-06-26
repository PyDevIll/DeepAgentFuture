"""Context pool with compression, crash recovery, and DeepSeek cache awareness."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

DEFAULT_MAX_LENGTH = 50000
DATA_DIR = Path(__file__).resolve().parent / "data"


class ContextPool:
    """Manages chat message history with overflow detection and persistence."""

    def __init__(
        self,
        max_length: int = DEFAULT_MAX_LENGTH,
        data_dir: Optional[Path] = None,
    ):
        self._max_length = max_length
        self._messages: list[dict] = []
        self._compressed_history: list[dict] = []
        self.overflow: bool = False
        self._data_dir = data_dir or DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._save_counter: int = 0

    @property
    def messages(self) -> list[dict]:
        return self._messages

    @property
    def length(self) -> int:
        return len(self._messages)

    def get_context_length(self) -> int:
        total = 0
        for msg in self._messages:
            content = msg.get("content", "") or ""
            reasoning = msg.get("reasoning_content", "") or ""
            total += len(content) + len(reasoning)
        return total

    def append(self, message: dict, save: bool = False) -> None:
        message["time"] = datetime.now().strftime("%d.%m.%Y, %H:%M")
        self._messages.append(message)
        self._save_counter += 1

        if save:
            self._save_to_file(message)

        if self.get_context_length() > self._max_length:
            logger.warning("Context max length overflow — compression needed")
            self.overflow = True
        else:
            self.overflow = False

        if self._save_counter % 5 == 0:
            self._emergency_save()

    def append_assistant_message(
        self, message: dict, save: bool = False, has_tool_calls: bool = False
    ) -> None:
        msg_copy = message.copy()
        msg_copy["time"] = datetime.now().strftime("%d.%m.%Y, %H:%M")

        if has_tool_calls:
            msg_copy["content"] = None
        else:
            msg_copy.pop("reasoning_content", None)
            if msg_copy.get("content") is None:
                msg_copy["content"] = ""

        self._messages.append(msg_copy)
        self._save_counter += 1

        if save:
            self._save_to_file(msg_copy)

        if self.get_context_length() > self._max_length:
            self.overflow = True

    def assign_messages(self, messages: list[dict]) -> None:
        self._messages = messages[:]

    def get_chat_history(self, messages: Optional[list[dict]] = None) -> str:
        msgs = messages if messages is not None else self._messages
        chat = ""
        for msg in msgs:
            role = msg.get("role", "unknown")
            time = msg.get("time", "--.--.-- --:--:--")
            chat += f"\n**{role}:** [{time}]\n"
            if msg.get("reasoning_content"):
                chat += f"*reasoning:* {msg.get('reasoning_content')}\n\n"
            chat += f"{msg.get('content', '')}\n---\n"
        return chat

    def _save_to_file(self, message: dict) -> None:
        history_file = self._data_dir / "message_history.md"
        try:
            with open(history_file, 'a', encoding='utf-8') as f:
                f.write(f"**{message['role']}:** [{message.get('time', '')}]\n")
                if message.get('reasoning_content'):
                    f.write(f"*Reasoning:* {message['reasoning_content']}\n\n")
                f.write(f"{message.get('content', '')}\n---\n\n")
        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def _emergency_save(self) -> None:
        save_file = self._data_dir / "emergency_save.json"
        try:
            with open(save_file, 'w', encoding='utf-8') as f:
                json.dump(self._messages, f, ensure_ascii=False, default=str)
            logger.debug(f"Emergency save: {len(self._messages)} messages")
        except Exception as e:
            logger.error(f"Emergency save failed: {e}")

    def restore_from_emergency(self) -> bool:
        save_file = self._data_dir / "emergency_save.json"
        if not save_file.exists():
            return False
        try:
            with open(save_file, 'r', encoding='utf-8') as f:
                self._messages = json.load(f)
            logger.info(f"Restored {len(self._messages)} messages from emergency save")
            return True
        except Exception as e:
            logger.error(f"Failed to restore from emergency: {e}")
            return False

    def compress(self, helper_agent) -> Optional[str]:
        """Compress context using a helper agent. Returns compressed text or None."""
        if not helper_agent:
            return None

        logger.info("Context compression started...")
        helper_message = {
            "role": "user",
            "name": "MASTERMIND",
            "content": "**ACTION**: COMPRESS\n\n**CONTENT**:\n" + self.get_chat_history(),
        }
        helper_agent.messages.assign_messages([helper_message])
        response = helper_agent.llm_request()
        compressed = response.choices[0].message.content

        # Save compression
        comp_file = self._data_dir / "compressed_history.txt"
        with open(comp_file, 'a', encoding='utf-8') as f:
            f.write("# Compressed:\n" + compressed + "\n\n")

        last_file = self._data_dir / "last_compression.txt"
        with open(last_file, 'w', encoding='utf-8') as f:
            f.write(compressed + "\n\n")

        self._compressed_history.append({
            "role": "assistant",
            "content": compressed,
            "time": datetime.now().strftime("%d.%m.%Y, %H:%M"),
        })
        self.overflow = False
        logger.info("Context compression complete")
        return compressed
