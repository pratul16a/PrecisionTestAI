"""
prompt_utils.py — Prompt Builder

Builds the tool decomposition prompt for LLM Call #1.
Takes user's NL query + 20+ tool schemas → prompt that produces
JSON array of {tool, args} calls.
"""


def build_tool_prompt(query: str, tools: list[dict]) -> str:
    """
    Build prompt for LLM Call #1: Tool Decomposition.
    
    Args:
        query: User's natural language prompt
        tools: List of tool schemas [{name, description, inputSchema}, ...]
    
    Returns:
        Complete prompt string for the LLM
    """
    # Format tool descriptions
    tool_descriptions = []
    for tool in tools:
        schema_str = _format_schema(tool.get("inputSchema", {}))
        tool_descriptions.append(
            f"  - {tool['name']}, {tool.get('description', '')}, {schema_str}"
        )
    tools_text = "\n".join(tool_descriptions)

    prompt = f"""You are a helpful assistant with access to these tools:
{tools_text}

Rules:
• field_name → exact name of the field from user's text
• field_type → element type (input, button, link, text, tab)
• field_description → VERBATIM text from user prompt
• Split compound statements into atomic actions
• Add close_browser at the end
• Each tool call must be a JSON object with "tool" and "args" keys

User's Question: {query}

Respond with ONLY a JSON array of tool calls. No explanation.
Example format:
```json
[
  {{"tool": "launch_browser", "args": {{"url": "https://example.com"}}}},
  {{"tool": "click", "args": {{"field_name": "Submit", "field_type": "button"}}}},
  {{"tool": "close_browser", "args": {{}}}}
]
```"""
    return prompt


def _format_schema(schema: dict) -> str:
    """Format inputSchema into a concise string representation."""
    if not schema:
        return "{}"
    
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    
    parts = []
    for key, val in properties.items():
        type_str = val.get("type", "string")
        req_marker = "*" if key in required else ""
        parts.append(f"{key}{req_marker}: {type_str}")
    
    return "{" + ", ".join(parts) + "}"


# Tool registry — defines all available tools and their schemas
TOOL_REGISTRY = [
    {
        "name": "launch_browser",
        "description": "Launch a web browser and navigate to URL",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "navigate_to_url",
        "description": "Navigate to a different URL in current browser",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to navigate to"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "click",
        "description": "Click on element",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Name/text of element to click"},
                "field_type": {"type": "string", "description": "Element type: button, link, tab, option, text"},
            },
            "required": ["field_name"],
        },
    },
    {
        "name": "enter_text",
        "description": "Enter text into input field",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Name/label of input field"},
                "textToEnter": {"type": "string", "description": "Text to type"},
            },
            "required": ["field_name", "textToEnter"],
        },
    },
    {
        "name": "select_dropdown",
        "description": "Select option from dropdown",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Dropdown field name"},
                "value": {"type": "string", "description": "Option to select"},
            },
            "required": ["field_name", "value"],
        },
    },
    {
        "name": "assert_element_visible",
        "description": "Assert element is visible on page",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expected_field_name": {"type": "string", "description": "Text/name expected to be visible"},
            },
            "required": ["expected_field_name"],
        },
    },
    {
        "name": "assert_text_equals",
        "description": "Assert element text equals expected value",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Element to check"},
                "expected_text": {"type": "string", "description": "Expected text value"},
            },
            "required": ["field_name", "expected_text"],
        },
    },
    {
        "name": "hover",
        "description": "Hover over element",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Element to hover over"},
            },
            "required": ["field_name"],
        },
    },
    {
        "name": "double_click",
        "description": "Double click on element",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Element to double click"},
            },
            "required": ["field_name"],
        },
    },
    {
        "name": "right_click",
        "description": "Right click on element",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Element to right click"},
            },
            "required": ["field_name"],
        },
    },
    {
        "name": "press_key",
        "description": "Press keyboard key",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to press (Enter, Tab, Escape, etc.)"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll page or element",
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "up or down"},
                "pixels": {"type": "integer", "description": "Pixels to scroll"},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for specified seconds",
        "inputSchema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Seconds to wait"},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Take screenshot of current page",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Screenshot label"},
            },
        },
    },
    {
        "name": "switch_tab",
        "description": "Switch to browser tab by index",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tab_index": {"type": "integer", "description": "Tab index (0-based)"},
            },
            "required": ["tab_index"],
        },
    },
    {
        "name": "upload_file",
        "description": "Upload file to file input",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "File input field"},
                "file_path": {"type": "string", "description": "Path to file"},
            },
            "required": ["field_name", "file_path"],
        },
    },
    {
        "name": "clear_field",
        "description": "Clear text from input field",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Field to clear"},
            },
            "required": ["field_name"],
        },
    },
    {
        "name": "checkbox",
        "description": "Check or uncheck a checkbox",
        "inputSchema": {
            "type": "object",
            "properties": {
                "field_name": {"type": "string", "description": "Checkbox label"},
                "state": {"type": "string", "description": "check or uncheck"},
            },
            "required": ["field_name", "state"],
        },
    },
    {
        "name": "drag_and_drop",
        "description": "Drag element to target",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source element"},
                "target": {"type": "string", "description": "Target element"},
            },
            "required": ["source", "target"],
        },
    },
    {
        "name": "close_browser",
        "description": "Close the browser",
        "inputSchema": {"type": "object", "properties": {}},
    },
]
