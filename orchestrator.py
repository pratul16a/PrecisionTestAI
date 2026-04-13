"""
orchestrator.py - Main Orchestrator
Replaces playwright_custom_mcp_client.py.
Runs the full end-to-end pipeline without MCP:

Phase 1: Receive prompt from UI/API
Phase 2: Config & detect app
Phase 3: LLM Call #1 - Tool decomposition
Phase 4: Sequential tool execution
Phase 5: Element locator pipeline (inside tool handlers)
Phase 6: Action execution (inside tool handlers)
Phase 7: LLM Call #2 - BDD feature file generation
Phase 8: Reports & artifacts
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import asyncio
import json
import logging
from datetime import datetime

from client.config_utils import extract_app_name_from_query, build_config
from client.prompt_utils import build_tool_prompt
from client.llm_api import call_llm, format_llm_response, generate_feature_file_from_feature_steps
from playwright_handlers_local import execute_tool, TOOL_HANDLERS
from report_generator import generate_json_report, generate_html_report

logger = logging.getLogger(__name__)


async def run_playwright_pipeline(prompt: str) -> dict:
    """
    Full end-to-end execution pipeline.
    Takes a natural language prompt and returns test results.
    """
    logger.info(f"Starting pipeline for: {prompt[:100]}...")

    # ── Phase 2: Config & App Detection ──
    app_name = extract_app_name_from_query(prompt)
    run_id = f"{app_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    config = build_config(app_name, run_id)
    logger.info(f"App: {app_name} | Run: {config['run_id']}")

    # ── Phase 3: LLM Call #1 - Tool Decomposition ──
    tools_schema = [{"name": name, "description": (fn.__doc__ or "").strip(), "inputSchema": {}} for name, fn in TOOL_HANDLERS.items()]
    tool_prompt = build_tool_prompt(prompt, tools_schema)
    raw_response = call_llm(tool_prompt)
    tool_list = format_llm_response(raw_response)

    if not tool_list:
        return {
            "status": "error",
            "message": "LLM failed to decompose prompt into tool calls",
            "raw_response": raw_response,
        }

    logger.info(f"Decomposed into {len(tool_list)} tool calls")

    # ── Phase 4: Sequential Tool Execution ──
    results = []
    feature_steps = []

    for i, tool_call in enumerate(tool_list):
        tool_name = tool_call.get("tool", "")
        args = tool_call.get("args", {})
        args["run_id"] = config["run_id"]
        args["project_name"] = config["project_name"]
        args["component_name"] = config["component_name"]

        logger.info(f"Executing {i+1}/{len(tool_list)}: {tool_name}")

        # Phase 5+6 happen inside execute_tool for click/enter_text/assert
        result = await execute_tool(tool_name, args, config)

        status = result.get("status", "unknown")
        featurestep = result.get("featurestep", "")

        if featurestep:
            feature_steps.append(featurestep)

        results.append({
            "tool": tool_name,
            "args": {k: v for k, v in args.items() if k not in ("run_id", "project_name", "component_name")},
            "status": status,
            "featurestep": featurestep,
            "screenshot": result.get("screenshot"),
            "xpath": result.get("xpath"),
            "error": result.get("error"),
        })

        if status == "failed":
            logger.error(f"Tool {tool_name} FAILED. Stopping.")
            break

    # ── Phase 7: LLM Call #2 - BDD Feature File ──
    feature_content = ""
    if feature_steps:
        try:
            feature_content = generate_feature_file_from_feature_steps(feature_steps, config)
        except Exception as e:
            logger.error(f"BDD generation failed: {e}")

    # ── Phase 8: Reports & Artifacts ──
    json_report_path = generate_json_report(results, config)
    html_report_path = generate_html_report(results, config)

    passed = sum(1 for r in results if r.get("status") == "success")
    failed = sum(1 for r in results if r.get("status") == "failed")

    return {
        "status": "completed",
        "run_id": config["run_id"],
        "app_name": app_name,
        "total_steps": len(results),
        "passed": passed,
        "failed": failed,
        "feature_steps": feature_steps,
        "feature_file": config["feature_file"],
        "json_report": json_report_path,
        "html_report": html_report_path,
        "results": results,
    }


async def run_playwrightmethod(prompt: str) -> dict:
    """Alias matching original function name from app.py."""
    return await run_playwright_pipeline(prompt)
