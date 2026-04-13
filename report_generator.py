"""
report_generator.py - Phase 8: Reports & Artifacts
Generates:
1. scenario_steps_status.json - pass/fail per step with screenshots
2. scenario_steps_status.html - visual report with green/red dots
3. .feature file (handled by llm_api)
"""
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_json_report(results: list[dict], config: dict) -> str:
    """Generate JSON report with step statuses and screenshots."""
    report = {
        "run_id": config["run_id"],
        "app_name": config["app_name"],
        "project_name": config["project_name"],
        "timestamp": datetime.now().isoformat(),
        "total_steps": len(results),
        "passed": sum(1 for r in results if r.get("status") == "success"),
        "failed": sum(1 for r in results if r.get("status") == "failed"),
        "steps": results,
    }

    path = config["json_file"]
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    logger.info(f"JSON report: {path}")
    return path


def generate_html_report(results: list[dict], config: dict) -> str:
    """Generate visual HTML report with green/red status dots and screenshots."""
    steps_html = ""
    for i, step in enumerate(results):
        status = step.get("status", "unknown")
        color = "#4CAF50" if status == "success" else "#f44336" if status == "failed" else "#FF9800"
        dot = f'<span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:{color};margin-right:8px;"></span>'

        screenshot_html = ""
        if step.get("screenshot"):
            screenshot_html = f'''
            <details style="margin-top:8px;">
                <summary style="cursor:pointer;color:#888;">Screenshot</summary>
                <img src="data:image/png;base64,{step["screenshot"]}" 
                     style="max-width:100%;border:1px solid #333;border-radius:4px;margin-top:4px;" />
            </details>'''

        xpath_html = ""
        if step.get("xpath"):
            xpath_html = f'<div style="font-size:11px;color:#888;margin-top:4px;">XPath: <code>{step["xpath"]}</code></div>'

        error_html = ""
        if step.get("error"):
            error_html = f'<div style="color:#f44336;font-size:12px;margin-top:4px;">Error: {step["error"]}</div>'

        steps_html += f'''
        <div style="padding:12px 16px;border-bottom:1px solid #333;background:{"#1a2e1a" if status == "success" else "#2e1a1a" if status == "failed" else "#2e2a1a"};">
            <div style="display:flex;align-items:center;">
                {dot}
                <strong>Step {i+1}:</strong>&nbsp;{step.get("tool", "")}
            </div>
            <div style="margin-left:20px;margin-top:4px;color:#ccc;">
                {step.get("featurestep", "")}
            </div>
            {xpath_html}
            {error_html}
            {screenshot_html}
        </div>'''

    passed = sum(1 for r in results if r.get("status") == "success")
    failed = sum(1 for r in results if r.get("status") == "failed")
    total = len(results)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>PrecisionTest AI - {config["run_id"]}</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }}
        .header {{ background: #16213e; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .stats {{ display: flex; gap: 20px; margin-top: 12px; }}
        .stat {{ padding: 8px 16px; border-radius: 4px; font-weight: bold; }}
        .steps {{ background: #16213e; border-radius: 8px; overflow: hidden; }}
        code {{ background: #333; padding: 2px 6px; border-radius: 3px; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1 style="margin:0;">PrecisionTest AI Report</h1>
        <div style="color:#888;margin-top:4px;">
            Run: {config["run_id"]} | App: {config["app_name"]} | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        </div>
        <div class="stats">
            <div class="stat" style="background:#1a2e1a;color:#4CAF50;">✓ {passed} Passed</div>
            <div class="stat" style="background:#2e1a1a;color:#f44336;">✗ {failed} Failed</div>
            <div class="stat" style="background:#1a1a2e;color:#64B5F6;">Total: {total}</div>
        </div>
    </div>
    <div class="steps">
        {steps_html}
    </div>
</body>
</html>"""

    path = config["html_report"]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)

    logger.info(f"HTML report: {path}")
    return path
