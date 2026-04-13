"""
config_utils.py — Config/App Detection

Scans user prompts for known URLs/app names and builds
run-specific configuration with paths for artifacts, features, etc.
"""
import os
import re
import json
import uuid
from datetime import datetime
from typing import Optional

# Known app URL patterns → app name mapping
APP_PATTERNS = {
    "ice": [r"ice\.test", r"ice\.uat", r"ice\.prod"],
    "rdp": [r"rdpdata", r"rdp\."],
    "murex": [r"murex", r"mx\."],
    "calypso": [r"calypso"],
    "summit": [r"summit"],
}

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARTIFACTS_DIR = os.path.join(BASE_DIR, "artifacts")
FEATURES_DIR = os.path.join(BASE_DIR, "features")
CACHE_DIR = os.path.join(BASE_DIR, "locator_cache")


def extract_app_name_from_query(prompt: str) -> Optional[str]:
    """Scan prompt for known URLs/app names and return matched app."""
    prompt_lower = prompt.lower()
    for app_name, patterns in APP_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, prompt_lower):
                return app_name
    return "generic"


def build_config(app_name: str, run_id: str) -> dict:
    """Build run-specific config with all necessary paths."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(ARTIFACTS_DIR, f"{run_id}_{timestamp}")

    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(FEATURES_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)

    return {
        "app_name": app_name,
        "run_id": run_id,
        "run_dir": run_dir,
        "json_file": os.path.join(run_dir, "scenario_steps_status.json"),
        "html_report": os.path.join(run_dir, "scenario_steps_status.html"),
        "feature_file": os.path.join(FEATURES_DIR, f"{run_id}.feature"),
        "screenshots_dir": os.path.join(run_dir, "screenshots"),
        "cache_dir": CACHE_DIR,
        "seal_id": f"SEAL-{app_name.upper()}-001",
        "project_name": f"PrecisionTest-{app_name.upper()}",
        "component_name": f"{app_name}-ui-tests",
    }


def generate_run_id() -> str:
    return str(uuid.uuid4())[:8]
