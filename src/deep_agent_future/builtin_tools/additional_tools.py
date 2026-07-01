"""Additional tools for MASTERMIND v2."""

import os
import sys
import json
import asyncio
from typing import Optional
from loguru import logger


def _smart_decode(data: bytes) -> str:
    """Decode bytes trying UTF-8 first, fallback to cp1251 (Russian Windows) on failure."""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        pass
    try:
        return data.decode('cp1251')
    except UnicodeDecodeError:
        pass
    return data.decode('utf-8', errors='replace')


async def ping() -> str:
    """Simple ping/pong health check. Returns 'pong' with current timestamp."""
    from datetime import datetime
    return json.dumps({
        "result": "pong",
        "timestamp": datetime.now().isoformat(),
    }, ensure_ascii=False)


async def exec_python(parameter: str, timeout: int = 30) -> str:
    """Execute arbitrary Python code for quick testing and debugging.

    Parameter can be:
      - `-c "print('hello')"` — inline code (like python -c)
      - A `.py` filename (absolute or relative to agent's CWD)
      - Raw Python code (auto-wrapped as -c)
    
    Returns JSON: {"stdout": "...", "stderr": "..."}
    """
    # Determine execution mode
    if parameter.startswith('-c '):
        code = parameter[3:]
        args = ['-c', code]
    elif os.path.isfile(parameter):
        args = [parameter]
    elif os.path.isfile(os.path.join(os.getcwd(), parameter)):
        args = [os.path.join(os.getcwd(), parameter)]
    else:
        # Treat as raw code
        args = ['-c', parameter]

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return json.dumps({
            "stdout": _smart_decode(stdout),
            "stderr": _smart_decode(stderr),
            "returncode": proc.returncode,
        }, ensure_ascii=False)
    except asyncio.TimeoutError:
        proc.kill()
        return json.dumps({
            "stdout": "",
            "stderr": f"Timeout ({timeout}s) exceeded",
            "returncode": -1,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "stdout": "",
            "stderr": f"Execution error: {e}",
            "returncode": -1,
        }, ensure_ascii=False)


async def exec_shell(command: str, timeout: int = 30) -> str:
    """Execute arbitrary shell command on Windows 10 using cmd.exe /c.

    ⚠️ DANGEROUS: Full shell access. Use with extreme caution.
    - Runs via cmd.exe /c {command}
    - Supports batch commands, pipes, redirects (>, |, &&)
    - Returns JSON: stdout, stderr, returncode
    - Timeout kills the process

    Args:
        command: Shell command string (e.g., "dir /b", "ipconfig", "echo hello")
        timeout: Execution timeout in seconds (default: 30)

    Returns:
        JSON string with stdout, stderr, returncode
    """
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd(),
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return json.dumps({
            "stdout": _smart_decode(stdout),
            "stderr": _smart_decode(stderr),
            "returncode": proc.returncode,
        }, ensure_ascii=False)
    except asyncio.TimeoutError:
        proc.kill()
        return json.dumps({
            "stdout": "",
            "stderr": f"Timeout ({timeout}s) exceeded",
            "returncode": -1,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "stdout": "",
            "stderr": f"Execution error: {e}",
            "returncode": -1,
        }, ensure_ascii=False)


async def aider_run(
    instruction: str,
    files: str = "",
    model: str = "deepseek/deepseek-v4-flash",
    read_only_files: str = "",
    timeout: int = 120,
) -> str:
    """Run Aider AI coding assistant on specified files with given instruction.

    Aider is an AI pair programming tool that can edit multiple files,
    create new files, and make code changes autonomously.

    Args:
        instruction: The task description for Aider (what to do)
        files: Comma-separated list of file paths to edit
        model: Model name (default: deepseek/deepseek-v4-flash)
        read_only_files: Comma-separated list of read-only context files
        timeout: Execution timeout in seconds (default: 120)

    Returns:
        JSON string with stdout, stderr, and exit code
    """
    import subprocess
    import tempfile
    import os

    # Write instruction to temp file (avoids Windows quoting hell)
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
    tmp.write(instruction)
    tmp_path = tmp.name
    tmp.close()

    try:
        # Build command
        venv_aider = os.path.join(os.path.dirname(sys.executable), 'aider.exe')
        if not os.path.exists(venv_aider):
            venv_aider = 'aider'

        cmd = [
            venv_aider,
            '--model', model,
            '--message-file', tmp_path,
            '--yes',
            '--no-stream',
            '--no-git',
            '--no-show-model-warnings',
        ]

        if files and files.strip():
            for f in [x.strip() for x in files.split(',') if x.strip()]:
                cmd.extend(['--file', f])

        if read_only_files and read_only_files.strip():
            for f in [x.strip() for x in read_only_files.split(',') if x.strip()]:
                cmd.extend(['--read', f])

        logger.debug(f"Running Aider: {' '.join(cmd)}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        result = {
            "stdout": stdout.decode('utf-8', errors='replace'),
            "stderr": stderr.decode('utf-8', errors='replace'),
            "returncode": proc.returncode,
        }

        return json.dumps(result, ensure_ascii=False)

    except asyncio.TimeoutError:
        return json.dumps({"error": f"Aider timed out after {timeout}s"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


TOOL_DEFINITIONS = [
    ("ping", ping, "Simple ping/pong health check. Returns pong with current timestamp.", {
        "type": "object",
        "properties": {},
        "required": [],
    }),
    ("exec_python", exec_python, "Execute arbitrary Python code for quick testing and debugging. "
     "Pass code as: -c \"print('hello')\", or a .py filename, or raw code string.", {
        "type": "object",
        "properties": {
            "parameter": {
                "type": "string",
                "description": "Code to execute: -c \"code\" for inline, .py filename, or raw code"
            },
            "timeout": {
                "type": "integer",
                "description": "Execution timeout in seconds (default: 30)",
                "default": 30
            }
        },
        "required": ["parameter"],
    }),
    ("exec_shell", exec_shell, "Execute arbitrary shell command on Windows 10 (cmd.exe /c). "
     "⚠️ Full shell access. Supports pipes, redirects, batch commands.", {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command (e.g., 'dir /b', 'ipconfig', 'type file.txt')"
            },
            "timeout": {
                "type": "integer",
                "description": "Execution timeout in seconds (default: 30)",
                "default": 30
            }
        },
        "required": ["command"],
    }),
    ("aider_run", aider_run, "Run Aider AI coding assistant to edit/create files. Pass instruction + comma-separated file paths.", {
        "type": "object",
        "properties": {
            "instruction": {"type": "string", "description": "Task description for Aider (what code changes to make)"},
            "files": {"type": "string", "description": "Comma-separated file paths to edit (e.g., 'builtin_tools/fs_tools.py')"},
            "model": {"type": "string", "description": "Model name (default: deepseek/deepseek-v4-flash)"},
            "read_only_files": {"type": "string", "description": "Comma-separated read-only context file paths"},
            "timeout": {"type": "integer", "description": "Execution timeout in seconds (default: 120)"},
        },
        "required": ["instruction", "files"],
    }),
]



def register_all(registry):
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} additional tools")
