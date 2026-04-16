"""
scraping_by_knowledge_graph.py — V2 orchestrator helpers
(ported from V2_Req/CAPTURE_scraping_by_knowledge_graph.md)

Responsibilities:
  - Token estimation & 50K-budget trimming
  - 4-strategy relevance filter with TEXT-FIRST override
  - Keyword extraction + overlap validation
  - JS-based element highlight with pulse animation
  - LLM response cleaning
  - Context dict standardization
  - run_scraping(): full pipeline from DOM → KG → intent → candidates
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from client.llm_api import call_llm
from .DOMSemanticParser import DOMSemanticParser
from .KnowledgeGraph import KnowledgeGraph
from .StructuredSearch import (
    ENHANCED_INTENT_PROMPT_TEMPLATE,
    IntentQueryBuilder,
    NodeMatchCriteria,
    StructuredQuery,
    StructuredSearchEngine,
)

logger = logging.getLogger(__name__)


# ==========================================================================
# 1. Token estimation
# ==========================================================================

def _estimate_tokens(text: str) -> int:
    """Best-effort: HuggingFace tokenizer if available, else chars/4."""
    if not text:
        return 0
    try:
        from tokenizers import Tokenizer  # type: ignore
        tokenizer_path = os.environ.get("PRECISIONAI_TOKENIZER_JSON", "").strip()
        if tokenizer_path and os.path.exists(tokenizer_path):
            tok = Tokenizer.from_file(tokenizer_path)
            return len(tok.encode(text).ids)
    except Exception:
        pass
    return max(1, int(len(text) / 4))


def _count_prompt_context_tokens(prompt_context: Any) -> int:
    try:
        txt = json.dumps(prompt_context, ensure_ascii=False)
    except Exception:
        txt = str(prompt_context)
    return _estimate_tokens(txt)


# ==========================================================================
# 2. Subtree ID extraction
# ==========================================================================

def _subtree_node_id(subtree: Dict[str, Any]) -> str:
    for k in ("target_node_id", "TargetNodeId", "node_id", "nodeid"):
        v = subtree.get(k)
        if isinstance(v, str) and v:
            return v
    chain = subtree.get("node_chain")
    if isinstance(chain, list) and chain:
        last = chain[-1]
        if isinstance(last, dict):
            for k in ("node_id", "id"):
                v = last.get(k)
                if isinstance(v, str) and v:
                    return v
    return ""


# ==========================================================================
# 3. Token-budget trimming
# ==========================================================================

def _trim_prompt_context_to_token_limit(
    prompt_context: Any,
    node_scores: Dict[str, float],
    token_limit: int = 50_000,
    safety_margin_tokens: int = 1_000,
) -> Any:
    """Drop lowest-scored subtrees until under budget. Hard-truncate as last resort."""
    if not isinstance(prompt_context, list) or not prompt_context:
        return prompt_context

    budget = max(0, int(token_limit) - int(safety_margin_tokens))
    current_tokens = _count_prompt_context_tokens(prompt_context)
    if current_tokens <= budget:
        return prompt_context

    scored: List[Tuple[float, int, Dict[str, Any]]] = []
    for i, subtree in enumerate(prompt_context):
        if not isinstance(subtree, dict):
            scored.append((float("inf"), i, subtree))
            continue
        nid = _subtree_node_id(subtree)
        s = node_scores.get(nid)
        scored.append((float(s) if s is not None else float("inf"), i, subtree))

    scored_sorted = sorted(scored, key=lambda t: (t[0], t[1]))
    keep_mask = [True] * len(prompt_context)
    for score, idx, _sub in scored_sorted:
        if current_tokens <= budget:
            break
        if score == float("inf") and any(
            s != float("inf") for s, _, __ in scored_sorted if keep_mask[_]
        ):
            continue
        keep_mask[idx] = False
        trimmed = [prompt_context[j] for j in range(len(prompt_context)) if keep_mask[j]]
        current_tokens = _count_prompt_context_tokens(trimmed)

    final_ctx = [prompt_context[j] for j in range(len(prompt_context)) if keep_mask[j]]

    if _count_prompt_context_tokens(final_ctx) > budget:
        # Hard-truncate: keep highest-scoring subtrees until under budget
        kept = [(s, i, sub) for (s, i, sub) in scored if keep_mask[i]]
        kept_sorted_desc = sorted(kept, key=lambda t: (-t[0], t[1]))
        hard: List[Tuple[int, Any]] = []
        for s, i, sub in kept_sorted_desc:
            hard.append((i, sub))
            candidate = [x for _, x in sorted(hard, key=lambda t: t[0])]
            if _count_prompt_context_tokens(candidate) > budget:
                hard.pop()
                break
        final_ctx = [x for _, x in sorted(hard, key=lambda t: t[0])]

    return final_ctx


# ==========================================================================
# 4. Search keywords
# ==========================================================================

_STOP_WORDS = {
    "the", "a", "for", "from", "with", "that", "this", "into",
    "under", "above", "below", "next", "near", "input", "field",
    "button", "click", "clicks", "enter", "type", "select",
    "choose", "which", "please", "in", "label", "labelled", "section",
    "user", "opens", "press", "tap", "hover", "toggle", "on", "of", "to",
}


def _extract_search_keywords(parsed_intent: Optional[dict], field_name: str) -> set:
    primary_texts: List[str] = []
    if parsed_intent and isinstance(parsed_intent, dict):
        target = parsed_intent.get("target") or {}
        primary_texts.append(target.get("text") or "")
        primary_texts.append(target.get("placeholder") or "")
        label = parsed_intent.get("label") or {}
        if isinstance(label, dict):
            primary_texts.append(label.get("text") or "")
        kws = parsed_intent.get("keywords") or []
        if isinstance(kws, list):
            for kw in kws:
                if isinstance(kw, str) and kw.strip():
                    primary_texts.append(kw.strip())

    secondary_texts: List[str] = []
    if field_name:
        secondary_texts.append(field_name)

    keywords: set = set()
    # primary: keep all tokens
    for txt in primary_texts:
        for token in str(txt).lower().split():
            token = token.strip(".,;:!?()[]{}'\"")
            if token and token not in _STOP_WORDS:
                keywords.add(token)
    # secondary: require length >= 3
    for txt in secondary_texts:
        for token in str(txt).lower().split():
            token = token.strip(".,;:!?()[]{}'\"")
            if len(token) >= 3 and token not in _STOP_WORDS:
                keywords.add(token)
    return keywords


def _has_keyword_overlap(meta: dict, keywords: set) -> bool:
    if not meta or not keywords:
        return True
    attrs = meta.get("attrs", {}) or {}
    parts = [
        meta.get("text", ""),
        meta.get("innerText", ""),
        meta.get("text_content_raw", ""),
        meta.get("text_own_norm", ""),
        meta.get("text_desc_norm", ""),
        attrs.get("aria-label", ""),
        attrs.get("placeholder", ""),
        attrs.get("name", ""),
        attrs.get("title", ""),
        attrs.get("id", ""),
        attrs.get("data-testid", ""),
    ]
    cls = attrs.get("class", "")
    if isinstance(cls, list):
        cls = " ".join(cls)
    if len(str(cls)) < 200:
        parts.append(str(cls))
    blob = " ".join(str(p).lower() for p in parts if p)
    for kw in keywords:
        if kw in blob:
            return True
    return False


# ==========================================================================
# 5. Relevance filter (4-strategy, TEXT-FIRST)
# ==========================================================================

_HINT_TO_TAGS = {
    "input":    ("input", "textarea"),
    "textarea": ("textarea",),
    "textbox":  ("input", "textarea"),
    "button":   ("button", "a"),
    "link":     ("a",),
    "checkbox": ("input",),
    "radio":    ("input",),
    "select":   ("select",),
    "combobox": ("select", "input"),
    "option":   ("option", "li"),
    "menuitem": ("li", "a"),
    "tab":      ("button", "a"),
    "icon":     ("i", "svg", "span", "img"),
    "img":      ("img",),
}
_ROLE_PASS = ("textbox", "searchbox", "combobox", "listbox", "button", "link",
              "tab", "checkbox", "radio", "switch", "menuitem", "option")


def _filter_relevant_candidates(
    results: List[Dict[str, Any]],
    parsed_intent: Optional[dict],
    field_name: str,
    max_candidates: int = 5,
    min_abs_score: float = 1.0,
    min_relative_pct: float = 0.10,
) -> List[Dict[str, Any]]:
    if not results:
        return results

    keywords = _extract_search_keywords(parsed_intent, field_name)
    top_score = max(float(r.get("score", 0.0)) for r in results)
    rel_threshold = top_score * min_relative_pct

    # Element-hint expected tags
    hints = []
    if parsed_intent and isinstance(parsed_intent, dict):
        hints = (parsed_intent.get("target") or {}).get("element_hints") or []
    expected_tags: set = set()
    for h in hints:
        h_low = str(h).strip().lower()
        expected_tags.update(_HINT_TO_TAGS.get(h_low, (h_low,)))

    filtered: List[Dict[str, Any]] = []
    for r in results:
        score = float(r.get("score", 0.0))
        nid = r.get("node_id", "")

        if score < min_abs_score:
            continue
        if score < rel_threshold:
            continue

        meta = r.get("metadata", {}) or {}
        attrs = meta.get("attrs", {}) or {}
        tag = (meta.get("tag") or "").lower()
        role = (meta.get("role") or attrs.get("role") or "").lower()

        # Strategy 3: keyword overlap (with proximity-found exception)
        is_proximity = bool(r.get("anchor_source") or r.get("label_source"))
        if keywords and not is_proximity and not _has_keyword_overlap(meta, keywords):
            logger.debug("[relevance_filter] DROP %s no keyword overlap", nid)
            continue

        # Strategy 4: element-type validation with TEXT-FIRST override
        if expected_tags and tag and tag not in expected_tags:
            role_passes = bool(role) and role in _ROLE_PASS
            ce = (attrs.get("contenteditable") or "").strip().lower()
            is_ce = ce in ("true", "plaintext-only")
            if not role_passes and not is_ce:
                target_text = (parsed_intent or {}).get("target", {}).get("text", "") if parsed_intent else ""
                target_text = (target_text or "").strip().lower()
                texts_joined = " ".join(str(x).lower() for x in [
                    meta.get("text", ""), meta.get("innerText", ""),
                    meta.get("text_own_norm", ""), meta.get("text_content_raw", ""),
                    meta.get("text_desc_norm", ""), attrs.get("aria-label", ""),
                    attrs.get("title", ""), attrs.get("placeholder", ""),
                ] if x)
                has_strong_text = False
                if target_text and target_text in texts_joined:
                    has_strong_text = True
                elif target_text:
                    q_words = {w for w in target_text.split() if len(w) >= 3}
                    if q_words:
                        found = sum(1 for w in q_words if w in texts_joined)
                        if found >= len(q_words) * 0.8:
                            has_strong_text = True
                if not has_strong_text:
                    # 92% penalty
                    r["score"] = score * 0.08
                    logger.debug("[relevance_filter] PENALIZE %s tag=%s not in %s", nid, tag, expected_tags)

        filtered.append(r)

    logger.info(
        "[relevance_filter] %d/%d candidates passed (top=%.2f abs=%.2f rel=%.2f)",
        len(filtered), len(results), top_score, min_abs_score, rel_threshold,
    )
    filtered.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return filtered[:max_candidates]


# ==========================================================================
# 6. Element highlighting
# ==========================================================================

HIGHLIGHT_JS = """
(element) => {
    element.style.outline = '3px solid #FF4444';
    element.style.outlineOffset = '2px';
    element.style.boxShadow = '0 0 12px 4px rgba(255, 68, 68, 0.5)';
    element.scrollIntoView({behavior: 'smooth', block: 'center'});
    let count = 0;
    const interval = setInterval(() => {
        count++;
        if (count % 2 === 0) {
            element.style.outline = '3px solid #FF4444';
            element.style.boxShadow = '0 0 12px 4px rgba(255, 68, 68, 0.5)';
        } else {
            element.style.outline = '3px solid #FF4400';
            element.style.boxShadow = '0 0 12px 4px rgba(255, 178, 0, 0.5)';
        }
        if (count >= 6) {
            clearInterval(interval);
            element.style.outline = '2px dashed #FF4444';
            element.style.outlineOffset = '2px';
            element.style.boxShadow = '0 0 6px 2px rgba(255, 68, 68, 0.3)';
        }
    }, 350);
}
"""


async def _highlight_element_on_page(page, xpath: str, frame_url: str = "", frame_name: str = "") -> dict:
    """Locate element by XPath on the page and apply visual highlight."""
    try:
        target_frame = page
        if frame_url or frame_name:
            for frame in page.frames:
                if frame_url and frame.url and frame_url in frame.url:
                    target_frame = frame
                    break
                if frame_name and frame.name == frame_name:
                    target_frame = frame
                    break
        elements = await target_frame.locator(f"xpath={xpath}").all()
        match_count = len(elements)
        logger.info("[highlight] XPath %r matched %d", xpath, match_count)
        if match_count == 0:
            return {"success": False, "match_count": 0, "error": "XPath matched 0 elements"}
        await elements[0].evaluate(HIGHLIGHT_JS)
        return {"success": True, "match_count": match_count, "error": None}
    except Exception as e:
        logger.warning("[highlight] Failed: %s", e)
        return {"success": False, "match_count": 0, "error": str(e)}


# ==========================================================================
# 7. LLM response cleaning
# ==========================================================================

def _clean_llm_response(llm_response: str) -> str:
    cleaned = (llm_response or "").strip()
    if "```json" in cleaned:
        start_idx = cleaned.find("```json")
        if start_idx != -1:
            cleaned = cleaned[start_idx + 7:]
            end_idx = cleaned.find("```")
            if end_idx != -1:
                cleaned = cleaned[:end_idx].strip()
    elif "```" in cleaned:
        start_idx = cleaned.find("```")
        if start_idx != -1:
            cleaned = cleaned[start_idx + 3:]
            end_idx = cleaned.find("```")
            if end_idx != -1:
                cleaned = cleaned[:end_idx].strip()
            if cleaned.startswith("\n"):
                cleaned = cleaned[1:]
    if not cleaned.startswith("{"):
        json_start = cleaned.find("{")
        if json_start != -1:
            brace_count = 0
            json_end = -1
            for i, ch in enumerate(cleaned[json_start:], start=json_start):
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            if json_end != -1:
                cleaned = cleaned[json_start:json_end].strip()
    return cleaned


# ==========================================================================
# 8. Context standardization
# ==========================================================================

def _extract_context(context: Dict[str, Any]) -> dict:
    run_id = (context.get("run_id") or "").strip()
    seal_id = (context.get("seal_id") or "").strip()
    project_name = (context.get("project_name") or context.get("proj_name") or "").strip()
    component_name = (context.get("component_name") or "").strip() or "default_component"
    return {
        "run_id": run_id,
        "seal_id": seal_id,
        "project_name": project_name,
        "component_name": component_name,
    }


# ==========================================================================
# 9. Pollution detection & XPath fixing
# ==========================================================================

_FORBIDDEN_XPATH_PATTERNS = [
    (r'\bjss\d+\b', 'JSS class'),
    (r'\bMui[A-Z][a-zA-Z]*-[\w]+\b', 'MUI class'),
    (r'\bsc-[a-zA-Z]{6,}\b', 'styled-components class'),
    (r'\bcss-[a-z0-9]{6,}\b', 'Emotion class'),
    (r'\b[a-zA-Z]+_[a-zA-Z]+_[a-zA-Z0-9]{5}\b', 'CSS module class'),
]

_NORMALIZE_EXACT_RE = re.compile(
    r"normalize-space\((\.\s*|\s*\.\s*)\)\s*=\s*(['\"])(.*?)\2"
)


def has_pollution_in_context(prompt_context: list) -> bool:
    for subtree in (prompt_context or []):
        if not isinstance(subtree, dict):
            continue
        ts = subtree.get("target_summary") or {}
        if ts.get("has_style_script_pollution"):
            return True
        for node in subtree.get("node_chain", []) or []:
            meta = node.get("metadata") or {}
            if meta.get("has_style_script_pollution"):
                return True
        for group_key in ("ancestors", "siblings", "descendants"):
            for n in subtree.get(group_key, []) or []:
                meta = n.get("metadata") or {}
                if meta.get("has_style_script_pollution"):
                    return True
    return False


def fix_pollution_xpath(xpath: str) -> str:
    def _repl(m):
        text_val = m.group(3)
        return f"contains(., '{text_val}')"
    return _NORMALIZE_EXACT_RE.sub(_repl, xpath)


# ==========================================================================
# 10. Main pipeline: run_scraping
# ==========================================================================

async def run_scraping(page, query: str) -> Tuple[KnowledgeGraph, Dict[str, Any]]:
    """Pipeline steps B-C: DOM parse → KnowledgeGraph → LLM Call #3 intent extraction.

    Returns:
        (kg, parsed_intent) — the built KnowledgeGraph and parsed intent dict.
    """
    # Step B: DOM parse
    parser = DOMSemanticParser(page)
    tree = await parser.run_full_sequence()

    # Step B2: build KG + semantic edges
    kg = KnowledgeGraph()
    kg.load_parsed_structure(tree)
    kg.convert_to_graph()

    # Step C: LLM Call #3 - intent extraction using ENHANCED_INTENT_PROMPT_TEMPLATE
    prompt = ENHANCED_INTENT_PROMPT_TEMPLATE.replace("__USER_QUERY__", query)
    try:
        raw = call_llm(prompt)
    except Exception as e:
        logger.warning("[intent] LLM call failed: %s — falling back to trivial intent", e)
        raw = ""

    parsed_intent: Dict[str, Any] = {}
    if raw:
        try:
            parsed_intent = json.loads(_clean_llm_response(raw))
        except Exception:
            logger.warning("[intent] JSON parse failed; raw=%r", raw[:200])
            parsed_intent = {}

    if not parsed_intent:
        # Trivial fallback intent — treat the query as target.text
        parsed_intent = {
            "action": "click",
            "target": {"text": query, "element_hints": [], "properties": {"isVisible": True}},
            "label": None,
            "anchor": None,
            "keywords": [w for w in query.split() if len(w) > 2],
        }

    logger.info("[intent] %s", json.dumps(parsed_intent)[:300])
    return kg, parsed_intent


async def search_candidates(
    kg: KnowledgeGraph,
    parsed_intent: Dict[str, Any],
    field_name: str,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Run StructuredSearch + 3-tier fallback + relevance filter.

    Returns a list of candidate dicts: {node_id, score, metadata, ...}.
    """
    results_k: List[Dict[str, Any]] = []

    # PRIMARY: StructuredSearch
    try:
        structured_query = IntentQueryBuilder.build(parsed_intent)
        logger.info("[search] query=%s", structured_query.summary())
        ss_engine = StructuredSearchEngine(kg)
        results_k = ss_engine.search(structured_query, top_k=top_k, prefer_visible=True)
    except Exception:
        logger.exception("[search] StructuredSearch failed")
        results_k = []

    # FALLBACK: keyword search on intent keywords
    if not results_k:
        logger.info("[search] falling back to keyword heuristic")
        try:
            ss_engine = StructuredSearchEngine(kg)
            kws = parsed_intent.get("keywords") or []
            if isinstance(kws, list) and kws:
                results_k = ss_engine._keyword_fallback(
                    [str(k) for k in kws if isinstance(k, str)],
                    top_k=top_k, prefer_visible=True,
                )
            if not results_k:
                results_k = ss_engine._keyword_fallback([field_name], top_k=top_k, prefer_visible=True)
        except Exception:
            logger.exception("[search] Keyword fallback failed")

    # De-dupe
    best_by_node: Dict[str, Dict[str, Any]] = {}
    for r in results_k:
        nid = r.get("node_id")
        if not nid:
            continue
        if nid not in best_by_node or float(r.get("score", 0)) > float(best_by_node[nid].get("score", 0)):
            best_by_node[nid] = r
    results_k = sorted(best_by_node.values(), key=lambda x: float(x.get("score", 0)), reverse=True)

    # Relevance filter
    unfiltered_top = results_k[:5]
    filtered = _filter_relevant_candidates(
        results_k,
        parsed_intent=parsed_intent,
        field_name=field_name,
        max_candidates=5,
        min_abs_score=1.0,
        min_relative_pct=0.10,
    )

    # Safety: supplemental keyword search with looser thresholds
    if not filtered:
        logger.warning("[search] filter dropped all — running supplemental keyword search")
        try:
            ss_engine = StructuredSearchEngine(kg)
            intent_kws = parsed_intent.get("keywords") or []
            label_text = ((parsed_intent.get("label") or {}).get("text") or "").strip()
            if label_text and label_text not in intent_kws:
                intent_kws = [label_text] + list(intent_kws)
            if intent_kws:
                supp = ss_engine._keyword_fallback(
                    [str(k) for k in intent_kws if isinstance(k, str)],
                    top_k=10, prefer_visible=True,
                )
                filtered = _filter_relevant_candidates(
                    supp,
                    parsed_intent=parsed_intent,
                    field_name=field_name,
                    max_candidates=5,
                    min_abs_score=0.5,
                    min_relative_pct=0.05,
                )
        except Exception:
            logger.exception("[search] supplemental search failed")

    # Final fallback: top 3 unfiltered
    if not filtered and unfiltered_top:
        logger.warning("[search] falling back to top 3 unfiltered")
        filtered = unfiltered_top[:3]

    return filtered
