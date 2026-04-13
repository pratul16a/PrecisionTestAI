"""
bdd_parser.py — BDD Parser

Extracts Gherkin .feature content from LLM response and writes to file.
Also extracts cucumber-compatible file references.
"""
import re
import os


def extract_gherkin_block(llm_response: str) -> str:
    """Extract Gherkin feature content from LLM response."""
    # Try markdown fenced block first
    match = re.search(r"```(?:gherkin|feature)?\s*(Feature:.*?)```", llm_response, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Try raw Feature: block
    match = re.search(r"(Feature:.*)", llm_response, re.DOTALL)
    if match:
        return match.group(1).strip()

    return llm_response.strip()


def write_feature_file(content: str, path: str) -> str:
    """Write .feature content to file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def extract_cucumber_files(feature_dir: str) -> list[str]:
    """List all .feature files in directory."""
    if not os.path.exists(feature_dir):
        return []
    return [
        os.path.join(feature_dir, f)
        for f in os.listdir(feature_dir)
        if f.endswith(".feature")
    ]
