"""
llm_api.py — LLM Caller

Replaces JPMC LLMSuite + Azure OpenAI GPT-4.1 with Anthropic Claude.
Handles all 4 LLM calls:
  #1 Tool Decomposition
  #2 BDD Feature File Generation
  #3 Intent Extraction
  #4 Locator Generation (+ #4b Retry)
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import json
import re
import os
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY", ""),
    base_url="https://openrouter.ai/api/v1",
)

DEFAULT_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")


def call_llm(prompt: str, model: str = DEFAULT_MODEL, max_tokens: int = 4096) -> str:
    """Generic LLM call via OpenRouter. Returns raw text response."""
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


def format_llm_response(raw_response: str) -> list[dict]:
    """Parse ```json``` blocks from LLM response into list of tool calls."""
    # Try to find JSON block in markdown fences
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw_response, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))

    # Try raw JSON array
    array_match = re.search(r"\[.*\]", raw_response, re.DOTALL)
    if array_match:
        return json.loads(array_match.group(0))

    raise ValueError(f"Could not parse JSON from LLM response: {raw_response[:200]}")


def llm_tool_call(session, tool_list: list[dict], config: dict) -> list[dict]:
    """
    Phase 4 — Sequential Tool Execution Loop.
    For each tool_call in tool_list:
      - Inject run_id, seal_id, project_name, component_name
      - Call session handler (local Playwright)
      - Parse response → {status, featurestep, screenshot}
      - If status == "failed" → STOP
      - Append featurestep to feature_steps[]
    Returns collected feature_steps.
    """
    feature_steps = []

    for i, tool_call in enumerate(tool_list):
        tool_name = tool_call.get("tool")
        args = tool_call.get("args", {})

        # Inject config into args
        args["run_id"] = config["run_id"]
        args["seal_id"] = config["seal_id"]
        args["project_name"] = config["project_name"]
        args["component_name"] = config["component_name"]

        print(f"  [{i+1}/{len(tool_list)}] Executing: {tool_name}({json.dumps(args, default=str)[:100]}...)")

        # Call the tool handler
        result = session.call_tool(tool_name, args)
        status = result.get("status", "failed")
        featurestep = result.get("featurestep", "")
        screenshot = result.get("screenshot", "")

        if featurestep:
            feature_steps.append(featurestep)

        # Save screenshot if present
        if screenshot and config.get("screenshots_dir"):
            os.makedirs(config["screenshots_dir"], exist_ok=True)
            ss_path = os.path.join(config["screenshots_dir"], f"step_{i+1}_{tool_name}.png")
            import base64
            with open(ss_path, "wb") as f:
                f.write(base64.b64decode(screenshot))

        if status == "failed":
            print(f"  [FAIL] Tool '{tool_name}' FAILED. Stopping execution.")
            break
        else:
            print(f"  [PASS] {tool_name} succeeded")

    return feature_steps


def generate_feature_file_from_feature_steps(feature_steps: list[str], config: dict) -> str:
    """
    LLM Call #2 — BDD Feature File Generation.
    Takes collected feature_steps and asks LLM to produce Gherkin .feature file.
    """
    steps_text = "\n".join(feature_steps)

    prompt = f"""You are a BDD test automation expert. Convert the following executed test steps 
into a proper Gherkin .feature file with Scenario Outline and Examples table.

Executed steps:
{steps_text}

Application: {config.get('app_name', 'unknown')}
Project: {config.get('project_name', 'unknown')}

Rules:
- Use proper Feature, Scenario Outline, Given/When/Then/And syntax
- Parameterize values into Examples table where appropriate
- Add meaningful feature and scenario descriptions
- Include tags like @automated @{config.get('app_name', 'app')}

Return ONLY the .feature file content, no explanation."""

    raw = call_llm(prompt)

    # Write to feature file
    feature_path = config.get("feature_file", "output.feature")
    with open(feature_path, "w", encoding="utf-8") as f:
        f.write(raw)

    return raw
