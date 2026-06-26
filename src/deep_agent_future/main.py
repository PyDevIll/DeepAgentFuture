"""MASTERMIND v2 — Main entry point."""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from .agent import Agent, NOW
from .telegram_bot import TelegramBot
from .tool_registry import get_registry
from .builtin_tools import register_all as register_builtin_tools


async def main() -> None:
    """Start MASTERMIND v2."""
    load_dotenv()

    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"))
    logger.add(
        Path(__file__).resolve().parent / "data" / "agent.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
    )

    logger.info("MASTERMIND v2 starting...")

    # Initialize tool registry with builtin tools
    registry = get_registry()
    register_builtin_tools(registry)
    logger.info(f"Registered {len(registry.tool_names)} tools: {registry.tool_names}")

    # System prompt
    system_prompt = f"""## **IDENTITY**
- **Name**: The Autonomous LLM-based Agent MASTERMIND v2
- **Goal**: self‑sustained, continuously learning system  
- **Language**: Laconic instructive command-like wide weighty formal sentences
- **Environment**: Windows 10 system with access to file system and internet
- **Time**: {NOW()}
"""

    # Create helper agent for compression
    helper_agent = Agent(
        name="HELPER",
        system_prompt="""## Values
- Meaning: Retain core semantic content. Highest priority.
- Relevance: Extract only information relevant to the given task.
- Fidelity: Accurately reproduce key elements.
- Concise: Return only processed content. No questions.""",
        use_tools=False,
        save_history=False,
    )

    # Create main agent
    agent = Agent(
        name="MASTERMIND",
        system_prompt=system_prompt,
        base_prompts=[
            ("# System files:\n", None),
        ],
        last_memory=[
            ("# **PREVIOUS MEMORY SUMMARY**\n", "data/last_compression.txt"),
        ],
        use_tools=True,
        save_history=True,
    )
    agent.add_helper_agent(helper_agent)

    # Initialize Telegram bot
    bot = TelegramBot()

    # Message handler
    async def handle_message(msg: dict) -> None:
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")

        logger.info(f"Message from {chat_id}: {text[:100]}")

        # Reasoning callback — sends thoughts to reasoning chat
        async def reasoning_callback(thought: str) -> None:
            await bot.send_reasoning(thought)

        # Run agent
        response = await agent.run_with_crash_recovery(
            initial_user_request=text,
            reasoning_callback=reasoning_callback,
        )

        if response:
            await bot.send_reply(chat_id, response)

    # Start polling
    logger.info("Starting Telegram polling...")
    await bot.start_polling(handle_message)


if __name__ == "__main__":
    asyncio.run(main())
