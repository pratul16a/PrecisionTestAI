"""
web_selectors.py — V2 Element Locator Pipeline (Phase 5)

Pipeline:
  Step A:  Cache Lookup (exact + fuzzy via word_similarity)
  Step B:  DOM Scraping (DOMSemanticParser)
  Step B2: KnowledgeGraph construction + semantic edges
  Step C:  LLM #3 — Intent Extraction
  Step D:  StructuredSearchEngine (two-phase text-first scoring)
  Step E:  GraphTraversal subtree context + 50K token trim
  Step F:  LLM #4 — Locator Generation (with assistant_instructions.txt)
  Step G:  Validate + auto-fix pollution + highlight
  Step H:  Manual fallback (cache user-supplied XPath)
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from client.llm_api import call_llm

from .GraphTraversal import GraphTraversal
from .scraping_by_knowledge_graph import (
    _clean_llm_response,
    _filter_relevant_candidates,
    _highlight_element_on_page,
    _trim_prompt_context_to_token_limit,
    _FORBIDDEN_XPATH_PATTERNS,
    fix_pollution_xpath,
    has_pollution_in_context,
    run_scraping,
    search_candidates,
)
from .word_similarity import combined_similarity

logger = logging.getLogger(__name__)

# ---- load assistant instructions once ----
_ASSISTANT_INSTRUCTIONS_PATH = Path(__file__).parent / "assistant_instructions.txt"
try:
    _ASSISTANT_INSTRUCTIONS = _ASSISTANT_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
except Exception:
    _ASSISTANT_INSTRUCTIONS = ""
    logger.warning("[locator] assistant_instructions.txt not found; using built-in prompt")


BUILTIN_PROMPT_FOOTER = """

CONTEXT:
__CONTEXT__

USER QUERY:
__USER_QUERY__

Return ONLY a JSON object of this shape:
{
    "xpath": "...",
    "frame_url": "...",
    "frame_name": "...",
    "associated_element_type": "input|icon|text",
    "element_handler": "click|type|select|hover|check|...",
    "confidence": "high|medium|low",
    "reasoning": "...",
    "match_count": 1,
    "status": "found|no_match|error"
}
"""


# ==========================================================================
# Cache
# ==========================================================================

def _cache_path(config: dict, page_url: str) -> Path:
    cache_dir = Path(config.get("cache_dir", "cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^a-zA-Z0-9]+", "_", page_url)[:120] or "default"
    return cache_dir / f"locators_{safe}.json"


def load_locator_cache(config: dict, page_url: str) -> dict:
    p = _cache_path(config, page_url)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_locator_cache(config: dict, page_url: str, cache: dict) -> None:
    try:
        _cache_path(config, page_url).write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("[cache] save failed: %s", e)


def get_selector_from_json_file(field_name: str, field_type: str, cache: dict) -> Optional[dict]:
    key = f"{field_name}|{field_type}"
    if key in cache:
        return cache[key]
    best_score = 0.0
    best_match = None
    for cached_key, cached_value in cache.items():
        try:
            cached_name = cached_key.split("|")[0]
        except Exception:
            continue
        score = combined_similarity(field_name.lower(), cached_name.lower())
        if score > best_score and score > 0.85:
            best_score = score
            best_match = cached_value
    if best_match:
        logger.info("[cache] fuzzy hit for %r (score=%.2f)", field_name, best_score)
    return best_match


# ==========================================================================
# Main entry point
# ==========================================================================

async def get_selector(
    page,
    field_name: str,
    field_type: str,
    action: str,
    config: dict,
    page_url: str = "",
    field_description: str = "",
) -> dict:
    """Full element locator pipeline."""
    if not page_url:
        page_url = page.url
    query = field_description or f"{action} {field_name}".strip()

    # Step A: cache lookup
    cache = load_locator_cache(config, page_url)
    cached = get_selector_from_json_file(field_name, field_type, cache)
    if cached and cached.get("xpath"):
        logger.info("[locator] cache HIT for %r -> %s", field_name, cached.get("xpath"))
        return cached

    logger.info("[locator] cache MISS for %r — running full pipeline", field_name)

    # Steps B + C: scrape DOM, build KG, extract intent
    kg, parsed_intent = await run_scraping(page, query)

    # Step D: run search with relevance filter + fallbacks
    candidates = await search_candidates(kg, parsed_intent, field_name, top_k=10)
    if not candidates:
        return _empty_locator("No candidates found after all fallbacks")

    # Step E: build subtree context for each candidate
    traversal = GraphTraversal(kg)
    target_ids = [c["node_id"] for c in candidates]
    node_scores = {c["node_id"]: float(c.get("score", 0.0)) for c in candidates}
    prompt_context = traversal.build_subtree_context_locatable_v2(
        target_ids, parsed_intent=parsed_intent,
    )
    prompt_context = _trim_prompt_context_to_token_limit(
        prompt_context, node_scores, token_limit=50_000,
    )

    # Step F: LLM Call #4
    llm_response = _call_locator_llm(prompt_context, parsed_intent, query)

    # Step G: parse, validate, highlight
    locator, validation_error = _parse_and_validate_locator(llm_response, prompt_context)
    if validation_error:
        logger.warning("[locator] validation failed: %s — retry once (Call #4b)", validation_error)
        retry_response = _call_locator_llm(
            prompt_context, parsed_intent, query,
            feedback=f"Previous attempt failed: {validation_error}",
        )
        locator, validation_error = _parse_and_validate_locator(retry_response, prompt_context)

    if not locator or validation_error:
        # Fall back to best candidate's suggested locator
        best = candidates[0]
        best_meta = best.get("metadata") or {}
        stability = kg._compute_stability_info(best_meta)
        suggestions = traversal._compute_locator_suggestions(best_meta, stability)
        xpath = suggestions[0] if suggestions else best_meta.get("xpath", "")
        locator = {
            "xpath": xpath,
            "frame_url": best_meta.get("frame_url", ""),
            "frame_name": best_meta.get("frame_name", ""),
            "confidence": "low",
            "reasoning": validation_error or "LLM response unparseable; using top-candidate fallback",
            "match_count": 0,
            "status": "found" if xpath else "no_match",
        }

    xpath = locator.get("xpath", "")
    if not xpath:
        return _empty_locator(locator.get("reasoning", "No XPath produced"))

    # Validate on page; retry once if count == 0
    try:
        highlight_result = await _highlight_element_on_page(
            page, xpath,
            frame_url=locator.get("frame_url", ""),
            frame_name=locator.get("frame_name", ""),
        )
        locator["match_count"] = highlight_result.get("match_count", 0)
        if not highlight_result.get("success") and highlight_result.get("match_count") == 0:
            logger.warning("[locator] XPath matched 0 elements — retrying LLM Call #4b")
            retry_response = _call_locator_llm(
                prompt_context, parsed_intent, query,
                feedback=f"Previous XPath {xpath!r} matched 0 elements on the page.",
            )
            retry_locator, retry_error = _parse_and_validate_locator(retry_response, prompt_context)
            if retry_locator and not retry_error and retry_locator.get("xpath"):
                locator = retry_locator
                xpath = locator["xpath"]
                await _highlight_element_on_page(
                    page, xpath,
                    frame_url=locator.get("frame_url", ""),
                    frame_name=locator.get("frame_name", ""),
                )
    except Exception as e:
        logger.warning("[locator] validation/highlight error: %s", e)
        locator["validation_error"] = str(e)

    # Cache on success
    if locator.get("match_count", 0) > 0:
        cache[f"{field_name}|{field_type}"] = locator
        save_locator_cache(config, page_url, cache)
        logger.info("[locator] cached %r", field_name)

    return locator


# ==========================================================================
# LLM #4 call
# ==========================================================================

def _call_locator_llm(
    prompt_context: list,
    parsed_intent: dict,
    query: str,
    feedback: str = "",
) -> str:
    """Compose the LLM #4 prompt and call the model."""
    base = _ASSISTANT_INSTRUCTIONS if _ASSISTANT_INSTRUCTIONS else BUILTIN_PROMPT_FOOTER

    ctx_json = json.dumps({
        "parsed_intent": parsed_intent,
        "candidates": prompt_context,
    }, ensure_ascii=False, indent=2)[:180_000]  # hard char cap beyond token trim

    prompt = base.replace("__CONTEXT__", ctx_json).replace("__USER_QUERY__", query)
    if feedback:
        prompt += f"\n\nRETRY FEEDBACK: {feedback}\n"
    try:
        return call_llm(prompt)
    except Exception as e:
        logger.exception("[locator] LLM call failed: %s", e)
        return ""


# ==========================================================================
# Parse / validate / pollution-fix
# ==========================================================================

def _parse_and_validate_locator(raw_response: str, prompt_context: list):
    if not raw_response:
        return None, "empty LLM response"
    cleaned = _clean_llm_response(raw_response)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"

    status = data.get("status", "found")
    if status in ("no_match", "error"):
        return data, data.get("reasoning", "LLM returned no_match/error status")

    xp = data.get("xpath", "") or ""
    for pat, pat_name in _FORBIDDEN_XPATH_PATTERNS:
        m = re.search(pat, xp)
        if m:
            return None, f"forbidden {pat_name} in XPath: {m.group()}"

    # pollution auto-fix
    if xp and has_pollution_in_context(prompt_context):
        fixed = fix_pollution_xpath(xp)
        if fixed != xp:
            logger.info("[pollution-fix] %r -> %r", xp, fixed)
            data["xpath"] = fixed
            handler = data.get("element_handler", "")
            if isinstance(handler, str) and xp in handler:
                data["element_handler"] = handler.replace(xp, fixed)

    return data, None


def _empty_locator(reason: str) -> dict:
    return {
        "status": "error",
        "confidence": "none",
        "xpath": "",
        "frame_url": "",
        "frame_name": "",
        "associated_element_type": "",
        "element_handler": "",
        "match_count": 0,
        "reasoning": reason,
    }


# ==========================================================================
# Step H — manual fallback
# ==========================================================================

def save_manual_locator(
    config: dict,
    page_url: str,
    field_name: str,
    field_type: str,
    xpath: str,
    frame_url: str = "",
    frame_name: str = "",
) -> dict:
    """Persist a user-supplied XPath into the cache so future runs skip the pipeline."""
    cache = load_locator_cache(config, page_url)
    locator = {
        "xpath": xpath,
        "frame_url": frame_url,
        "frame_name": frame_name,
        "confidence": "manual",
        "reasoning": "user-supplied locator (Step H)",
        "match_count": 1,
        "status": "found",
    }
    cache[f"{field_name}|{field_type}"] = locator
    save_locator_cache(config, page_url, cache)
    logger.info("[locator] manually cached %r -> %s", field_name, xpath)
    return locator
