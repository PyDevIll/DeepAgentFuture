"""Additional tools for MASTERMIND v2."""

import os
from typing import Optional
from loguru import logger

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# add python def here


TOOL_DEFINITIONS = [

]


def register_all(registry):
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} additional tools")
