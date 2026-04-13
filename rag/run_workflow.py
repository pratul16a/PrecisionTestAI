"""
Bridge: RAG → skill_agent.

Resolves a natural-language prompt to a workflow, flattens the steps into
an instruction sentence, and runs it through skill_agent.run_test.

Usage:  python rag/run_workflow.py "check feedback for 902128"
"""
from __future__ import annotations
import os
import sys
import json
import asyncio

# allow importing siblings
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rag"))

from rag import resolve  # noqa: E402
from skill_agent import run_test  # noqa: E402

BASE_URL = os.environ.get("ICE_URL", "http://localhost:3000")


def step_to_sentence(step: dict) -> str | None:
    if "navigate" in step:
        page = step["navigate"].get("page")
        if page and page.lower() != "dashboard":
            return f'click on "{page}" in the sidebar'
        return None
    if "action" in step and step["action"] == "search":
        return 'click on "Search" button'
    if "enter" in step:
        e = step["enter"]
        return f'enter "{e["value"]}" in "{e["field"]}"'
    if "click" in step:
        c = step["click"]
        return f'click on "{c["element"]}"'
    if "select" in step:
        s = step["select"]
        return f'select "{s["value"]}" in "{s["field"]}"'
    if "verify" in step:
        v = step["verify"]
        if "visible" in v:
            return f'verify "{v["visible"]}" is visible'
        if "one_of" in v:
            first = v["one_of"][0]
            if "visible" in first:
                return f'verify "{first["visible"]}" is visible'
    return None


def workflow_to_prompt(resolved: dict) -> str:
    parts = [f"Launch {BASE_URL}"]
    for step in resolved["steps"]:
        s = step_to_sentence(step)
        if s:
            parts.append(s)
    parts.append("close the browser")
    return ", then ".join(parts)


async def main():
    if len(sys.argv) < 2:
        print('Usage: python rag/run_workflow.py "<prompt>"')
        sys.exit(1)
    user_prompt = " ".join(sys.argv[1:])

    resolved = resolve(user_prompt)
    print(f"Selected workflow : {resolved['selected_workflow']}  (score={resolved['score']})")
    print(f"Params            : {resolved['params_used']}")

    instruction = workflow_to_prompt(resolved)
    print(f"\nInstruction sent to skill_agent:\n  {instruction}\n")

    result = await run_test(instruction)
    for step in result.get("results", []):
        if step.get("screenshot"):
            step["screenshot"] = "[base64 omitted]"
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
