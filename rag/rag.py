"""
RAG layer for PrecisionTest workflows.

Loads workflow YAMLs + glossary, resolves a natural-language prompt to a
parameterized workflow, and prints the substituted steps.

Usage:  python rag.py "check feedback for 902128"
"""
from __future__ import annotations
import os
import re
import sys
import json
import glob
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
WORKFLOWS_DIR = os.path.join(ROOT, "workflows")
GLOSSARY_PATH = os.path.join(ROOT, "glossary", "ice_glossary.yaml")


# ---------- loading ----------

def load_workflows() -> dict:
    workflows = {}
    for path in glob.glob(os.path.join(WORKFLOWS_DIR, "*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        wf["_tags_set"] = set(t.lower() for t in wf.get("tags", []))
        workflows[wf["name"]] = wf
    return workflows


def load_glossary() -> dict:
    with open(GLOSSARY_PATH, "r", encoding="utf-8") as f:
        g = yaml.safe_load(f)
    # Build alias -> canonical-term lookup
    alias_index = {}
    for term, body in g.get("terms", {}).items():
        alias_index[term.lower()] = term
        for alias in (body or {}).get("aliases", []) or []:
            alias_index[alias.lower()] = term
    g["_alias_index"] = alias_index
    return g


# ---------- resolution ----------

def resolve_terms(prompt: str, glossary: dict) -> dict:
    """Find which glossary terms appear in the prompt; return canonical names + tags."""
    text = " " + prompt.lower() + " "
    matched_terms = set()
    matched_tags = set()

    # Sort by length desc so multi-word aliases beat single-word ones
    aliases = sorted(glossary["_alias_index"].keys(), key=len, reverse=True)
    for alias in aliases:
        if re.search(r"\b" + re.escape(alias) + r"\b", text):
            canonical = glossary["_alias_index"][alias]
            matched_terms.add(canonical)
            matched_tags.add(canonical.lower())
            # remove so a shorter alias inside a longer one isn't double-counted
            text = text.replace(alias, " ")

    return {"terms": sorted(matched_terms), "tags": matched_tags}


def extract_params(prompt: str) -> dict:
    """Pull out simple param values from the prompt."""
    params = {}

    # 6-digit client SID
    sid = re.search(r"\b(\d{6})\b", prompt)
    if sid:
        params["client_id"] = sid.group(1)

    # Trade IDs like TRD-100005
    trd = re.search(r"\b(TRD-\d+)\b", prompt, re.IGNORECASE)
    if trd:
        params["trade_id"] = trd.group(1).upper()

    return params


def score_workflow(wf: dict, matched_tags: set, prompt_lower: str) -> int:
    """Higher score = better match."""
    score = 0
    for tag in wf["_tags_set"]:
        if tag in matched_tags:
            score += 3
        if tag in prompt_lower:
            score += 1
    # Bonus when workflow name tokens appear in prompt
    for token in wf["name"].split("_"):
        if token and token in prompt_lower:
            score += 2
    return score


def find_workflow(prompt: str, workflows: dict, matched_tags: set) -> tuple[str, int]:
    prompt_lower = prompt.lower()
    scored = [(name, score_workflow(wf, matched_tags, prompt_lower))
              for name, wf in workflows.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0]  # (name, score)


# ---------- substitution ----------

def substitute(obj: Any, params: dict) -> Any:
    if isinstance(obj, str):
        out = obj
        for k, v in params.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    if isinstance(obj, list):
        return [substitute(x, params) for x in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, params) for k, v in obj.items()}
    return obj


# ---------- main entry ----------

def resolve(prompt: str) -> dict:
    workflows = load_workflows()
    glossary = load_glossary()

    resolved = resolve_terms(prompt, glossary)
    params = extract_params(prompt)

    name, score = find_workflow(prompt, workflows, resolved["tags"])
    wf = workflows[name]

    # Fill in any missing required params from examples (for demo)
    filled = dict(params)
    for pname, pdef in (wf.get("params") or {}).items():
        if pname not in filled and isinstance(pdef, dict) and "example" in pdef:
            filled[pname] = pdef["example"]

    steps = substitute(wf.get("steps", []), filled)

    return {
        "prompt": prompt,
        "matched_terms": resolved["terms"],
        "matched_tags": sorted(resolved["tags"]),
        "extracted_params": params,
        "selected_workflow": name,
        "score": score,
        "params_used": filled,
        "steps": steps,
    }


def main():
    if len(sys.argv) < 2:
        # Run the demo prompts
        prompts = [
            "check feedback for 902128",
            "upload document for client 900005",
            "run full audit for 900003",
            "check compliance reports",
            "verify KYC for 900015",
        ]
    else:
        prompts = [" ".join(sys.argv[1:])]

    for p in prompts:
        print("=" * 70)
        print(f"PROMPT: {p}")
        print("=" * 70)
        result = resolve(p)
        print(json.dumps(result, indent=2, default=str))
        print()


if __name__ == "__main__":
    main()
