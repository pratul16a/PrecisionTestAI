"""
skill_agent.py - Skill/Agent Version for Copilot Integration
Single callable entry point -- no MCP server, no UI needed.
Copilot calls: run_test(prompt) -> gets back structured results.

Usage:
    from skill_agent import run_test
    result = await run_test("Launch browser, go to example.com, verify title visible")
    print(result["status"])       # "completed"
    print(result["passed"])       # 3
    print(result["feature_file"]) # path to .feature file
    print(result["html_report"])  # path to HTML report
"""
import asyncio
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator import run_playwright_pipeline


async def run_test(prompt: str, headless: bool = False) -> dict:
    """
    Single entry point for Copilot/agent integration.
    
    Args:
        prompt: Natural language test description
        headless: Run browser in headless mode (default False)
    
    Returns:
        dict with: status, run_id, passed, failed, total_steps,
                   feature_steps, feature_file, html_report, results
    """
    if headless:
        os.environ["PLAYWRIGHT_HEADLESS"] = "1"

    return await run_playwright_pipeline(prompt)


if __name__ == "__main__":
    import json
    if len(sys.argv) < 2:
        print('Usage: python skill_agent.py "your test prompt"')
        sys.exit(1)
    prompt = " ".join(sys.argv[1:])
    result = asyncio.run(run_test(prompt))
    # Strip screenshots for terminal readability
    for step in result.get("results", []):
        if step.get("screenshot"):
            step["screenshot"] = "[base64 omitted]"
    print(json.dumps(result, indent=2, default=str))


def run_test_sync(prompt: str, headless: bool = False) -> dict:
    """Synchronous wrapper for environments without async support."""
    return asyncio.run(run_test(prompt, headless))


# CLI usage
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="PrecisionTest AI - Skill Agent")
    parser.add_argument("prompt", help="Natural language test prompt")
    parser.add_argument("--headless", action="store_true", help="Run headless")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = run_test_sync(args.prompt, args.headless)

    if args.json:
        # Strip screenshots for clean output
        for step in result.get("results", []):
            step.pop("screenshot", None)
        print(json.dumps(result, indent=2))
    else:
        status_icon = "✅" if result["failed"] == 0 else "❌"
        print(f"\n{status_icon} PrecisionTest AI - Run Complete")
        print(f"   Run ID:  {result['run_id']}")
        print(f"   App:     {result['app_name']}")
        print(f"   Passed:  {result['passed']}/{result['total_steps']}")
        print(f"   Failed:  {result['failed']}")
        print(f"\n   Feature: {result['feature_file']}")
        print(f"   Report:  {result['html_report']}")
        print()
        for step in result.get("results", []):
            icon = "[PASS]" if step["status"] == "success" else "[FAIL]"
            print(f"   {icon} {step.get('featurestep', step['tool'])}")
