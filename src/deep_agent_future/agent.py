"""MASTERMIND v2 — Core async agent loop."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from loguru import logger

from .context_manager import ContextPool
from .tool_registry import ToolRegistry, get_registry

LLM_MAX_OUTPUT_TOKENS = 30000
LLM_MODEL = "deepseek-reasoner"  # thinking mode enabled


def construct_history(prompts_list: list[tuple[str, Optional[str]]]) -> list[dict]:
    """Build base prompt messages from text/file tuples."""
    composed = []
    for prompt_text, prompt_file in prompts_list:
        content = prompt_text
        if prompt_file:
            try:
                fp = Path(prompt_file)
                if not fp.is_absolute():
                    fp = Path(__file__).resolve().parent / fp
                content += fp.read_text(encoding='utf-8')
            except Exception:
                logger.warning(f"File {prompt_file} not loaded")
        content += "\n\n---\n\n"
        composed.append({
            "role": "user",
            "name": "MASTERMIND",
            "content": content,
        })
    return composed


class Agent:
    """Async reasoning agent with hot-reload tools and crash recovery."""

    def __init__(
        self,
        name: str = "MASTERMIND",
        system_prompt: str = "",
        base_prompts: Optional[list] = None,
        last_memory: Optional[list] = None,
        use_tools: bool = True,
        save_history: bool = True,
        base_url: str = "https://api.deepseek.com/",
    ):
        self.name = name
        api_key = os.environ.get(f'DEEPSEEK_API_KEY_{self.name}') or os.environ.get('DEEPSEEK_API_KEY', '')
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._system_prompt = {"role": "system", "name": "Creator", "content": system_prompt}
        self._base_prompts = base_prompts or []
        self._last_memory = last_memory or []
        self._use_tools = use_tools
        self._save_history = save_history
        self._helper_agent: Optional[Agent] = None
        self.messages = ContextPool()
        self._registry: ToolRegistry = get_registry()

        # Load last memory into context
        if self._last_memory:
            self.messages.assign_messages(construct_history(self._last_memory))

        logger.info(f"Agent '{name}' initialized ({LLM_MODEL})")

    def add_helper_agent(self, helper: Agent) -> None:
        self._helper_agent = helper

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def _execute_single_tool(self, tool_call, user_request: str = "") -> dict:
        """Execute one tool call and return the result message."""
        func_name = tool_call.function.name
        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error for {func_name}: {e}")
            return {
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": func_name,
                "content": f"Error: invalid JSON arguments — {e}",
            }

        logger.info(f"Tool: {func_name}({json.dumps(args, ensure_ascii=False)[:200]})")
        result = await self._registry.call_tool(func_name, **args)

        return {
            "tool_call_id": tool_call.id,
            "role": "tool",
            "name": func_name,
            "content": result,
        }

    async def _execute_tools_parallel(self, tool_calls, user_request: str = "") -> list[dict]:
        """Execute multiple tool calls concurrently."""
        tasks = [self._execute_single_tool(tc, user_request) for tc in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        output = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                output.append({
                    "tool_call_id": tool_calls[i].id,
                    "role": "tool",
                    "name": tool_calls[i].function.name,
                    "content": f"Error: {result}",
                })
            else:
                output.append(result)
        return output

    async def llm_request(self) -> dict:
        """Make an async LLM API call."""
        messages = (
            [self._system_prompt]
            + construct_history(self._base_prompts)
            + self.messages.messages
        )

        ctx_len = self.messages.get_context_length()
        logger.info(f"LLM request: {len(messages)} msgs, ~{ctx_len} chars")

        tools = self._registry.get_openai_tools() if self._use_tools else []

        response = await self._client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=tools or None,
            stream=False,
            max_tokens=LLM_MAX_OUTPUT_TOKENS,
            temperature=1.0,
        )
        return response.model_dump()

    async def run(self, initial_user_request: str = "", reasoning_callback=None) -> str:
        """
        Main agent loop.
        Returns final response text.
        reasoning_callback: async callable(thought_text) for live reasoning output.
        """
        max_iterations = 15
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # Check for new tools (hot-reload)
            if self._registry.version > 0:
                logger.debug(f"Registry v{self._registry.version}, {len(self._registry.tool_names)} tools ready")

            response = await self.llm_request()
            choice = response["choices"][0]
            message = choice["message"]

            # Extract reasoning if present
            reasoning = message.get("reasoning_content", "")
            if reasoning and reasoning_callback:
                await reasoning_callback(reasoning)

            has_tool_calls = bool(message.get("tool_calls"))
            self.messages.append_assistant_message(message, self._save_history, has_tool_calls)

            if has_tool_calls:
                tool_calls_raw = message["tool_calls"]
                # Convert dicts to objects for compatibility
                tool_call_objects = []
                for tc in tool_calls_raw:
                    # Create a simple object with .id, .function.name, .function.arguments
                    class ToolCallObj:
                        pass
                    obj = ToolCallObj()
                    obj.id = tc["id"]
                    obj.function = type('fn', (), {})()
                    obj.function.name = tc["function"]["name"]
                    obj.function.arguments = tc["function"]["arguments"]
                    tool_call_objects.append(obj)

                # Execute tools in parallel
                tool_results = await self._execute_tools_parallel(
                    tool_call_objects, initial_user_request
                )

                for result in tool_results:
                    self.messages.append(result, save=False)

                # Check if context overflowed
                if self.messages.overflow and self._helper_agent:
                    self.messages.compress(self._helper_agent)
            else:
                # Final response — no tool calls
                content = message.get("content", "")
                logger.info(f"Agent finished in {iteration} iterations")
                return content

        logger.warning(f"Max iterations ({max_iterations}) reached")
        return "Max iterations reached without final response."

    async def run_with_crash_recovery(self, initial_user_request: str = "", reasoning_callback=None) -> str:
        """Run agent with crash recovery."""
        try:
            return await self.run(initial_user_request, reasoning_callback)
        except Exception as e:
            logger.error(f"Agent crashed: {e}")
            self.messages._emergency_save()
            raise


def NOW() -> str:
    return datetime.now().strftime("%d.%m.%Y, %H:%M")
