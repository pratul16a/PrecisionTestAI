"""
app.py - FastAPI Backend
Serves the conversation UI and handles test execution requests.
"""
import sys
import asyncio
import logging
import json
from pathlib import Path

# Force UTF-8 on Windows console so unicode chars don't crash
import os
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Windows: use ProactorEventLoop so Playwright subprocess spawning works
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from orchestrator import run_playwrightmethod

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

app = FastAPI(title="PrecisionTest AI", version="1.0.0")

# Serve static files
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the conversation UI."""
    ui_path = Path(__file__).parent / "templates" / "conversation_ui.html"
    return HTMLResponse(ui_path.read_text())


@app.post("/run_playwright_codegen")
async def run_playwright_codegen(request: Request):
    """
    Main endpoint. Receives user prompt, runs full pipeline.
    POST {prompt: "..."} → orchestrator → results
    """
    body = await request.json()
    prompt = body.get("prompt", "")

    if not prompt:
        return JSONResponse({"error": "No prompt provided"}, status_code=400)

    try:
        result = await run_playwrightmethod(prompt)
        # Strip screenshots from response to keep it lean (they're in the HTML report)
        for step in result.get("results", []):
            if step.get("screenshot"):
                step["screenshot"] = f"[base64 screenshot - see HTML report]"
        return JSONResponse(result)
    except Exception as e:
        logging.error(f"Pipeline error: {e}", exc_info=True)
        return JSONResponse({"error": str(e), "status": "error"}, status_code=500)


@app.get("/reports/{run_id}")
async def get_report(run_id: str):
    """Serve HTML report for a run."""
    artifacts = Path(__file__).parent / "artifacts"
    # exact match first, then prefix match (folders are <run_id>_<timestamp>)
    candidates = []
    exact = artifacts / run_id / "scenario_steps_status.html"
    if exact.exists():
        candidates.append(exact)
    else:
        candidates = sorted(artifacts.glob(f"{run_id}*/scenario_steps_status.html"), reverse=True)
    if candidates:
        return HTMLResponse(candidates[0].read_text(encoding="utf-8"))
    return JSONResponse({"error": "Report not found"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=1113)
