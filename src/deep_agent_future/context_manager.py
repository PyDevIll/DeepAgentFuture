"""Context Manager v3 — Hybrid Observation Masking + LLM Summarization + Layered Memory.

Based on Lindenbauer et al. (NeurIPS 2025): observation masking as first line,
LLM summarization as last resort. Structured in 4 memory layers with token budget.

Layers (ordered by proximity to LLM):
  L0_SCRATCHPAD  — current turn, full detail
  L1_SLIDING     — last N messages, preserved verbatim
  L2_MASKED      — older tool outputs replaced with [MASKED: ...]
  L3_COMPRESSED  — LLM-summarized batches (last resort)
  LX_PERSISTENT  — key facts surviving across sessions
"""

from __future__ import annotations

import json
import re
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Optional

from loguru import logger

# ── Constants ──────────────────────────────────────────────────────────
DEFAULT_MAX_TOKENS = 100000          # soft cap; proactive trim at 80%
SLIDING_WINDOW_SIZE = 12            # last N messages kept verbatim
MASK_BATCH_SIZE = 8                 # mask tool outputs older than this many msgs
COMPRESSION_BATCH = 30              # trigger LLM summarization every N messages
PERSISTENT_FILE = "persistent_memory.json"
EMERGENCY_FILE = "emergency_save.json"

DATA_DIR = Path(__file__).resolve().parent / "data"

# ── Memory Layer enum ──────────────────────────────────────────────────
class Layer(IntEnum):
    SCRATCHPAD = 0
    SLIDING = 1
    MASKED = 2
    COMPRESSED = 3
    PERSISTENT = 4

# ── Data structures ────────────────────────────────────────────────────
@dataclass
class MemoryEntry:
    role: str
    content: str
    time: str = ""
    reasoning: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    tool_calls: list = field(default_factory=list)
    masked: bool = False
    layer: Layer = Layer.SLIDING

@dataclass
class TokenBudget:
    limit: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def usage_ratio(self) -> float:
        return self.used / self.limit if self.limit > 0 else 0

    def count(self, text: str) -> int:
        """Rough token estimate: ~chars/3.5 for multilingual text."""
        return max(1, len(text) // 3)

# ── Observation Masker ─────────────────────────────────────────────────
class ObservationMasker:
    """Replaces verbose tool outputs with compact [MASKED: tool → result] placeholders."""

    @staticmethod
    def mask(entry: MemoryEntry) -> MemoryEntry:
        if entry.role != "tool" or entry.masked:
            return entry

        content = entry.content or ""
        tool = entry.tool_name or "unknown"

        # Extract 1-line summary: first non-empty meaningful line
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        summary = ""
        if lines:
            first = lines[0]
            # Truncate to ~120 chars for the mask
            summary = first[:120] + ("…" if len(first) > 120 else "")

        masked_content = f"[MASKED: {tool} → {summary}]" if summary else f"[MASKED: {tool}]"

        masked_entry = MemoryEntry(
            role=entry.role,
            content=masked_content,
            time=entry.time,
            tool_name=tool,
            tool_call_id=entry.tool_call_id,
            masked=True,
            layer=Layer.MASKED,
        )
        return masked_entry

# ── Persistent Store ───────────────────────────────────────────────────
class PersistentStore:
    """Key facts surviving across sessions (user identity, critical knowledge)."""

    def __init__(self, data_dir: Path):
        self._path = data_dir / PERSISTENT_FILE
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding='utf-8'))
            except Exception as e:
                logger.warning(f"Persistent store load failed: {e}")
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding='utf-8')

    @property
    def facts(self) -> dict:
        return dict(self._data)

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def get(self, key: str, default: str = "") -> str:
        return self._data.get(key, default)

    def as_context_string(self) -> str:
        if not self._data:
            return ""
        lines = ["## Persistent Memory"]
        for k, v in self._data.items():
            lines.append(f"- **{k}**: {v}")
        return "\n".join(lines) + "\n"

# ── Context Assembler ──────────────────────────────────────────────────
class ContextAssembler:
    """Assembles memory layers into a single context string for the LLM.
    
    Order (DeepSeek cache-optimized):
      system → persistent → compressed → masked → sliding → current
    """

    def __init__(self, token_limit: int = DEFAULT_MAX_TOKENS):
        self.budget = TokenBudget(limit=token_limit)

    def assemble(
        self,
        system_prompt: str,
        persistent: str,
        compressed: list[MemoryEntry],
        masked: list[MemoryEntry],
        sliding: list[MemoryEntry],
    ) -> tuple[str, TokenBudget]:
        """Build final context string. Returns (text, budget)."""
        self.budget = TokenBudget(limit=self.budget.limit)
        parts: list[str] = []

        # 1. System prompt (static → DeepSeek prefix cache)
        parts.append(system_prompt)
        self.budget.used += self.budget.count(system_prompt)

        # 2. Persistent facts
        if persistent:
            parts.append(persistent)
            self.budget.used += self.budget.count(persistent)

        # 3. Compressed history (LLM summaries)
        for entry in compressed:
            text = self._entry_to_text(entry)
            if self.budget.remaining > self.budget.count(text):
                parts.append(text)
                self.budget.used += self.budget.count(text)
                self.budget.used += self.budget.count(entry.reasoning)

        # 4. Masked observations
        for entry in masked:
            text = self._entry_to_text(entry)
            if self.budget.remaining > self.budget.count(text):
                parts.append(text)
                self.budget.used += self.budget.count(text)

        # 5. Sliding window (verbatim, newest first in prompt order)
        for entry in sliding:
            text = self._entry_to_text(entry)
            if self.budget.remaining > self.budget.count(text):
                parts.append(text)
                self.budget.used += self.budget.count(text)
                self.budget.used += self.budget.count(entry.reasoning)
            else:
                logger.warning("Token budget exhausted — truncating sliding window")

        return "\n\n".join(parts), self.budget

    @staticmethod
    def _entry_to_text(entry: MemoryEntry) -> str:
        """Convert a MemoryEntry to prompt text."""
        time_str = f"[{entry.time}]" if entry.time else ""
        if entry.role == "system":
            return entry.content
        elif entry.role == "assistant":
            text = f"**ASSISTANT** {time_str}"
            if entry.reasoning:
                text += f"\n*reasoning:* {entry.reasoning}"
            if entry.content:
                text += f"\n{entry.content}"
            return text
        elif entry.role == "tool":
            return f"**TOOL [{entry.tool_name}]** {time_str}\n{entry.content}"
        else:
            return f"**{entry.role.upper()}** {time_str}\n{entry.content}"

# ── ContextPool v3 ─────────────────────────────────────────────────────
class ContextPool:
    """Hybrid context manager with observation masking, LLM summarization, and crash recovery."""

    def __init__(
        self,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        window_size: int = SLIDING_WINDOW_SIZE,
        data_dir: Optional[Path] = None,
    ):
        self.max_tokens = max_tokens
        self.window_size = window_size
        self._data_dir = data_dir or DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Memory layers
        self._all_entries: list[MemoryEntry] = []     # master log
        self._compressed: list[MemoryEntry] = []       # L3
        self._masked: list[MemoryEntry] = []           # L2 (managed automatically)

        # Infrastructure
        self._masker = ObservationMasker()
        self._persistent = PersistentStore(self._data_dir)
        self._assembler = ContextAssembler(token_limit=max_tokens)
        self._save_counter: int = 0
        self.overflow: bool = False

        # Attempt crash recovery
        self._restore_if_needed()

    # ── Properties ─────────────────────────────────────────────────
    @property
    def messages(self) -> list[dict]:
        """Return sliding window as OpenAI-format dicts for API compatibility."""
        return [self._entry_to_openai_dict(e) for e in self.sliding_window]

    @property
    def sliding_window(self) -> list[MemoryEntry]:
        """Last N entries in full detail."""
        return self._all_entries[-self.window_size:] if self._all_entries else []

    @property
    def masked_entries(self) -> list[MemoryEntry]:
        """Entries older than sliding window, with tool outputs masked."""
        if len(self._all_entries) <= self.window_size:
            return []
        older = self._all_entries[: -self.window_size]
        return [self._masker.mask(e) for e in older]

    @property
    def length(self) -> int:
        return len(self._all_entries)

    # ── Core API ───────────────────────────────────────────────────
    def get_context_length(self) -> int:
        """Estimate token count of entire context."""
        total = 0
        for entry in self._all_entries:
            total += len(entry.content or "") + len(entry.reasoning or "")
        return total // 3  # rough token estimate

    def append(self, message: dict, save: bool = False) -> None:
        """Append a raw message dict."""
        entry = self._dict_to_entry(message)
        self._all_entries.append(entry)
        self._save_counter += 1

        if save:
            self._save_to_file(entry)

        self._check_overflow()
        self._auto_mask()
        self._periodic_save()

    def append_assistant_message(
        self, message: dict, save: bool = False, has_tool_calls: bool = False
    ) -> None:
        """Append assistant message with tool-call aware processing."""
        entry = MemoryEntry(
            role="assistant",
            content=message.get("content") if not has_tool_calls else None,
            reasoning=message.get("reasoning_content", ""),
            time=datetime.now().strftime("%d.%m.%Y, %H:%M"),
            tool_calls=message.get("tool_calls", []) if has_tool_calls else [],
        )
        self._all_entries.append(entry)
        self._save_counter += 1

        if save:
            self._save_to_file(entry)

        self._check_overflow()
        self._auto_mask()
        self._periodic_save()

    def assign_messages(self, messages: list[dict]) -> None:
        """Bulk load messages (e.g., from last memory)."""
        self._all_entries = [self._dict_to_entry(m) for m in messages]
        self._clean_orphaned_tools()

    def get_chat_history(self, messages: Optional[list[dict]] = None) -> str:
        """Render chat history as markdown string (for compression)."""
        entries = [self._dict_to_entry(m) for m in messages] if messages else self._all_entries
        lines = []
        for entry in entries:
            lines.append(f"\n**{entry.role}:** [{entry.time or '--:--'}]")
            if entry.reasoning:
                lines.append(f"*reasoning:* {entry.reasoning}")
            if entry.content:
                lines.append(entry.content)
            lines.append("---")
        return "\n".join(lines)

    def build_context(self, system_prompt: str = "") -> tuple[str, TokenBudget]:
        """Assemble full context from all layers. Returns (text, budget)."""
        persistent = self._persistent.as_context_string()
        return self._assembler.assemble(
            system_prompt=system_prompt,
            persistent=persistent,
            compressed=self._compressed,
            masked=self.masked_entries,
            sliding=self.sliding_window,
        )

    # ── Compression ────────────────────────────────────────────────
    async def compress(self, helper_agent) -> Optional[str]:
        """LLM summarization — last resort for large batches."""
        # Token-based trigger: compress at 80% budget OR 20+ entries
        self.log_state("BEFORE compression")

        est_tokens = self.get_context_length()
        overflow_ratio = est_tokens / self.max_tokens if self.max_tokens > 0 else 0
        enough_entries = len(self._all_entries) >= 20
        token_overflow = overflow_ratio >= 0.80

        if not helper_agent:
            return None
        if not enough_entries and not token_overflow:
            return None
        if len(self._all_entries) < 3:
            return None

        logger.info(
            f"Context compression triggered: {len(self._all_entries)} entries, "
            f"{est_tokens} tokens ({overflow_ratio:.0%})"
        )

        # Take the oldest batch beyond sliding window
        batch = self._all_entries[: -self.window_size]
        if not batch:
            return None

        chat_text = self.get_chat_history(
            [self._entry_to_dict(e) for e in batch]
        )

        helper_message = {
            "role": "user",
            "name": "MASTERMIND",
            "content": (
                "**ACTION**: COMPRESS\n\n"
                "Retain: key decisions, file changes, tool results, user intent, errors.\n"
                "Discard: redundant reasoning, repeated tool calls, noise.\n\n"
                "**CONTENT**:\n" + chat_text
            ),
        }

        # Use helper agent for compression (async)
        try:
            helper_agent.messages.assign_messages([helper_message])
            response = await helper_agent.llm_request()
        except Exception as e:
            logger.error(f"Compression helper LLM call failed: {e}")
            return None

        # Extract compressed text
        if isinstance(response, dict):
            compressed_text = response["choices"][0]["message"]["content"]
        else:
            compressed_text = response.choices[0].message.content

        # Store compression
        comp_entry = MemoryEntry(
            role="assistant",
            content=f"[COMPRESSED HISTORY — {len(batch)} turns]\n{compressed_text}",
            time=datetime.now().strftime("%d.%m.%Y, %H:%M"),
            layer=Layer.COMPRESSED,
        )
        logger.info(f"Compressed entry added: role={comp_entry.role}, content length={len(comp_entry.content)}")
        self._compressed.append(comp_entry)

        # Trim old entries: keep only last window_size + append compressed
        kept = self._all_entries[-self.window_size:]
        self._all_entries = kept
        self._clean_orphaned_tools()

        # Save to disk
        comp_file = self._data_dir / "compressed_history.txt"
        with open(comp_file, 'a', encoding='utf-8') as f:
            f.write(f"# Compressed {len(batch)} turns:\n{compressed_text}\n\n")

        last_file = self._data_dir / "last_compression.txt"
        with open(last_file, 'w', encoding='utf-8') as f:
            f.write(compressed_text + "\n\n")

        self.overflow = False
        self._check_overflow()
        logger.info(
            f"Compression complete: {len(batch)} turns → summary, "
            f"context now ~{self.get_context_length()} tokens"
        )

        self.log_state("AFTER compression")
        return compressed_text

    # ── Crash Recovery ─────────────────────────────────────────────
    def _restore_if_needed(self) -> bool:
        """Called on init. Restores from emergency save if it exists."""
        save_file = self._data_dir / EMERGENCY_FILE
        if not save_file.exists():
            return False
        try:
            raw = json.loads(save_file.read_text(encoding='utf-8'))
            self._all_entries = [self._dict_to_entry(m) for m in raw]
            self._clean_orphaned_tools()
            self._check_overflow()
            if self.overflow:
                logger.warning(
                    f"🔄 Restored {len(self._all_entries)} entries — overflow "
                    f"({self.get_context_length()} tokens), compression advised"
                )
            else:
                logger.info(f"🔄 Restored {len(self._all_entries)} messages from emergency save")
            return True
        except Exception as e:
            logger.error(f"Emergency restore failed: {e}")
            return False

    def _emergency_save(self) -> None:
        """Save full state as JSON."""
        save_file = self._data_dir / EMERGENCY_FILE
        try:
            raw = [self._entry_to_dict(e) for e in self._all_entries]
            save_file.write_text(json.dumps(raw, ensure_ascii=False, default=str), encoding='utf-8')
            logger.debug(f"Emergency save: {len(raw)} entries")
        except Exception as e:
            logger.error(f"Emergency save failed: {e}")

    def restore_from_emergency(self) -> bool:
        """Public API: manual restore."""
        return self._restore_if_needed()

    # ── Persistent facts ───────────────────────────────────────────
    def remember(self, key: str, value: str) -> None:
        """Store a persistent fact."""
        self._persistent.set(key, value)

    def recall(self, key: str) -> str:
        """Retrieve a persistent fact."""
        return self._persistent.get(key)

    # ── Internals ──────────────────────────────────────────────────
    def _dict_to_entry(self, msg: dict) -> MemoryEntry:
        """Convert raw dict to MemoryEntry. Preserves tool_calls for round-trip."""
        return MemoryEntry(
            role=msg.get("role", "unknown"),
            content=msg.get("content", "") or "",
            reasoning=msg.get("reasoning_content", ""),
            time=msg.get("time", datetime.now().strftime("%d.%m.%Y, %H:%M")),
            tool_name=msg.get("name", ""),
            tool_call_id=msg.get("tool_call_id", ""),
            tool_calls=msg.get("tool_calls", []),
        )

    def _entry_to_dict(self, entry: MemoryEntry) -> dict:
        """Serialize MemoryEntry to dict. Preserves tool_calls for crash recovery."""
        d = {
            "role": entry.role,
            "content": entry.content,
            "time": entry.time,
        }
        if entry.reasoning:
            d["reasoning_content"] = entry.reasoning
        if entry.tool_name:
            d["name"] = entry.tool_name
        if entry.tool_call_id:
            d["tool_call_id"] = entry.tool_call_id
        if entry.tool_calls:
            d["tool_calls"] = entry.tool_calls
        return d

    def _entry_to_openai_dict(self, entry: MemoryEntry) -> dict:
        """Convert to OpenAI-compatible message dict.

        Critical: OpenAI/DeepSeek API requires assistant messages to have
        non-empty `content` OR non-empty `tool_calls`. Empty string ""
        is treated as missing. This method ensures validity.
        """
        d = {"role": entry.role}

        raw_content = entry.content
        has_tool_calls = bool(entry.tool_calls)

        if raw_content is not None and raw_content != "":
            d["content"] = raw_content
        elif has_tool_calls:
            # content can be empty/null when tool_calls present
            d["content"] = ""
        elif entry.reasoning:
            # Fallback: first line of reasoning as content
            first_line = entry.reasoning.split('\n')[0][:200]
            d["content"] = f"[Thought: {first_line}]"
        else:
            d["content"] = "[No content]"

        if entry.reasoning:
            d["reasoning_content"] = entry.reasoning
        if entry.tool_calls:
            d["tool_calls"] = entry.tool_calls
        if entry.tool_name:
            d["name"] = entry.tool_name
        if entry.tool_call_id:
            d["tool_call_id"] = entry.tool_call_id
        return d

    def _check_overflow(self) -> None:
        """Check token budget and set overflow flag."""
        est_tokens = self.get_context_length()
        if est_tokens > self.max_tokens * 0.8:
            self.overflow = True
            logger.warning(f"Context at {est_tokens} tokens ({est_tokens/self.max_tokens:.0%}) — overflow")
        else:
            self.overflow = False

    def _auto_mask(self) -> None:
        """Automatically mask tool outputs beyond sliding window."""
        if len(self._all_entries) <= self.window_size + MASK_BATCH_SIZE:
            return
        # Masking happens lazily via masked_entries property; nothing to do eagerly
        pass

    def _periodic_save(self) -> None:
        """Emergency save every 5 messages."""
        if self._save_counter % 5 == 0:
            self._emergency_save()

    def _save_to_file(self, entry: MemoryEntry) -> None:
        """Append to human-readable history file."""
        history_file = self._data_dir / "message_history.md"
        try:
            with open(history_file, 'a', encoding='utf-8') as f:
                f.write(f"**{entry.role}:** [{entry.time}]\n")
                if entry.reasoning:
                    f.write(f"*Reasoning:* {entry.reasoning}\n\n")
                f.write(f"{entry.content or ''}\n---\n\n")
        except Exception as e:
            logger.error(f"History save failed: {e}")


    def log_state(self, tag: str = "") -> None:
        logger.info(f"=== Context state {tag} ===")
        logger.info(f"  Total entries: {len(self._all_entries)}")
        logger.info(f"  Sliding window (last {self.window_size}): {len(self.sliding_window)} entries")
        if self.sliding_window:
            first = self.sliding_window[0]
            last = self.sliding_window[-1]
            # Safe preview: handle None content
            first_preview = (first.content[:50] if first.content else "[No content]")
            last_preview = (last.content[:50] if last.content else "[No content]")
            logger.info(f"    first: {first.role} '{first_preview}'")
            logger.info(f"    last:  {last.role} '{last_preview}'")
        logger.info(f"  Compressed entries: {len(self._compressed)}")
        logger.info(f"  Masked entries (old): {len(self.masked_entries)}")
        logger.info(f"  Persistent facts: {len(self._persistent.facts)}")
        logger.info(f"  Estimated tokens: {self.get_context_length()}")
        logger.info(f"  Overflow flag: {self.overflow}")
        logger.info("=====================================")


    def _clean_orphaned_tools(self) -> None:
        """Remove tool messages that have no matching assistant with tool_calls."""
        # Collect all valid tool_call_ids from assistant messages
        valid_ids = set()
        for entry in self._all_entries:
            if entry.role == "assistant" and entry.tool_calls:
                for tc in entry.tool_calls:
                    valid_ids.add(tc["id"])
        # Keep only tool messages whose id is in valid_ids
        self._all_entries = [
            e for e in self._all_entries
            if not (e.role == "tool" and e.tool_call_id not in valid_ids)
        ]
