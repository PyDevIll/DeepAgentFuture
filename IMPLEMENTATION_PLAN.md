# MASTERMIND v2 — Implementation Plan

## Architecture Overview

```
Deep_Agent_Future/
├── pyproject.toml
├── .env
├── .gitignore
├── README.md
├── IMPLEMENTATION_PLAN.md          ← this file
├── PROGRESS_REPORT.md              ← progress log
├── src/
│   └── deep_agent_future/
│       ├── __init__.py
│       ├── main.py                 ← async entry point
│       ├── agent.py                ← core agent loop (async)
│       ├── context_manager.py      ← ContextPool, compression, crash recovery
│       ├── tool_registry.py        ← dynamic tool loading, hot-reload
│       ├── telegram_bot.py         ← async Telegram integration
│       ├── reasoning_chat.py       ← separate reasoning output chat
│       ├── builtin_tools/
│       │   ├── __init__.py
│       │   ├── fs_tools.py         ← file system operations (migrated fs_toolkit)
│       │   ├── search_tools.py     ← web search, browse
│       │   ├── git_tools.py        ← git operations
│       │   └── aider_tools.py      ← Aider invocation
│       ├── system_prompts/
│       │   ├── core.md
│       │   ├── extended.md
│       │   └── tools_guidelines.md
│       └── data/
│           ├── message_history.md
│           ├── compressed_history.txt
│           └── last_compression.txt
└── tests/
    └── __init__.py
```

---

## Пункт 1: Hot-reload инструментов

**Проблема**: старый агент требует перезапуска для добавления инструментов.
**Решение**: `tool_registry.py` — реестр с динамической загрузкой через `importlib`.

### Архитектура:
- Инструменты лежат в `builtin_tools/` как отдельные модули
- Каждый модуль регистрирует свои функции в реестре через декоратор `@register_tool`
- `ToolRegistry.reload()` — перечитывает модули через `importlib.reload()`
- Агент перед каждым циклом проверяет `registry.version` и обновляет tool_list при изменениях
- Файловый вотчер (polling) для авто-детекта изменений

### API:
```python
@register_tool(name="fs_mkdir", description="Create directory")
async def fs_mkdir(path: str) -> str: ...

# Agent usage:
tools = registry.get_openai_tools()  # -> list[dict]
```

---

## Пункт 2: Редактирование и поиск по текстовым файлам

**Решение**: единый `fs_tools.py` с чтением, поиском И редактированием.

### Операции:
- `read` — чтение с бинарным детектом, умной обрезкой >50KB
- `search` — рекурсивный grep с фильтром по расширению
- `edit` — замена по строкам (line range + new content)
- `append` — добавление в конец файла
- `insert` — вставка на позицию

---

## Пункт 3: Манипуляции файловой системой

**Решение**: портировать `fs_toolkit.py` в `builtin_tools/fs_tools.py`.

Команды: `mkdir`, `touch`, `rm`, `mv`, `cp`, `tree`, `stat`, `find`, `sizes`, `grep`, `cd`, `pwd`.

---

## Пункт 4: Telegram-интеграция

**Решение**: асинхронный `telegram_bot.py` + разделение вывода.

- Входящие → основной чат
- Reasoning → отдельный REASONING_CHAT_ID
- Ответы → в чат отправителя
- `aiohttp` для асинхронных HTTP-запросов
- `asyncio.Queue` для входящих сообщений

---

## Пункт 5: Контроль контекста + DeepSeek cache

**Решение**: `context_manager.py` с автосжатием и персистентностью.

### DeepSeek Context Cache best practices:
1. System prompt — статический, кешируется (prefix caching)
2. Tool definitions — статические, кешируются
3. История — переменная, НЕ кешируется
4. Cache break: новый tool definition инвалидирует кеш
5. При переполнении — вызов компрессора
6. Crash recovery: автосейв каждые 5 сообщений

---

## Пункт 6: Асинхронность + параллельные вызовы

**Решение**: весь агент на `asyncio`.

```python
async def execute_tools(tool_calls: list[ToolCall]) -> list[ToolResult]:
    tasks = [execute_single(call) for call in tool_calls]
    return await asyncio.gather(*tasks, return_exceptions=True)
```

---

## Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Асинхронность | `asyncio` + `aiohttp` |
| HTTP-клиент | `httpx.AsyncClient` |
| LLM API | `openai` (async mode) |
| Telegram API | `aiohttp` |
| Валидация | `pydantic` |
| Логирование | `loguru` |
| Сериализация | `orjson` |

---

## Порядок реализации

### Фаза 1: Скелет
1. Структура проекта, pyproject.toml, .env, .gitignore
2. git init + первый коммит

### Фаза 2: Инструменты
3. tool_registry.py
4. builtin_tools/fs_tools.py
5. builtin_tools/search_tools.py

### Фаза 3: Агент
6. context_manager.py
7. agent.py

### Фаза 4: Telegram
8. telegram_bot.py
9. reasoning_chat.py

### Фаза 5: Интеграция
10. main.py — сборка
11. Тестирование

*Plan version: 1.0 | Created: 26.06.2026*
