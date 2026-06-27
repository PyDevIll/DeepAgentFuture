"""MASTERMIND v2 — Main entry point."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from agent import Agent, NOW
from telegram_bot import TelegramBot, set_bot
from tool_registry import get_registry
from builtin_tools import register_all as register_builtin_tools
import sys

def global_exception_handler(exc_type, exc_value, exc_traceback):
    logger.exception("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = global_exception_handler

async def main() -> None:
    """Start MASTERMIND v2."""
    load_dotenv()

    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="DEBUG") #os.environ.get("LOG_LEVEL", "INFO"))
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
- **Goal**: self-sustained, continuously learning system  
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
    bot = TelegramBot(
        reasoning_chat_id=-1003969262771
    )

    # Make bot accessible to tools
    set_bot(bot)

    # File handler: auto-download incoming files to data/downloads/
    DOWNLOADS_DIR = Path(__file__).resolve().parent / "data" / "downloads"
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    async def handle_file(msg: dict) -> None:
        """Auto-download incoming documents/photos."""
        chat_id = msg["chat"]["id"]
        doc = msg.get("document")
        photo = msg.get("photo")

        if doc:
            file_id = doc["file_id"]
            file_name = doc.get("file_name", file_id)
            logger.info(f"Document from {chat_id}: {file_name} ({doc.get('file_size', 0)} bytes)")
            result = await bot.download_file(file_id, str(DOWNLOADS_DIR))
            if result.get("ok"):
                await bot.send_message(
                    chat_id,
                    f"📥 Downloaded: `{result['file_name']}` ({result['file_size']} bytes)",
                )
            else:
                await bot.send_message(chat_id, f"❌ Failed: {result.get('error')}")

        elif photo:
            # Get largest photo size
            largest = max(photo, key=lambda p: p.get("file_size", 0))
            file_id = largest["file_id"]
            logger.info(f"Photo from {chat_id}: {largest.get('file_size', 0)} bytes")
            result = await bot.download_file(file_id, str(DOWNLOADS_DIR))
            if result.get("ok"):
                await bot.send_message(
                    chat_id,
                    f"📥 Downloaded photo: `{result['file_name']}` ({result['file_size']} bytes)",
                )
            else:
                await bot.send_message(chat_id, f"❌ Failed: {result.get('error')}")

    bot.set_file_handler(handle_file)

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
