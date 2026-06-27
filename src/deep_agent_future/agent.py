"""MASTERMIND v2 — Core async agent loop. ContextPool v3 integrated."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from loguru import logger

from context_manager import ContextPool
from tool_registry import ToolRegistry, get_registry

LLM_MAX_OUTPUT_TOKENS = 30000
LLM_MODEL = "deepseek-v4-pro"  # thinking mode enabled


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


def validate_message_sequence(messages: list[dict]) -> None:
    """
    Check that every tool message has a preceding assistant message
    with a tool_calls entry that includes its tool_call_id.
    Raises ValueError with details if invalid.
    """
    tool_call_ids = set()
    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            # Collect all tool_call_ids from this assistant message
            for tc in msg["tool_calls"]:
                tool_call_ids.add(tc["id"])
        elif role == "tool":
            tc_id = msg.get("tool_call_id")
            if tc_id not in tool_call_ids:
                # Check if the immediately preceding message is assistant with this id
                prev = messages[i-1] if i > 0 else None
                if prev and prev.get("role") == "assistant" and prev.get("tool_calls"):
                    # Check if the id exists in its tool_calls
                    ids_in_prev = {tc["id"] for tc in prev["tool_calls"]}
                    if tc_id in ids_in_prev:
                        continue  # valid
                # If we reach here, it's orphaned
                raise ValueError(
                    f"Orphaned tool message at index {i} with tool_call_id={tc_id}. "
                    f"Preceding message: {prev} (if any)."
                )

class Agent:
    """Async reasoning agent with hot-reload tools, crash recovery, and layered context."""

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

        # Load last memory into context (from previous compression)
        if self._last_memory:
            self.messages.assign_messages(construct_history(self._last_memory))

        logger.info(f"Agent '{name}' initialized ({LLM_MODEL}), "
                     f"crash recovery: {self.messages.length > 0}")

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
        try:
            result = await asyncio.wait_for(
                self._registry.call_tool(func_name, **args),
                timeout=120.0  # 2-minute timeout per tool
            )
        except asyncio.TimeoutError:
            logger.error(f"Tool '{func_name}' timed out after 120s")
            return {
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": func_name,
                "content": f"Error: tool '{func_name}' timed out (>120s). "
                           f"Try narrowing the search scope.",
            }

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

    def _build_messages_for_llm(self) -> list[dict]:
        """Build full message list with all memory layers.
        
        Order (DeepSeek cache-optimized):
          system → base_prompts → persistent → compressed → masked → sliding window
        
        Critical: every assistant message MUST have non-empty content OR tool_calls.
        """
        self.messages.log_state("STATE AT build_messager_for_llm")
        messages: list[dict] = []

        # Layer 0: System prompt (static → prefix-cached by DeepSeek)
        messages.append(self._system_prompt)

        # Layer 1: Base prompts (tool definitions, guidelines — static)
        if self._base_prompts:
            messages.extend(construct_history(self._base_prompts))

        # Layer 2: Persistent memory (key facts across sessions)
        persistent = self.messages._persistent.as_context_string()
        if persistent:
            messages.append({
                "role": "user",
                "name": "MASTERMIND",
                "content": persistent,
            })

        # Layer 3: Compressed history (LLM summaries of old batches)
        for entry in self.messages._compressed:
            d = {"role": entry.role, "content": entry.content or ""}
            if entry.reasoning:
                d["reasoning_content"] = entry.reasoning
            if entry.tool_calls:
                d["tool_calls"] = entry.tool_calls
            messages.append(d)

        # Layer 4: Masked observations (old tool outputs replaced with [MASKED: ...])
        for entry in self.messages.masked_entries:
            d = {"role": entry.role, "content": entry.content}
            if entry.tool_name:
                d["name"] = entry.tool_name
            if entry.tool_call_id:
                d["tool_call_id"] = entry.tool_call_id
            if entry.tool_calls:
                d["tool_calls"] = entry.tool_calls
            if entry.reasoning:
                d["reasoning_content"] = entry.reasoning
            # Safety: ensure assistant messages always have content or tool_calls
            if entry.role == "assistant" and not d.get("content") and not d.get("tool_calls"):
                if entry.reasoning:
                    d["content"] = f"[Thought: {entry.reasoning.split(chr(10))[0][:200]}]"
                else:
                    d["content"] = "[No content]"
            messages.append(d)

        # Layer 5: Sliding window (last N messages in full detail)
        messages.extend(self.messages.messages)

        # ---- DEBUG: log message structure ----
        logger.debug(f"Built {len(messages)} messages for LLM")
        for idx, msg in enumerate(messages):
            role = msg.get("role")
            content_preview = (msg.get("content") or "")[:100]
            tool_calls = bool(msg.get("tool_calls"))
            tc_id = msg.get("tool_call_id", "")
            logger.debug(
                f"  [{idx}] role={role}, content='{content_preview}', "
                f"has_tool_calls={tool_calls}, tool_call_id={tc_id}"
            )
        # ---- end debug ----

        # Validate the sequence (optional: can be commented out after fixing)
        try:
            validate_message_sequence(messages)
        except ValueError as e:
            logger.error(f"Message sequence validation failed: {e}")
            # Optionally dump full messages to file for inspection
            import json
            with open("invalid_messages.json", "w", encoding='utf-8') as f:
                json.dump(messages, f, indent=2, default=str)
            raise

        return messages

    async def llm_request(self) -> dict:
        """Make an async LLM API call with layered context."""
        messages = self._build_messages_for_llm()

        ctx_len = sum(len(m.get("content", "") or "") + len(m.get("reasoning_content", "") or "")
                      for m in messages)
        est_tokens = ctx_len // 3
        logger.info(f"LLM request: {len(messages)} msgs, ~{est_tokens} tokens")

        tools = self._registry.get_openai_tools() if self._use_tools else []

        try:
            response = await self._client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                tools=tools or None,
                stream=False,
                max_tokens=LLM_MAX_OUTPUT_TOKENS,
                temperature=1.0,
            )
        except Exception as e:
            # Log full error with traceback and dump messages to file
            logger.exception(f"LLM API call failed: {e}")
            # Dump messages for post-mortem
            import json
            with open("failed_messages.json", "w", encoding="utf-8") as f:
                json.dump(messages, f, indent=2, default=str)
            raise  # re-raise

        # Validate response structure
        if response is None:
            raise ValueError("API returned None response")
        if not hasattr(response, "choices") or not response.choices:
            raise ValueError(f"Response missing 'choices': {response}")

        response_dict = response.model_dump()
        if not response_dict.get("choices"):
            # The API might have returned an error. Log the full response.
            logger.error(f"LLM response has no choices: {response_dict}")
            raise ValueError(f"Invalid LLM response: {response_dict}")
        return response_dict


    async def run(self, initial_user_request: str = "", reasoning_callback=None) -> str:
        """
        Main agent loop.
        Returns final response text.
        reasoning_callback: async callable(thought_text) for live reasoning output.
        """
        max_iterations = 15
        iteration = 0

        # Add user message to context
        if initial_user_request:
            self.messages.append({
                "role": "user",
                "name": "User",
                "content": initial_user_request,
            })

        # Proactive compression: if context overflowed before LLM call, compress now
        if self.messages.overflow and self._helper_agent:
            logger.warning(
                f"Overflow before LLM request ({self.messages.get_context_length()} tokens) — "
                "compressing proactively"
            )
            try:
                await asyncio.wait_for(
                    self.messages.compress(self._helper_agent),
                    timeout=60.0
                )
            except asyncio.TimeoutError:
                logger.error("Proactive compression timed out")
            except Exception as e:
                logger.error(f"Proactive compression failed: {e}")

        while iteration < max_iterations:
            iteration += 1

            # Check for new tools (hot-reload)
            if self._registry.version > 0:
                logger.debug(f"Registry v{self._registry.version}, {len(self._registry.tool_names)} tools ready")

            try:
                response = await self.llm_request()
            except Exception as e:
                logger.exception(f"LLM request failed at iteration {iteration}")
                # Log the current messages state
                self.messages.log_state("FAILED LLM REQUEST")
                # Optionally dump messages
                import json
                with open("failed_context.json", "w", encoding='utf-8') as f:
                    # You'll need to serialize the messages, maybe using self.messages._all_entries
                    json.dump([self.messages._entry_to_dict(e) for e in self.messages._all_entries], f, indent=2,
                              default=str)
                raise

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

                # Check if context overflowed — trigger compression
                if self.messages.overflow and self._helper_agent:
                    try:
                        await asyncio.wait_for(
                            self.messages.compress(self._helper_agent),
                            timeout=60.0
                        )
                    except asyncio.TimeoutError:
                        logger.error("Compression timed out after 60s")
                    except Exception as e:
                        logger.error(f"Compression failed: {e}")
            else:
                # Final response — no tool calls
                content = message.get("content", "")
                logger.info(f"Agent finished in {iteration} iterations, "
                           f"context: {self.messages.length} msgs, "
                           f"~{self.messages.get_context_length()} tokens")
                return content

        logger.warning(f"Max iterations ({max_iterations}) reached")
        return "Max iterations reached without final response."

    async def run_with_crash_recovery(self, initial_user_request: str = "", reasoning_callback=None) -> str:
        """Run agent with crash recovery."""
        try:
            return await self.run(initial_user_request, reasoning_callback)
        except Exception as e:
            logger.exception(f"Agent crashed: {e}")  # prints full traceback
            self.messages._emergency_save()
            raise


def NOW() -> str:
    return datetime.now().strftime("%d.%m.%Y, %H:%M")
