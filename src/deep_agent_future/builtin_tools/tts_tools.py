"""Google Translate TTS + Telegram voice tools for MASTERMIND v2.

FREE text-to-speech via Google Translate's public TTS endpoint.
No API key required. Sends voice messages via Telegram sendVoice API.

Provides:
- tts_generate: generate MP3 audio file from text
- telegram_send_voice: generate TTS + send as Telegram voice message
"""

from __future__ import annotations

import asyncio
import hashlib
import urllib.parse
from pathlib import Path
from typing import Any

import httpx
from loguru import logger

DEFAULT_TTS_DIR = Path(__file__).resolve().parent.parent / "data" / "tts_cache"
MAX_TEXT_LENGTH = 200  # Google TTS query limit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _tts_google(text: str, lang: str = "ru", output_dir: str | None = None) -> dict[str, Any]:
    """Generate TTS audio via Google Translate and save as MP3.

    Args:
        text: Text to speak (max 200 chars)
        lang: Language code (ru, en, ja, etc.)
        output_dir: Directory to save audio (default: data/tts_cache)

    Returns:
        dict with ok, path, file_size, text, lang
    """
    text = text.strip()
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH]
        logger.warning(f"TTS text truncated to {MAX_TEXT_LENGTH} chars")

    dest_dir = Path(output_dir) if output_dir else DEFAULT_TTS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Derive filename from text hash
    text_hash = hashlib.md5(f"{lang}:{text}".encode()).hexdigest()[:12]
    out_path = dest_dir / f"tts_{lang}_{text_hash}.mp3"

    # Build Google Translate TTS URL
    encoded_text = urllib.parse.quote(text)
    tts_url = (
        f"https://translate.google.com/translate_tts"
        f"?ie=UTF-8&client=tw-ob&tl={lang}&q={encoded_text}"
    )

    try:
        async with httpx.AsyncClient(proxy="socks5://127.0.0.1:1080") as client:
            resp = await client.get(tts_url, timeout=30.0, follow_redirects=True)
            resp.raise_for_status()

            # Check if we got actual audio (not an error page)
            content_type = resp.headers.get("content-type", "")
            if "audio" not in content_type and len(resp.content) < 512:
                return {"ok": False, "error": f"Google TTS returned non-audio: {resp.content[:200]}"}

            await asyncio.to_thread(out_path.write_bytes, resp.content)

        file_size = out_path.stat().st_size
        logger.info(f"TTS generated: '{text[:50]}...' → {out_path.name} ({file_size} bytes)")
        return {
            "ok": True,
            "path": str(out_path),
            "file_size": file_size,
            "text": text,
            "lang": lang,
        }
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return {"ok": False, "error": str(e)}


async def _get_bot():
    """Get TelegramBot instance from registry or create."""
    from deep_agent_future.tool_registry import get_registry
    import os
    from deep_agent_future.telegram_bot import TelegramBot

    registry = get_registry()
    bot = registry.get_bot()
    if bot is not None:
        return bot

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        return None

    bot = TelegramBot(token=token)
    return bot


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


async def tts_generate(
    text: str,
    lang: str = "ru",
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Generate speech audio from text using Google Translate TTS (FREE, no API key).

    Args:
        text: Text to speak (max 200 chars, Russian by default)
        lang: Language code: ru (Russian), en (English), ja (Japanese), etc.
        output_dir: Optional output directory (default: data/tts_cache)

    Returns:
        dict: {\"ok\": True, \"path\": \"...\", \"file_size\": 1234} on success
    """
    return await _tts_google(text=text, lang=lang, output_dir=output_dir)


async def telegram_send_voice(
    text: str,
    chat_id: str,
    lang: str = "ru",
    caption: str = "",
) -> dict[str, Any]:
    """Generate TTS audio and send as voice message to Telegram chat.

    Combines Google Translate TTS + Telegram sendVoice in one call.

    Args:
        text: Text to speak and send (max 200 chars)
        chat_id: Telegram chat ID (numeric string)
        lang: Language code: ru, en, ja, etc. (default: ru)
        caption: Optional caption for the voice message

    Returns:
        dict: {\"ok\": True, \"result\": {...}} on success
    """
    # Step 1: Generate TTS audio
    tts_result = await _tts_google(text=text, lang=lang)
    if not tts_result["ok"]:
        return tts_result

    audio_path = tts_result["path"]

    # Step 2: Get bot instance
    bot = await _get_bot()
    if bot is None:
        return {"ok": False, "error": "Telegram bot not available. Set TELEGRAM_BOT_TOKEN."}

    # Step 3: Send as voice
    send_result = await bot.send_voice(
        chat_id=int(chat_id),
        voice_path=audio_path,
        caption=caption if caption else None,
    )

    if send_result.get("ok"):
        logger.info(f"Voice sent to chat {chat_id}: '{text[:50]}...'")

    return send_result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_all(registry) -> None:
    """Register TTS tools with the given ToolRegistry."""
    registry.register_function(
        func=tts_generate,
        name="tts_generate",
        description="Generate speech audio (MP3) from text using Google Translate TTS. FREE, no API key needed. Max 200 chars. Supports ru, en, ja, and 50+ languages.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to speak (max 200 chars, Russian by default)",
                },
                "lang": {
                    "type": "string",
                    "description": "Language code: ru, en, ja, etc. (default: ru)",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional output directory for audio file",
                },
            },
            "required": ["text"],
        },
    )

    registry.register_function(
        func=telegram_send_voice,
        name="telegram_send_voice",
        description="Generate TTS and send as voice message to Telegram chat. Combines Google TTS + sendVoice. Russian by default.",
        parameters={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to speak (max 200 chars)",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Telegram chat ID (numeric string, e.g., '-1003969262771')",
                },
                "lang": {
                    "type": "string",
                    "description": "Language code: ru, en, ja, etc. (default: ru)",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption for the voice message",
                },
            },
            "required": ["text", "chat_id"],
        },
    )

    logger.info("TTS tools registered: tts_generate, telegram_send_voice")
