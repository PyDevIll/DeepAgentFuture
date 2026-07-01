"""MASTERMIND v2 — Main entry point."""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from agent import Agent, NOW
from telegram_bot import TelegramBot
from tool_registry import get_registry
from builtin_tools import register_all as register_builtin_tools
from scheduler import get_scheduler
import sys


def global_exception_handler(exc_type, exc_value, exc_traceback):
    logger.exception("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = global_exception_handler


async def main() -> None:
    """Start MASTERMIND v2."""
    load_dotenv()

    # Configure logging
    logger.remove()
    logger.add(sys.stderr, level="DEBUG")  # os.environ.get("LOG_LEVEL", "INFO"))
    logger.add(
        Path(__file__).resolve().parent / "data" / "agent.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
    )

    logger.info("MASTERMIND v2 starting...")

    # Global queue for incoming requests (user messages + scheduled tasks)
    request_queue = asyncio.Queue()

    # Initialize tool registry with builtin tools
    registry = get_registry()
    register_builtin_tools(registry)
    logger.info(f"Registered {len(registry.tool_names)} tools: {registry.tool_names}")

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
        base_prompts=[
            ("## **IDENTITY**\n", "system_prompts/core.md"),
            ("\n## **APPLICATION ARCHITECTURE**\n", "system_prompts/extended.md"),
            ("\n## **Tools Guidelines & Best Practices**\n", "system_prompts/tools_guidelines.md"),
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
    registry = get_registry()
    registry.set_bot(bot)

    # File handler: auto-download incoming files to data/downloads/
    DOWNLOADS_DIR = Path(__file__).resolve().parent / "data" / "downloads"
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- Request enqueuing ----
    async def handle_message(msg: dict) -> None:
        """Enqueue incoming user messages for processing."""
        await request_queue.put({"type": "user", "msg": msg})

    # ---- Actual processing logic for user messages ----
    async def process_user_message(msg: dict) -> None:
        """Handle a user message: build context, run agent, send reply."""
        chat_id = msg["chat"]["id"]

        # Build rich message context
        text = msg.get("text", "") or msg.get("caption", "")

        # Format entities if present
        entities_str = ""
        if msg.get("entities"):
            for ent in msg["entities"]:
                ent_type = ent["type"]
                entity_text = text[ent["offset"]: ent["offset"] + ent["length"]]
                ent_desc = f"  • {ent_type}: \"{entity_text}\""
                if ent.get("url"):
                    ent_desc += f" → {ent['url']}"
                if ent.get("user"):
                    ent_desc += f" → user {ent['user'].get('id')}"
                entities_str += ent_desc + "\n"

        # Format reply-to info
        reply_str = ""
        if msg.get("reply_to_message"):
            rt = msg["reply_to_message"]
            reply_from = rt.get("from", {})
            reply_text = rt.get("text", rt.get("caption", ""))
            reply_str = f"Reply to: @{reply_from.get('username', '?')} ({reply_from.get('first_name', '')}): \"{reply_text[:200]}\"\n"

        # Format forward info
        forward_str = ""
        if msg.get("forward_origin"):
            fo = msg["forward_origin"]
            ftype = fo.get("type", "")
            if ftype == "user":
                fu = fo.get("sender_user", {})
                forward_str = f"Forwarded from user: @{fu.get('username', '?')} ({fu.get('first_name', '')})\n"
            elif ftype == "channel":
                fc = fo.get("chat", {})
                forward_str = f"Forwarded from channel: {fc.get('title', '?')}\n"
            elif ftype == "chat":
                fc = fo.get("sender_chat", {})
                forward_str = f"Forwarded from chat: {fc.get('title', '?')}\n"

        # Sender info
        sender = msg.get("from", {})
        sender_str = f"From: @{sender.get('username', '?')} ({sender.get('first_name', '')} {sender.get('last_name', '')})\n"

        # Chat info
        chat_title = msg.get("chat", {}).get("title", str(chat_id))

        # Assemble enhanced request
        context_parts = [
            f"Current chat_id: {chat_id}",
            f"Chat: {chat_title}",
            sender_str.rstrip(),
        ]
        if reply_str:
            context_parts.append(reply_str.rstrip())
        if forward_str:
            context_parts.append(forward_str.rstrip())
        if entities_str:
            context_parts.append("Entities:\n" + entities_str.rstrip())

        context_str = "\n".join(context_parts)

        enhanced_request = f"{context_str}\n\nUser request: {text}"

        logger.info(f"Message from {chat_id}: {text[:100]}")

        async def reasoning_callback(thought: str) -> None:
            await bot.send_reasoning(thought)

        response = await agent.run_with_crash_recovery(
            initial_user_request=enhanced_request,
            reasoning_callback=reasoning_callback,
        )

        if response:
            await bot.send_reply(chat_id, response)

    # ---- Processing logic for scheduled tasks ----
    async def process_scheduled_task(task: dict) -> None:
        """Run agent with a scheduled prompt."""
        chat_id = task["chat_id"]
        prompt = task["prompt"]
        logger.info(f"Processing scheduled task {task['id']}: {prompt[:100]}")

        async def reasoning_callback(thought: str) -> None:
            await bot.send_reasoning(thought)

        response = await agent.run_with_crash_recovery(
            initial_user_request=prompt,
            reasoning_callback=reasoning_callback,
        )

        if response:
            await bot.send_reply(chat_id, f"🕒 **Scheduled task result:**\n\n{response}")

        scheduler = get_scheduler()
        scheduler.mark_done(task["id"])

    # ---- Worker coroutine (processes requests sequentially) ----
    async def worker() -> None:
        """Process requests from the queue sequentially."""
        while True:
            req = await request_queue.get()
            try:
                if req["type"] == "user":
                    await process_user_message(req["msg"])
                elif req["type"] == "scheduled":
                    await process_scheduled_task(req["task"])
            except Exception as e:
                logger.exception(f"Worker failed processing {req.get('type')}: {e}")
            finally:
                request_queue.task_done()

    # ---- Scheduler checker (polls due tasks every 60 seconds) ----
    async def scheduler_checker() -> None:
        """Poll the scheduler every minute and enqueue due tasks."""
        while True:
            await asyncio.sleep(60)
            sched = get_scheduler()
            due = sched.get_due_tasks()
            if due:
                logger.info(f"Found {len(due)} due scheduled task(s)")
                for task in due:
                    await request_queue.put({"type": "scheduled", "task": task})

    # ---- File handler (unchanged from original) ----
    async def handle_file(msg: dict) -> None:
        """Download incoming documents/photos/voice and route to processing."""
        chat_id = msg["chat"]["id"]
        doc = msg.get("document")
        photo = msg.get("photo")
        voice = msg.get("voice")

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

        if photo:
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

        if voice:
            file_id = voice["file_id"]
            duration = voice.get("duration", 0)
            logger.info(f"Voice message from {chat_id}: {duration}s")

            # Download the voice file
            result = await bot.download_file(file_id, str(DOWNLOADS_DIR))
            if not result.get("ok"):
                await bot.send_message(chat_id, f"❌ Voice download failed: {result.get('error')}")
                return

            audio_path = result["path"]
            logger.info(f"Voice saved to {audio_path}, transcribing...")

            # Transcribe via Groq Whisper
            from builtin_tools.groq_whisper_tools import groq_transcribe
            transcript_result = await groq_transcribe(
                audio_path,
                language="ru",  # Russian by default; Groq auto-detects well
            )

            if not transcript_result.get("ok"):
                await bot.send_message(
                    chat_id,
                    f"❌ Transcription failed: {transcript_result.get('error')}",
                )
                return

            transcript = transcript_result["text"]
            logger.info(f"Transcribed voice ({duration}s): {transcript[:100]}")

            # Route transcribed text to the agent via handle_message
            msg["text"] = transcript
            await handle_message(msg)

    bot.set_file_handler(handle_file)

    # Start all components concurrently
    logger.info("Starting Telegram polling, worker, and scheduler checker...")
    polling_task = asyncio.create_task(bot.start_polling(handle_message))
    worker_task = asyncio.create_task(worker())
    checker_task = asyncio.create_task(scheduler_checker())

    logger.info("All components started. Awaiting tasks...")
    await asyncio.gather(polling_task, worker_task, checker_task)


if __name__ == "__main__":
    asyncio.run(main())
