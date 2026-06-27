"""Builtin tools for MASTERMIND v2. Auto-registered on import."""

from loguru import logger


def register_all(registry):
    """Register all builtin tool modules with the given registry."""
    from . import fs_tools, search_tools, git_tools, tavily_tools, meta_tools, edit_tools, telegram_tools
    fs_tools.register_all(registry)
    search_tools.register_all(registry)
    git_tools.register_all(registry)
    tavily_tools.register_all(registry)
    meta_tools.register_all(registry)
    edit_tools.register_all(registry)
    telegram_tools.register_all(registry)
    logger.info("All builtin tools registered")
