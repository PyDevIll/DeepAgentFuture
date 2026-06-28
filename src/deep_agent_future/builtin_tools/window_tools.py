"""Window management tools for MASTERMIND v2 using Windows UI Automation.

Provides:
  - window_list: enumerate open windows (handle, title, process, rect)
  - window_get_content: read all text from a window via UI Automation
  - window_click: click a UI element by name/type/path
  - window_send_keys: send keystrokes to a window
  - window_screenshot: capture a screenshot of a window (optional)

Requires:
  pip install uiautomation pygetwindow pyautogui Pillow
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from loguru import logger

try:
    import uiautomation as auto
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

try:
    import pygetwindow as gw
    HAS_PYGW = True
except ImportError:
    HAS_PYGW = False

try:
    import pyautogui
    HAS_PYAUTO = True
except ImportError:
    HAS_PYAUTO = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ──────────────────────────────────────────────────────────────────────────────
# Helper: get a window by handle or title
# ──────────────────────────────────────────────────────────────────────────────

def _find_window(identifier: str | int) -> auto.WindowControl | None:
    """
    Find a UI Automation window by handle (int) or title substring (str).
    Returns a WindowControl or None.
    """
    if not HAS_UIA:
        return None
    if isinstance(identifier, int):
        # handle
        try:
            return auto.WindowControl(handle=identifier)
        except Exception:
            return None
    # string: search by title (case-insensitive substring)
    try:
        # get all top-level windows
        desktop = auto.GetRootControl()
        windows = desktop.GetChildren()
        for w in windows:
            if w.ControlType == auto.ControlType.WindowControl:
                title = w.Name or ""
                if identifier.lower() in title.lower():
                    return w
    except Exception:
        pass
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tool: window_list
# ──────────────────────────────────────────────────────────────────────────────

async def window_list(
    include_hidden: bool = False,
    max_windows: int = 50,
) -> str:
    """
    List all top-level windows with handle, title, process ID, and rectangle.

    Args:
        include_hidden: Include windows that are not visible.
        max_windows: Maximum number of windows to return (default 50).

    Returns:
        JSON string with list of window objects, or error message.
    """
    if not HAS_PYGW:
        return "Error: pygetwindow not installed. Run: pip install pygetwindow"

    try:
        windows = gw.getAllWindows()
        if not include_hidden:
            windows = [w for w in windows if w.visible]
        windows = windows[:max_windows]

        result = []
        for w in windows:
            result.append({
                "handle": w._hWnd,
                "title": w.title,
                "left": w.left,
                "top": w.top,
                "width": w.width,
                "height": w.height,
                "visible": w.visible,
                "isMinimized": w.isMinimized,
                "isMaximized": w.isMaximized,
            })
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"window_list error: {e}")
        return f"Error listing windows: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Tool: window_get_content
# ──────────────────────────────────────────────────────────────────────────────

async def window_get_content(
    window_identifier: str | int,
    max_depth: int = 3,
    include_children: bool = True,
) -> str:
    """
    Extract all text content from a window using UI Automation.

    Args:
        window_identifier: Window handle (int) or title substring (str).
        max_depth: How deep to traverse the UI tree (default 3).
        include_children: If True, recurse into child elements.

    Returns:
        JSON string with window info and content tree, or error message.
    """
    if not HAS_UIA:
        return "Error: uiautomation not installed. Run: pip install uiautomation"

    win = _find_window(window_identifier)
    if win is None:
        return f"Error: window not found for identifier: {window_identifier}"

    def _get_control_text(ctrl: auto.Control) -> str:
        """Extract the best available text from a control."""
        # 1) Try ValuePattern (for edit controls, etc.)
        try:
            val_pattern = ctrl.GetPattern(auto.ValueControlPattern)
            if val_pattern:
                value = val_pattern.CurrentValue
                if value:
                    return value
        except Exception:
            pass

        # 2) Try TextPattern (for static text, document controls)
        try:
            text_pattern = ctrl.GetPattern(auto.TextControlPattern)
            if text_pattern:
                doc = text_pattern.CurrentDocument
                if doc:
                    return doc
        except Exception:
            pass

        # 3) Fallback to Name
        return ctrl.Name or ""

    def extract_element(ctrl: auto.Control, depth: int) -> dict:
        if depth > max_depth:
            return {"type": "truncated", "depth": depth}

        info = {
            "control_type": str(ctrl.ControlType),
            "name": ctrl.Name or "",
            "automation_id": ctrl.AutomationId or "",
            "class_name": ctrl.ClassName or "",
            "text": _get_control_text(ctrl),   # <-- fixed
        }

        if include_children and depth < max_depth:
            children = []
            for child in ctrl.GetChildren():
                children.append(extract_element(child, depth + 1))
            if children:
                info["children"] = children

        return info

    try:
        root_info = extract_element(win, 0)
        # Add window metadata
        root_info["handle"] = win.NativeWindowHandle
        root_info["title"] = win.Name
        root_info["class"] = win.ClassName
        return json.dumps(root_info, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"window_get_content error: {e}")
        return f"Error extracting content: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Tool: window_click
# ──────────────────────────────────────────────────────────────────────────────

async def window_click(
    window_identifier: str | int,
    target_name: str,
    target_type: str = "Button",
) -> str:
    """
    Click a UI element (button, checkbox, etc.) inside a window.

    Args:
        window_identifier: Window handle or title substring.
        target_name: Name of the element to click (case-insensitive substring).
        target_type: Control type (e.g., "Button", "CheckBox", "MenuItem").

    Returns:
        Success or error message.
    """
    if not HAS_UIA:
        return "Error: uiautomation not installed."

    win = _find_window(window_identifier)
    if win is None:
        return f"Error: window not found for identifier: {window_identifier}"

    try:
        # Convert target_type to ControlType enum
        control_type_map = {
            "Button": auto.ControlType.ButtonControl,
            "CheckBox": auto.ControlType.CheckBoxControl,
            "MenuItem": auto.ControlType.MenuItemControl,
            "RadioButton": auto.ControlType.RadioButtonControl,
            "Link": auto.ControlType.HyperlinkControl,
            "TabItem": auto.ControlType.TabItemControl,
        }
        ctype = control_type_map.get(target_type, auto.ControlType.ButtonControl)

        # Find the element
        element = win.GetFirstChildControl(
            control_type=ctype,
            name=target_name,
            search_depth=5,
        )
        if element is None:
            return f"Error: element '{target_name}' (type {target_type}) not found."

        # Perform click
        element.Click()
        return f"Clicked '{target_name}' successfully."
    except Exception as e:
        logger.error(f"window_click error: {e}")
        return f"Error clicking element: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Tool: window_send_keys
# ──────────────────────────────────────────────────────────────────────────────

async def window_send_keys(
    window_identifier: str | int,
    keys: str,
    set_focus: bool = True,
) -> str:
    """
    Send keyboard input to a window.

    Args:
        window_identifier: Window handle or title substring.
        keys: Keys to send (supports special keys like {ENTER}, {CTRL}, etc.)
             See pyautogui documentation for syntax.
        set_focus: Bring window to foreground before sending.

    Returns:
        Success or error message.
    """
    if not HAS_PYAUTO:
        return "Error: pyautogui not installed. Run: pip install pyautogui"

    win = _find_window(window_identifier)
    if win is None:
        return f"Error: window not found for identifier: {window_identifier}"

    try:
        if set_focus:
            win.SetFocus()
            # wait a bit for focus change
            import asyncio
            await asyncio.sleep(0.2)

        pyautogui.write(keys)
        return f"Sent keys: {keys}"
    except Exception as e:
        logger.error(f"window_send_keys error: {e}")
        return f"Error sending keys: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Tool: window_screenshot
# ──────────────────────────────────────────────────────────────────────────────

async def window_screenshot(
    window_identifier: str | int,
    output_path: Optional[str] = None,
) -> str:
    """
    Capture a screenshot of a window and save it to a file.

    Args:
        window_identifier: Window handle or title substring.
        output_path: Optional absolute path to save the image.
                    If omitted, saves to data/screenshots/ with a timestamp.

    Returns:
        Path to the saved image, or error message.
    """
    if not HAS_PYAUTO:
        return "Error: pyautogui not installed."
    if not HAS_PIL:
        return "Error: Pillow not installed."

    win = _find_window(window_identifier)
    if win is None:
        return f"Error: window not found for identifier: {window_identifier}"

    try:
        # Get window rectangle via pygetwindow (if available) or UIA
        if HAS_PYGW:
            # find pygetwindow window by handle
            gw_win = None
            for w in gw.getAllWindows():
                if w._hWnd == win.NativeWindowHandle:
                    gw_win = w
                    break
            if gw_win:
                left, top, right, bottom = gw_win.left, gw_win.top, gw_win.right, gw_win.bottom
            else:
                # fallback: use UIA bounding rectangle
                rect = win.BoundingRectangle
                left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
        else:
            rect = win.BoundingRectangle
            left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom

        # Take screenshot
        screenshot = pyautogui.screenshot(region=(left, top, right - left, bottom - top))

        # Determine output path
        if output_path:
            out = Path(output_path).resolve()
        else:
            base = Path(__file__).resolve().parent.parent / "data" / "screenshots"
            base.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = base / f"screenshot_{timestamp}.png"

        screenshot.save(str(out))
        return f"Screenshot saved to: {out}"
    except Exception as e:
        logger.error(f"window_screenshot error: {e}")
        return f"Error capturing screenshot: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ──────────────────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[tuple[str, Any, str, dict[str, Any]]] = [
    (
        "window_list",
        window_list,
        "List all visible top-level windows with handles, titles, and sizes.",
        {
            "type": "object",
            "properties": {
                "include_hidden": {
                    "type": "boolean",
                    "description": "Include hidden/minimized windows (default false)",
                },
                "max_windows": {
                    "type": "integer",
                    "description": "Maximum number of windows to return (default 50)",
                },
            },
        },
    ),
    (
        "window_get_content",
        window_get_content,
        "Extract UI Automation content tree from a window. Returns structured JSON.",
        {
            "type": "object",
            "properties": {
                "window_identifier": {
                    "type": ["string", "integer"],
                    "description": "Window handle (integer) or title substring (string)",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum traversal depth (default 3)",
                },
                "include_children": {
                    "type": "boolean",
                    "description": "Recurse into child elements (default true)",
                },
            },
            "required": ["window_identifier"],
        },
    ),
    (
        "window_click",
        window_click,
        "Click a UI element (button, checkbox, etc.) inside a window.",
        {
            "type": "object",
            "properties": {
                "window_identifier": {
                    "type": ["string", "integer"],
                    "description": "Window handle or title substring",
                },
                "target_name": {
                    "type": "string",
                    "description": "Name of the element to click (case-insensitive substring)",
                },
                "target_type": {
                    "type": "string",
                    "description": "Control type: Button, CheckBox, MenuItem, etc. (default Button)",
                },
            },
            "required": ["window_identifier", "target_name"],
        },
    ),
    (
        "window_send_keys",
        window_send_keys,
        "Send keyboard input to a window (sets focus first by default).",
        {
            "type": "object",
            "properties": {
                "window_identifier": {
                    "type": ["string", "integer"],
                    "description": "Window handle or title substring",
                },
                "keys": {
                    "type": "string",
                    "description": "Keys to send (supports {ENTER}, {CTRL}c, etc.)",
                },
                "set_focus": {
                    "type": "boolean",
                    "description": "Bring window to foreground before sending (default true)",
                },
            },
            "required": ["window_identifier", "keys"],
        },
    ),
    (
        "window_screenshot",
        window_screenshot,
        "Capture a screenshot of a window and save to file.",
        {
            "type": "object",
            "properties": {
                "window_identifier": {
                    "type": ["string", "integer"],
                    "description": "Window handle or title substring",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional absolute path to save the image",
                },
            },
            "required": ["window_identifier"],
        },
    ),
]


def register_all(registry) -> None:
    """Register all window tools with the given registry."""
    for name, func, desc, params in TOOL_DEFINITIONS:
        registry.register_function(func, name, desc, params)
    logger.info(f"Registered {len(TOOL_DEFINITIONS)} window management tools")
    
