"""
web_selectors.py - Element Locator Pipeline (Phase 5)
The smart part. Full pipeline:
  Step A: Cache Lookup (no LLM)
  Step B: DOM Scraping
  Step C: Intent Extraction (LLM #3)
  Step D: Graph Search (no LLM)
  Step E: Context Building (no LLM)
  Step F: Locator Generation (LLM #4)
  Step G: Validate & Highlight
  Step H: Manual Fallback
"""
import json
import re
import logging
import asyncio
from pathlib import Path
from typing import Optional

from client.llm_api import call_llm
from .word_similarity import combined_similarity
from .scraping_by_knowledge_graph import run_scraping
from .StructuredSearch import StructuredSearchEngine, filter_relevant_candidates
from .GraphTraversal import GraphTraversal

logger = logging.getLogger(__name__)


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
        logger.warning(f"Failed to save locator cache: {e}")


def get_selector_from_json_file(field_name: str, field_type: str, cache: dict) -> Optional[dict]:
    return cache.get(f"{field_name}|{field_type}")

# Forbidden XPath patterns
FORBIDDEN_PATTERNS = [
    r'jss-\d+',           # JSS/MUI generated
    r'css-[a-z0-9]+',     # Emotion/styled-component
    r'sc-[a-zA-Z]+',      # styled-components
    r'_[a-f0-9]{5,}',     # CSS module hashes
]

# Locator priority order
PRIORITY_ORDER = "data-testid > aria-* > role > id > text() > position"

LOCATOR_GENERATION_PROMPT = """You are a QA assistant. Generate a robust XPath locator.

FORBIDDEN PATTERNS:
• No JSS/MUI/Emotion/styled-component classes
• No CSS-module hashes

PRIORITY ORDER:
data-testid > aria-* > role > id > text() > position

RULES:
• Prefer text() match for tabs/buttons/links — e.g. //*[normalize-space(text())='Reports']
• Use ancestor scoping for ambiguous matches
• Handle grid/dialog/tab/menu patterns
• text() for direct text, . for descendant text
• Do NOT add class-exclusion predicates (no `not(contains(@class,...))`) — apps may legitimately use css- prefixes
• Verify match_count = 1

CONTEXT: __CONTEXT__
QUERY: __USER_QUERY__

OUTPUT: Return ONLY a JSON object:
{{"xpath": "...", "frame_url": "...", "frame_name": "...", "confidence": "high|medium|low", "reasoning": "...", "match_count": 1}}
"""


async def get_selector(page, field_name: str, field_type: str, action: str,
                       config: dict, page_url: str = "") -> dict:
    """
    Full element locator pipeline.
    Returns: {xpath, frame_url, frame_name, confidence}
    """
    if not page_url:
        page_url = page.url

    # ── Step A: Cache Lookup ──
    cache = load_locator_cache(config, page_url)
    cached = get_selector_from_json_file(field_name, field_type, cache)
    if cached:
        logger.info(f"Cache HIT for '{field_name}' → {cached['xpath']}")
        return cached

    logger.info(f"Cache MISS for '{field_name}'. Running full pipeline.")

    # ── Steps B+C: DOM Scraping + Intent Extraction ──
    query = f"{action} on {field_name}"
    kg, structured_intent = await run_scraping(page, query)

    # ── Step D: Graph Search ──
    search_engine = StructuredSearchEngine(kg)
    candidates = search_engine.search(structured_intent, top_k=10)

    # Fallback to heuristic search if poor results
    if not candidates or candidates[0][1] < 1.0:
        logger.info("Structured search weak, trying heuristic fallback")
        heuristic_candidates = search_engine.search_heuristic(field_name, top_k=10)
        candidates = _merge_candidates(candidates, heuristic_candidates)

    candidates = filter_relevant_candidates(candidates, threshold=0.3)

    if not candidates:
        logger.warning(f"No candidates found for '{field_name}'")
        return {"xpath": "", "frame_url": "", "frame_name": "", "confidence": "none", "error": "No candidates"}

    # ── Step E: Context Building ──
    traversal = GraphTraversal(kg)
    context_json = traversal.build_subtree_context_locatable_v2(candidates)

    # ── Step F: LLM Call #4 - Locator Generation ──
    prompt = LOCATOR_GENERATION_PROMPT.replace("__CONTEXT__", context_json).replace("__USER_QUERY__", field_name)
    response = call_llm(prompt)

    try:
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
        locator = json.loads(clean)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse locator JSON: {response[:200]}")
        # Use best candidate's xpath as fallback
        locator = {
            "xpath": candidates[0][0].xpath,
            "frame_url": candidates[0][0].frame_url,
            "frame_name": candidates[0][0].frame_name,
            "confidence": "low",
            "reasoning": "Fallback to best candidate xpath",
            "match_count": 1,
        }

    # ── Step G: Validate & Highlight ──
    xpath = locator.get("xpath", "")

    # Check forbidden patterns
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, xpath):
            logger.warning(f"Forbidden pattern found in xpath: {xpath}")
            locator["confidence"] = "low"
            locator["warning"] = f"Contains forbidden pattern: {pattern}"

    # Validate on page
    try:
        frame_url = locator.get("frame_url", "")
        target_frame = page
        if frame_url:
            for frame in page.frames:
                if frame.url and frame_url in frame.url:
                    target_frame = frame
                    break

        match_count = await target_frame.locator(f"xpath={xpath}").count()
        locator["match_count"] = match_count

        if match_count == 0:
            logger.warning(f"XPath matched 0 elements. Retrying with LLM (Call #4b).")
            # ── RETRY: LLM Call #4b ──
            retry_prompt = prompt + f"\n\nPREVIOUS ATTEMPT FAILED: xpath '{xpath}' matched 0 elements. Try again with a different approach."
            retry_response = call_llm(retry_prompt)
            try:
                clean = retry_response.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
                locator = json.loads(clean)
                xpath = locator.get("xpath", "")
                match_count = await target_frame.locator(f"xpath={xpath}").count()
                locator["match_count"] = match_count
            except Exception as e:
                logger.error(f"Retry failed: {e}")

        if match_count == 1:
            # Highlight element
            await _highlight_element_on_page(target_frame, xpath)

            # Save to cache
            cache[f"{field_name}|{field_type}"] = locator
            save_locator_cache(config, page_url, cache)
            logger.info(f"Locator cached for '{field_name}'")

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        locator["validation_error"] = str(e)

    return locator


def get_selector_from_json_file(field_name: str, field_type: str, cache: dict) -> dict | None:
    """
    Step A: Cache Lookup.
    Try exact name match, then fuzzy similarity via word_similarity.
    """
    # Exact match
    key = f"{field_name}|{field_type}"
    if key in cache:
        return cache[key]

    # Fuzzy match
    best_score = 0.0
    best_match = None
    for cached_key, cached_value in cache.items():
        cached_name = cached_key.split("|")[0]
        score = combined_similarity(field_name.lower(), cached_name.lower())
        if score > best_score and score > 0.85:
            best_score = score
            best_match = cached_value

    if best_match:
        logger.info(f"Fuzzy cache match for '{field_name}' (score={best_score:.2f})")
        return best_match

    return None


async def _highlight_element_on_page(frame, xpath: str):
    """Inject JS to scroll to and flash-highlight the element."""
    try:
        await frame.evaluate(f"""
            (xpath) => {{
                const result = document.evaluate(xpath, document, null, 
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                const el = result.singleNodeValue;
                if (el) {{
                    el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    const orig = el.style.outline;
                    el.style.outline = '3px solid red';
                    setTimeout(() => {{ el.style.outline = orig; }}, 2000);
                }}
            }}
        """, xpath)
    except Exception as e:
        logger.warning(f"Highlight failed: {e}")


def _merge_candidates(structured, heuristic):
    """Merge structured + heuristic results, deduplicating by node id."""
    seen = set()
    merged = []
    for node, score in structured:
        if node.id not in seen:
            seen.add(node.id)
            merged.append((node, score))
    for node, score in heuristic:
        if node.id not in seen:
            seen.add(node.id)
            merged.append((node, score * 0.8))  # slightly discount heuristic
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged
