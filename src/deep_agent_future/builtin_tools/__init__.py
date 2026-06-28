"""Builtin tools for MASTERMIND v2. Auto-registered on import."""

from loguru import logger


def register_all(registry):
    from . import fs_tools, search_tools, git_tools, tavily_tools, meta_tools, edit_tools, telegram_tools, groq_whisper_tools, tts_tools, additional_tools, rest_api_tool, window_tools
    fs_tools.register_all(registry)
    search_tools.register_all(registry)
    git_tools.register_all(registry)
    tavily_tools.register_all(registry)
    meta_tools.register_all(registry)
    edit_tools.register_all(registry)
    telegram_tools.register_all(registry)
    groq_whisper_tools.register_all(registry)
    tts_tools.register_all(registry)
    additional_tools.register_all(registry)
    rest_api_tool.register_all(registry)
    window_tools.register_all(registry)
    logger.info("All builtin tools registered")
