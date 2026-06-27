"""Dynamic tool registry with hot-reload for MASTERMIND v2."""

from __future__ import annotations

import importlib
import sys
import pkgutil
import inspect
from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass, field

from loguru import logger


@dataclass
class ToolDef:
    """Definition of a registered tool."""
    name: str
    description: str
    func: Callable
    parameters: dict = field(default_factory=dict)
    module_name: str = ""


class ToolRegistry:
    """Async-first tool registry with hot-reload via importlib."""

    def __init__(self, tools_package: str = "deep_agent_future.builtin_tools"):
        self._tools_package = tools_package
        self._tools: Dict[str, ToolDef] = {}
        self._version: int = 0
        self._loaded_modules: set[str] = set()
        self._bot = None

    def set_bot(self, bot) -> None:
        """Store the Telegram bot instance for tools to use."""
        self._bot = bot
        if not self._bot:
            logger.error(f"Failed to set bot for tool {self._tools_package}")

    def get_bot(self):
        """Retrieve the stored bot instance."""
        if not self._bot:
            logger.error(f"Failed to get bot for tool {self._tools_package}")
        return self._bot

    @property
    def version(self) -> int:
        return self._version


    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


    def register(
        self,
        name: str,
        description: str,
        parameters: Optional[dict] = None,
    ) -> Callable:
        """Decorator to register an async tool function."""
        def wrapper(func: Callable) -> Callable:
            if not inspect.iscoroutinefunction(func):
                logger.warning(f"Tool '{name}' is not async")
            module_name = func.__module__
            self._tools[name] = ToolDef(
                name=name, description=description,
                func=func, parameters=parameters or {}, module_name=module_name,
            )
            self._version += 1
            logger.debug(f"Registered tool: {name} from {module_name}")
            return func
        return wrapper


    def register_function(
        self, func: Callable, name: str, description: str,
        parameters: Optional[dict] = None,
    ) -> None:
        module_name = func.__module__
        self._tools[name] = ToolDef(
            name=name, description=description,
            func=func, parameters=parameters or {}, module_name=module_name,
        )
        self._version += 1


    def get_tool(self, name: str) -> Optional[ToolDef]:
        return self._tools.get(name)


    def get_openai_tools(self) -> list[dict]:
        tools = []
        for tdef in self._tools.values():
            tools.append({
                "type": "function",
                "function": {
                    "name": tdef.name,
                    "description": tdef.description,
                    "parameters": tdef.parameters,
                },
            })
        return tools


    async def call_tool(self, tool_name: str, **kwargs: Any) -> str:
        tdef = self._tools.get(tool_name)
        if not tdef:
            return f"Error: tool '{tool_name}' not found"
        try:
            result = await tdef.func(**kwargs)
            return str(result)
        except Exception as e:
            logger.error(f"Tool '{tool_name}' error: {e}")
            return f"Error executing '{tool_name}': {e}"


    def hot_reload(self) -> int:
        """Reload all submodules and re-register their tools."""
        reloaded = 0
        package = self._tools_package
        if package not in sys.modules:
            try:
                importlib.import_module(package)
            except ImportError as e:
                logger.error(f"Failed to import '{package}': {e}")
                return 0
        pkg = sys.modules[package]
        if not hasattr(pkg, '__path__'):
            return 0
        for _, mod_name, _ in pkgutil.iter_modules(pkg.__path__, prefix=package + '.'):
            if mod_name in sys.modules:
                try:
                    importlib.reload(sys.modules[mod_name])
                    self._loaded_modules.add(mod_name)
                    reloaded += 1
                except Exception as e:
                    logger.error(f"Failed to reload '{mod_name}': {e}")
            else:
                try:
                    importlib.import_module(mod_name)
                    self._loaded_modules.add(mod_name)
                    reloaded += 1
                except Exception as e:
                    logger.error(f"Failed to load '{mod_name}': {e}")
        # Critical: re-register all tools after module reloads
        try:
            from deep_agent_future.builtin_tools import register_all
            register_all(self)
            logger.info(f"Registry reloaded: {reloaded} modules, {len(self._tools)} tools re-registered")
        except ImportError as e:
            logger.error(f"Failed to import register_all: {e}")
        self._version += 1
        return reloaded

    def list_tools(self) -> str:
        lines = [f"ToolRegistry v{self._version} — {len(self._tools)} tools:"]
        for tool_name, tdef in sorted(self._tools.items()):
            lines.append(f"  {tool_name}: {tdef.description[:80]}")
        return '\n'.join(lines)
_registry: Optional[ToolRegistry] = None
_registry_initialized: bool = False


def get_registry() -> ToolRegistry:
    global _registry, _registry_initialized
    if _registry is None:
        _registry = ToolRegistry()
    if not _registry_initialized:
        try:
            from deep_agent_future.builtin_tools import register_all
            register_all(_registry)
            _registry_initialized = True
        except ImportError:
            logger.error("Cannot auto-register builtin tools (import failed)")
    return _registry