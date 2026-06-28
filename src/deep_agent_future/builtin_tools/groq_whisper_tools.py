"""Groq Whisper voice recognition tools for MASTERMIND v2.

100% FREE voice-to-text via Groq's complimentary Whisper API.
API key from https://console.groq.com/ → GROQ_API_KEY env var.

Provides:
- groq_transcribe: transcribe audio file via whisper-large-v3
- groq_transcribe_telegram: download Telegram voice message then transcribe

Supports automatic ffmpeg conversion of unsupported formats (e.g. .oga from Telegram)
into MP3 before sending to Groq.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from groq import AsyncGroq
    HAS_GROQ = True
except ImportError:
    HAS_GROQ = False

DEFAULT_DOWNLOADS = Path(__file__).resolve().parent.parent / "data" / "downloads"

# Extensions accepted by Groq Whisper API (as of 2025-06-28)
_GROQ_ALLOWED_EXT = {
    ".flac", ".mp3", ".mp4", ".mpeg", ".mpga",
    ".m4a", ".ogg", ".opus", ".wav", ".webm",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _convert_audio_to_mp3(source: Path) -> Path | None:
    """Convert any audio to mono 16kHz MP3 via ffmpeg. Returns path or None."""
    output = source.with_suffix(".mp3")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(source),
                "-ac", "1",
                "-ar", "16000",
                "-b:a", "64k",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg conversion failed: {result.stderr[:400]}")
            return None
        logger.info(
            f"Converted {source.name} → {output.name} "
            f"({output.stat().st_size} bytes)"
        )
        return output
    except FileNotFoundError:
        logger.error(
            "ffmpeg not found — install ffmpeg to transcribe "
            "unsupported audio formats"
        )
        return None
    except Exception as exc:
        logger.exception(f"ffmpeg conversion error: {exc}")
        return None


async def _get_client(proxy: str = "") -> AsyncGroq | None:
    """Return configured AsyncGroq client or None."""
    if not HAS_GROQ:
        logger.error("groq package not installed. Run: pip install groq")
        return None
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        logger.error("GROQ_API_KEY env var not set")
        return None
    kwargs: dict[str, Any] = {"api_key": api_key}
    if proxy:
        import httpx
        kwargs["http_client"] = httpx.AsyncClient(proxy=proxy)
    return AsyncGroq(**kwargs)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def groq_transcribe(
    audio_path: str,
    language: str = "zh",
    prompt: str = "",
    proxy: str = "socks5://127.0.0.1:1080",
) -> dict[str, Any]:
    """Transcribe an audio file using Groq Whisper (whisper-large-v3)."""
    path = Path(audio_path)
    if not path.exists():
        return {"ok": False, "error": f"File not found: {audio_path}"}
    if not path.is_file():
        return {"ok": False, "error": f"Not a file: {audio_path}"}

    # --- FIX: rename .oga -> .ogg (Groq accepts .ogg but not .oga) ---
    if path.suffix.lower() == ".oga":
        new_path = path.with_suffix(".ogg")
        path.rename(new_path)
        path = new_path
        logger.info(f"Renamed .oga → .ogg: {path}")

    # ── format check + auto-convert if needed ──────────────────────────
    converted_path: Path | None = None
    if path.suffix.lower() not in _GROQ_ALLOWED_EXT:
        logger.warning(
            f"Unsupported format '{path.suffix}' — Groq accepts: "
            f"{', '.join(sorted(_GROQ_ALLOWED_EXT))}. Converting via ffmpeg…"
        )
        converted_path = _convert_audio_to_mp3(path)
        if converted_path is None:
            return {
                "ok": False,
                "error": (
                    f"Unsupported audio format '{path.suffix}'. "
                    "Install ffmpeg and ensure the file is valid audio."
                ),
            }
        path = converted_path

    client = await _get_client(proxy=proxy)
    if client is None:
        return {
            "ok": False,
            "error": (
                "Groq client unavailable — "
                "check GROQ_API_KEY and pip install groq"
            ),
        }

    try:
        with open(path, "rb") as fh:
            transcript = await client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=(path.name, fh),
                language=language,
                prompt=prompt,
                response_format="verbose_json",
            )
        text = transcript.text.strip()
        result = {
            "ok": True,
            "text": text,
            "language": language,
            "model": "whisper-large-v3",
            "duration_s": getattr(transcript, "duration", None),
            "segments": getattr(transcript, "segments", None),
        }
        logger.info(f"Transcribed {path.name} → {len(text)} chars")
        return result

    except Exception as exc:
        logger.exception(f"Groq transcription failed: {exc}")
        return {"ok": False, "error": str(exc)}
    finally:
        # Clean up temporary converted file
        if converted_path is not None and converted_path.exists():
            try:
                converted_path.unlink()
                logger.debug(f"Cleaned up temp file: {converted_path}")
            except Exception:
                pass
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass


async def groq_transcribe_telegram(
    file_id: str,
    language: str = "zh",
    prompt: str = "",
    proxy: str = "socks5://127.0.0.1:1080",
    destination_dir: str = "",
) -> dict[str, Any]:
    """Download a Telegram voice message and transcribe it via Groq Whisper.

    Requires telegram_tools infrastructure for download. Format conversion
    is handled automatically by ``groq_transcribe``.

    Args:
        file_id: Telegram file_id of the voice message.
        language: ISO language code (zh, en, ja, ko, …). Default zh.
        prompt: Optional context prompt.
        proxy: Optional proxy URL.
        destination_dir: Directory to save the downloaded audio file.

    Returns:
        dict: {"ok": True, "text": "…", "audio_path": "…"} or {"ok": False, …}
    """
    dest = Path(destination_dir) if destination_dir else DEFAULT_DOWNLOADS
    dest.mkdir(parents=True, exist_ok=True)

    # Import locally to avoid circular dependency
    from .telegram_tools import telegram_download_file

    dl_result = await telegram_download_file(
        file_id=str(file_id), destination_dir=str(dest)
    )
    if not dl_result.get("ok"):
        return {
            "ok": False,
            "error": f"Telegram download failed: {dl_result.get('error')}",
            "details": dl_result,
        }

    # telegram_download_file returns the path under the key "path"
    audio_path = dl_result.get("path", "")
    if not audio_path:
        return {
            "ok": False,
            "error": "Download succeeded but no path returned",
            "details": dl_result,
        }

    # Telegram sends .oga (Opus-in-Ogg); rename to .ogg for Groq compatibility
    audio = Path(audio_path)
    if audio.suffix.lower() == ".oga":
        new_path = audio.with_suffix(".ogg")
        audio.rename(new_path)
        audio_path = str(new_path)
        logger.info(f"Renamed .oga → .ogg: {new_path}")

    # ─── FIX: single call, no duplicate ───────────────────────────────
    transcribe_result = await groq_transcribe(
        audio_path=audio_path,
        language=language,
        prompt=prompt,
        proxy=proxy,
    )

    # Add the audio path to the result for reference
    transcribe_result["audio_path"] = audio_path
    return transcribe_result


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[tuple[str, Any, str, dict[str, Any]]] = [
    (
        "groq_transcribe",
        groq_transcribe,
        (
            "Transcribe an audio file using Groq's FREE Whisper API "
            "(whisper-large-v3). 50+ languages. Unsupported formats are "
            "auto-converted via ffmpeg. Requires GROQ_API_KEY env var."
        ),
        {
            "type": "object",
            "properties": {
                "audio_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to audio file "
                        "(mp3, wav, ogg, flac, m4a, oga, …)"
                    ),
                },
                "language": {
                    "type": "string",
                    "description": "ISO language code: zh, en, ja, ko, etc. (default: zh)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional context prompt for transcription style",
                },
                "proxy": {
                    "type": "string",
                    "description": "Optional proxy URL (default is socks5://127.0.0.1:1080)",
                },
            },
            "required": ["audio_path"],
        },
    ),
    (
        "groq_transcribe_telegram",
        groq_transcribe_telegram,
        (
            "Download a Telegram voice message (by file_id) and transcribe "
            "via Groq Whisper. Combines telegram_download_file + "
            "groq_transcribe into one call."
        ),
        {
            "type": "object",
            "properties": {
                "file_id": {
                    "type": "string",
                    "description": "Telegram file_id of the voice message",
                },
                "language": {
                    "type": "string",
                    "description": "ISO language code (default: zh)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional context prompt",
                },
                "proxy": {
                    "type": "string",
                    "description": "Optional proxy URL (default is socks5://127.0.0.1:1080)",
                },
                "destination_dir": {
                    "type": "string",
                    "description": "Directory to save downloaded audio",
                },
            },
            "required": ["file_id"],
        },
    ),
]


def register_all(registry) -> None:
    """Register every tool defined in this module onto *registry*."""
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} Groq Whisper tools")
