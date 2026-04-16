# CAPTURE: scraping_by_knowledge_graph.py
## Full transcription from 14 screenshots (lines 1–1237)
## File: precisiontestai/src/playwright_mcp/code/web_selectors/scraping_by_knowledge_graph.py

---

## FILE SUMMARY

This is the **main orchestration module** for the element locator pipeline (Phase 5).
It contains both helper functions (lines 1–611) AND the main `scrape_by_knowledge_graph()`
function (lines ~641–1237) that wires together all pipeline steps.

**Key responsibilities:**
1. **Token estimation & prompt trimming** — keep LLM context under token budget
2. **Relevance filtering** — prune garbage candidates before context building (4-strategy filter)
3. **Keyword extraction** — build search keywords from parsed intent
4. **Keyword overlap validation** — check if candidates have any textual match to query
5. **Element highlighting** — JS-based visual highlight of matched elements on live page
6. **LLM response cleaning** — extract JSON from LLM responses with code fences
7. **Context extraction** — standardize run_id/seal_id/project_name from kwargs

---

## IMPORTS (lines 1–15)

```python
import logging
import time
from typing import Dict, Any, Optional
from web_selectors.EmbeddingEngine import EmbeddingEngine
from web_selectors.DOMSemanticParser import DOMSemanticParser
import json
from web_selectors.KnowledgeGraph import GraphTraversal, KnowledgeGraph
from web_selectors.utility import sanitize_string_for_json_key, get_page_title
from web_selectors.open_ai_andGpt4 import call_using_ol_model_azure_openai, set_access_token, openai
from web_selectors.StructuredSearch import (
    StructuredQuery, NodeMatchCriteria, IntentQueryBuilder,
    StructuredSearchEngine, ENHANCED_INTENT_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)
```

**Key imports reveal the pipeline wiring:**
- `EmbeddingEngine` — for embedding-based search (Layer 4)
- `DOMSemanticParser` — DOM scraping (Step B)
- `GraphTraversal, KnowledgeGraph` — graph building + traversal (Step B2)
- `StructuredQuery, NodeMatchCriteria, IntentQueryBuilder, StructuredSearchEngine` — scoring (Step D)
- `ENHANCED_INTENT_PROMPT_TEMPLATE` — intent extraction prompt (Step C)
- `call_using_ol_model_azure_openai` — LLM API call wrapper

---

## FUNCTION 1: _estimate_tokens (lines 18–47)

```python
def _estimate_tokens(text: str) -> int:
    """Best-effort token estimation.

    - Prefer HuggingFace's `tokenizers` package (already in requirements) for a closer estimate.
    - Fallback to a conservative heuristic (chars/4).

    Notes:
    - This is an estimate used for trimming; it doesn't need to match the model exactly.
    - We intentionally do not make a network call.
    """
    if not text:
        return 0

    # 1) Try HuggingFace tokenizers if available.
    try:
        from tokenizers import Tokenizer  # type: ignore

        # Use a common GPT-ish BPE tokenizer if present locally; otherwise fallback.
        # Many environments won't ship tokenizer files; we keep this guarded.
        # We still keep the import path so a team can optionally provide a tokenizer JSON.
        # If not present, this will raise and we will fallback.
        tokenizer_path = os.environ.get("PRECISIONAI_TOKENIZER_JSON", "").strip()
        if tokenizer_path and os.path.exists(tokenizer_path):
            tok = Tokenizer.from_file(tokenizer_path)
            return len(tok.encode(text).ids)
    except Exception:
        pass

    # 2) Heuristic fallback: ~4 chars per token (rough for English/JSON-ish text).
    return max(1, int(len(text) / 4))
```

**Logic:** Try HuggingFace tokenizer from env var `PRECISIONAI_TOKENIZER_JSON` → fallback to chars/4 heuristic.

---

## FUNCTION 2: _count_prompt_context_tokens (lines 49–54)

```python
def _count_prompt_context_tokens(prompt_context: Any) -> int:
    try:
        txt = json.dumps(prompt_context, ensure_ascii=False)
    except Exception:
        txt = str(prompt_context)
    return _estimate_tokens(txt)
```

**Logic:** JSON-serialize the prompt context, then estimate tokens.

---

## FUNCTION 3: _trim_prompt_context_to_token_limit (lines 56–139)

```python
def _trim_prompt_context_to_token_limit(
    prompt_context: Any,
    node_scores: Dict[str, float],
    token_limit: int = 50_000,
    safety_margin_tokens: int = 1_000,
) -> Any:
    """
    Trim prompt_context under a token limit by dropping lowest-score subtrees.

    Assumptions (based on current GraphTraversal output):
    - prompt_context is a list, where each item corresponds to one requested top node.
    - each subtree item contains a 'target_node_id' (preferred) OR can be matched
      via any node id in 'node_chain'.

    If we can't match subtree→node id reliably, we keep that subtree (fail-safe).
    """
    if not isinstance(prompt_context, list) or not prompt_context:
        return prompt_context

    budget = max(0, int(token_limit) - int(safety_margin_tokens))
    current_tokens = _count_prompt_context_tokens(prompt_context)
    if current_tokens <= budget:
        return prompt_context

    # (calls _subtree_node_id below to match subtrees to scores)

    # Build candidates with scores; unknown score → keep (score=inf so removed last).
    scored: list[tuple[float, int, Dict[str, Any]]] = []
    for i, subtree in enumerate(prompt_context):
        if not isinstance(subtree, dict):
            scored.append((float("inf"), i, subtree))
            continue
        nid = _subtree_node_id(subtree)
        s = node_scores.get(nid)
        scored.append((float(s) if s is not None else float("inf"), i, subtree))

    # Remove lowest scores first; preserve original order for remaining items.
    scored_sorted = sorted(scored, key=lambda t: (t[0], t[1]))

    # Start with all kept; drop until under budget.
    keep_mask = [True] * len(prompt_context)
    for score, idx, _sub in scored_sorted:
        if current_tokens <= budget:
            break
        # If score is inf, it means unknown; stop dropping unknowns unless absolutely necessary.
        if score == float("inf") and any(s != float("inf") for s, _, __ in scored_sorted if keep_mask[_]):
            continue
        keep_mask[idx] = False
        trimmed = [prompt_context[j] for j in range(len(prompt_context)) if keep_mask[j]]
        current_tokens = _count_prompt_context_tokens(trimmed)

    final_ctx = [prompt_context[j] for j in range(len(prompt_context)) if keep_mask[j]]

    if _count_prompt_context_tokens(final_ctx) > budget:
        # fail-safe: if we're still over, hard-truncate by keeping the top N by score.
        # This avoids runaway prompts.
        kept = [(s, i, sub) for (s, i, sub) in scored if keep_mask[i]]
        kept_sorted = sorted(kept, key=lambda t: (t[0], t[1]))
        # Keep best-scored ones (i.e., highest score), so invert when truncating.
        kept_sorted_desc = sorted(kept_sorted, key=lambda t: (t[0], t[1]), reverse=True)
        hard = []
        for s, i, sub in kept_sorted_desc:
            hard.append((i, sub))
            candidate = [x for _, x in sorted(hard, key=lambda t: t[0])]
            if _count_prompt_context_tokens(candidate) > budget:
                hard.pop()  # revert last add
                break
        final_ctx = [x for _, x in sorted(hard, key=lambda t: t[0])]

    return final_ctx
```

**Key design:**
- Default token budget: **50,000** (with 1,000 safety margin)
- Drops lowest-scored subtrees first
- Unknown-score subtrees (score=inf) kept as long as possible
- Hard-truncation fallback: keep top-N by score if still over budget
- Preserves original order of remaining items

---

## FUNCTION 4: _subtree_node_id (lines 79–95)

```python
def _subtree_node_id(subtree: Dict[str, Any]) -> str:
    # Prefer explicit target_id if present.
    for k in ("target_node_id", "TargetNodeId", "node_id", "nodeid"):
        v = subtree.get(k)
        if isinstance(v, str) and v:
            return v

    # Fall back to last node in the node_chain (target-ish).
    chain = subtree.get("node_chain")
    if isinstance(chain, list) and chain:
        last = chain[-1]
        if isinstance(last, dict):
            for k in ("node_id", "id"):
                v = last.get(k)
                if isinstance(v, str) and v:
                    return v

    return ""
```

**Logic:** Extract node ID from subtree dict. Tries 4 key names, then falls back to last element in `node_chain`.

---

## FUNCTION 5: _filter_relevant_candidates (lines 143–376)

This is the **largest and most critical function** in the file. ~230 lines.

### Signature & Docstring

```python
def _filter_relevant_candidates(
    results: list,
    parsed_intent: Optional[dict],
    field_name: str,
    max_candidates: int = 5,
    min_abs_score: float = 1.0,
    min_relative_pct: float = 0.10,
) -> list:
    """
    Remove search results that are unlikely to be the correct target.

    Three pruning strategies (applied in order):
    1. *Absolute threshold* — drop any candidate with score < min_abs_score.
       Nodes that barely matched a substring in some random attribute are noise.
    2. *Relative gap* — drop candidates scoring < min_relative_pct of the
       top candidate's score. If #1 scores 15.0 and min_relative_pct=0.10,
       anything below 1.5 is cut.
    3. *Keyword overlap validation* — the candidate's text-bearing fields
       (text, innerText, aria-label, placeholder, id, class, name) must
       contain at least one substantive keyword from the query. Candidates
       with zero keyword overlap are garbage even if they scored > 0.

    Finally, cap at max_candidates.
    """
```

### Strategy 1: Absolute Threshold

```python
    if not results:
        return results

    keywords = _extract_search_keywords(parsed_intent, field_name)

    top_score = max(float(r.get("score", 0.0)) for r in results)
    rel_threshold = top_score * min_relative_pct
```

Drop any candidate with `score < 1.0` (default).

### Strategy 2: Relative Gap

Drop any candidate scoring < 10% of the top candidate's score.

### Strategy 3: Keyword Overlap (with proximity-found exception)

```python
        is_proximity_found = bool(r.get("anchor_source") or r.get("label_source"))
        if keywords and not is_proximity_found and not _has_keyword_overlap(r.get("metadata", {}), keywords):
            logger.debug("[relevance_filter] DROP %s — no keyword overlap", nid)
            continue
```

**Critical exception:** Candidates found via anchor+label pairing or anchor-driven BFS are **skipped** for keyword overlap validation — they were already validated by proximity to matching nodes. This handles cases like `<textarea>` elements that have no visible text.

### Strategy 4: Element-Type Validation (with TEXT-FIRST priority)

Extracts `element_hints` from parsed intent and maps them to expected HTML tags:

```python
    _HINT_TO_TAGS = {
        "input": ("input", "textarea"),
        "textarea": ("textarea",),
        "textbox": ("input", "textarea"),
        "button": ("button", "a"),
        "link": ("a",),
        "checkbox": ("input",),
        "radio": ("input",),
        "select": ("select",),
        "combobox": ("select", "input"),
        "option": ("option", "li"),
        "menuitem": ("li", "a"),
        "tab": ("button", "a"),
        "icon": ("i", "svg", "span", "img"),
        "img": ("img",),
    }
```

**Tag mismatch handling — TEXT-FIRST principle:**

When a candidate's tag doesn't match the expected element type:
1. **Check for matching ARIA role** (e.g., `role="textbox"`) → accept
2. **Check for contenteditable** (`contenteditable="true"` or `"plaintext-only"`) → accept
3. **Check for strong text match** against the query:
   - Gather all text from: `text`, `innerText`, `text_own_norm`, `text_content_raw`, `text_desc_norm`, `aria-label`, `title`, `placeholder`
   - If exact substring match → **no penalty** (TEXT-FIRST)
   - If 80%+ word overlap → **no penalty**
4. **Otherwise:** Apply **92% score penalty** (`score * 0.08`)

```python
    _ROLE_PASS = ("textbox", "searchbox", "combobox", "listbox", ...)

    if not (role and role in _ROLE_PASS) and not _is_contenteditable:
        # Check text match...
        if _has_strong_text_match:
            logger.debug("[relevance_filter] SKIP penalty %s — tag '%s' not in hints %s "
                        "but STRONG text match → keep score %.2f", ...)
        else:
            r["score"] = old_score * 0.08  # ~92% penalty
```

### Final: Cap & Return

```python
    logger.info(
        "[relevance_filter] %d/%d candidates passed (top_score=%.2f, abs=%.2f, rel=%.2f)",
        len(filtered), len(results), top_score, min_abs_score, rel_threshold,
    )
    return filtered[:max_candidates]
```

---

## FUNCTION 6: _extract_search_keywords (lines 378–437)

```python
def _extract_search_keywords(parsed_intent: Optional[dict], field_name: str) -> set:
    """
    Build a set of lowercase keywords from the structured intent.

    Tokens from "target.text", "label.text", and the LLM "keywords"
    array are treated as "primary" search terms and are kept regardless of
    length (even ≤3 char abbreviations like "cm", "rx"). Tokens derived
    from the free-form "field_name" are secondary and must be > 3 chars
    to avoid noise from short prepositions / articles.
    """
    # --- Primary sources: keep ALL tokens (no length filter) ---
    primary_texts: list[str] = []
    if parsed_intent and isinstance(parsed_intent, dict):
        target = parsed_intent.get("target") or {}
        primary_texts.append(target.get("text") or "")
        label = parsed_intent.get("label") or {}
        primary_texts.append(label.get("text") or "")
        # Also keep placeholder as a primary source
        primary_texts.append(target.get("placeholder") or "")
        # Don't include anchor text — anchor is a region qualifier, not a keyword
        # that should appear on the target element itself.
        # DO include LLM-produced keywords array — these are curated search
        # tokens that should be used for relevance validation.
        intent_keywords = parsed_intent.get("keywords") or []
        if isinstance(intent_keywords, list):
            for kw in intent_keywords:
                if isinstance(kw, str) and kw.strip():
                    primary_texts.append(kw.strip())

    #  Secondary source: field name (apply length filter) ---
    secondary_texts: list[str] = []
    if field_name:
        secondary_texts.append(field_name)
        secondary_texts.append(field_name)

    # Tokenize and filter
    _STOP = {"the", "a", "for", "from", "with", "that", "this", "into",
             "under", "above", "below", "next", "near", "input", "field",
             "button", "click", "clicks", "enter", "type", "select",
             "choose", "which", "please", "in", "label", "labelled", "section",
             "user", "opens", "press", "tap", "hover", "toggle", "on", "in"}
    keywords = set()

    # Primary tokens: keep even if short, skip only stop words
    for txt in primary_texts:
        for token in str(txt).lower().split():
            token = token.strip(".,;:!?()[]{}'\"")
            if token and token not in _STOP:
                keywords.add(token)

    # Secondary tokens: require length ≥ 3
    for txt in secondary_texts:
        for token in str(txt).lower().split():
            token = token.strip(".,;:!?()[]{}'\"")
            if len(token) >= 3 and token not in _STOP:
                keywords.add(token)

    return keywords
```

**Key design decisions:**
- Primary sources (intent target text, label text, LLM keywords) keep **all tokens** regardless of length
- Secondary source (field_name) requires **length ≥ 3** to filter short noise
- Explicit stop word list includes UI action words: "click", "enter", "type", "select", "toggle", etc.
- **Anchor text deliberately excluded** — it's a region qualifier, not a keyword for the target element

---

## FUNCTION 7: _has_keyword_overlap (lines 440–478)

```python
def _has_keyword_overlap(meta: dict, keywords: set) -> bool:
    """
    Check if any of the node's text-bearing fields contain at least one keyword.

    IMPORTANT: many interactive elements (buttons, links) have empty own text
    but carry descendant text in "text_content_raw" / "text_desc_norm" /
    "text_own_norm" (e.g. "<button><span>CLOSE ALL</span></button>").
    We must include these fields to avoid falsely dropping valid candidates.
    """
    if not meta or not keywords:
        return True  # No keywords → can't filter

    attrs = meta.get("attrs", {}) or {}
    # Gather all searchable text from the node — including descendant text
    # Fields that StructuredSearch._collect_searchable_text also uses.
    searchable_parts = [
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
    # For class, only include if it's semantic (not huge random hashes)
    cls = attrs.get("class", "")
    if isinstance(cls, list):
        cls = " ".join(cls)
    if len(str(cls)) < 200:
        searchable_parts.append(str(cls))

    blob = " ".join(str(p).lower() for p in searchable_parts if p)

    for kw in keywords:
        if kw in blob:
            return True
    return False
```

**Key details:**
- Includes **11 text-bearing fields** from metadata + attrs
- Class names included only if **< 200 chars** (filters out huge random hashes)
- Returns `True` (pass) if no keywords provided — can't filter
- Checks all fields that `StructuredSearch._collect_searchable_text` also uses (consistency)

---

## FUNCTION 8: _highlight_element_on_page (lines 485–551)

```python
async def _highlight_element_on_page(page, xpath: str, frame_url: str = "", frame_name: str = "") -> dict:
    """Try to locate the element by XPath on the Playwright page and highlight it.

    Returns a dict with:
    - success (bool)
    - match_count (int): number of elements matched by the xpath
    - error (str | None): error message if highlight failed
    """
    HIGHLIGHT_JS = """
    (element) => {
        // Save original styles so we can restore later
        const orig = element.style.cssText;
        element.style.outline = '3px solid #FF4444';
        element.style.outlineOffset = '2px';
        element.style.boxShadow = '0 0 12px 4px rgba(255, 68, 68, 0.5)';
        element.scrollIntoView({behavior: 'smooth', block: 'center'});
        // Pulse animation: flash twice then settle on a subtle highlight
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
                // Settle on a persistent subtle highlight
                element.style.outline = '2px dashed #FF4444';
                element.style.outlineOffset = '2px';
                element.style.boxShadow = '0 0 6px 2px rgba(255, 68, 68, 0.3)';
            }
        }, 350);
    }
    """
    try:
        # Determine the target frame
        target_frame = page
        if frame_url or frame_name:
            for frame in page.frames:
                if frame_url and frame.url and frame_url in frame.url:
                    target_frame = frame
                    break
                if frame_name and frame.name == frame_name:
                    target_frame = frame
                    break

        # Count matches
        elements = await target_frame.locator(f"xpath={xpath}").all()
        match_count = len(elements)
        logger.info("[highlight] XPath '%s' matched %d element(s)", xpath, match_count)

        if match_count == 0:
            return {"success": False, "match_count": 0, "error": f"XPath matched 0 elements on the live page. The locator may be incorrect."}

        # Highlight the first match
        first_el = elements[0]
        await first_el.evaluate(HIGHLIGHT_JS)
        logger.info("[highlight] Element highlighted successfully.")
        return {"success": True, "match_count": match_count, "error": None}

    except Exception as e:
        err_msg = str(e)
        logger.warning("[highlight] Failed to highlight element: %s", err_msg)
        return {"success": False, "match_count": 0, "error": err_msg}
```

**Key details:**
- Visual feedback: red outline + box shadow, pulse animation (6 cycles @ 350ms), settles to dashed outline
- Frame-aware: resolves `frame_url` or `frame_name` before locating
- Returns structured result with `success`, `match_count`, `error`

---

## FUNCTION 9: _clean_llm_response (lines 555–592)

```python
def _clean_llm_response(llm_response: str) -> str:
    """Extract JSON string from an LLM response that may contain code fences or preamble."""
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
            for i, char in enumerate(cleaned[json_start:], start=json_start):
                if char == "{":
                    brace_count += 1
                elif char == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        json_end = i + 1
                        break
            if json_end != -1:
                cleaned = cleaned[json_start:json_end].strip()

    return cleaned
```

**Logic:**
1. Strip `\`\`\`json ... \`\`\`` fences
2. Strip plain `\`\`\` ... \`\`\`` fences
3. If still not starting with `{`, find the first balanced `{}` block via brace counting
4. Return cleaned JSON string

---

## FUNCTION 10: _extract_context (lines 596–611+)

```python
# Helper to extract standardized context from kwargs
def _extract_context(context: Dict[str, Any]) -> dict:
    run_id = (context.get("run_id") or "").strip()
    seal_id = (context.get("seal_id") or "").strip()
    # Accept either project_name or legacy proj_name
    project_name = (context.get("project_name") or context.get("proj_name") or "").strip()
    component_name = (context.get("component_name") or "").strip() or "default_component"
    # Final sanitization (basic) — remove whitespace-only tokens
    if not component_name.strip():
        component_name = "default_component"
    return {
        "run_id": run_id,
        "seal_id": seal_id,
        "project_name": project_name,
        "component_name": component_name,
    }
```

**Logic:** Standardize context dict with `run_id`, `seal_id`, `project_name`, `component_name`. Supports legacy `proj_name` key.

---

## ARCHITECTURAL NOTES

### Where this file sits in the pipeline

```
Phase 5: Element Locator Pipeline
  Step A:   Cache lookup → word_similarity
  Step A.5: is_scraping_required() → scope_web_page.py
  Step B:   DOMSemanticParser.run_full_sequence()
  Step B2:  KnowledgeGraph.load_parsed_structure() → NetworkX graph
  Step C:   LLM Call #3 — Intent Extraction
  Step D:   StructuredSearch.search() → scored candidates
  ─────────────────────────────────────────────────────
  ▶ THIS FILE provides helpers used between D and F:
    • _filter_relevant_candidates() — prune scored candidates
    • _trim_prompt_context_to_token_limit() — fit into LLM context
    • _extract_search_keywords() — build keyword set for validation
    • _has_keyword_overlap() — validate candidates have textual match
    • _highlight_element_on_page() — visual feedback
    • _clean_llm_response() — parse LLM output
    • _extract_context() — standardize run context
  ─────────────────────────────────────────────────────
  Step E:   build_subtree_context_locatable_v2() — rich context
  Step F:   LLM Call #4 — Locator Generation
  Step G:   Validate (frame.locator(xpath).count())
```

### Key design patterns

1. **TEXT-FIRST filtering** — text match on the element overrides tag mismatch penalties.
   A `<div>` with exact text match keeps its score even if intent says "button".

2. **Proximity-found exception** — candidates found via anchor+label BFS skip keyword
   overlap validation. A `<textarea>` near a matching label has no text to match.

3. **Token budget management** — 50K token limit with score-based trimming.
   Unknown-score subtrees are preserved (fail-safe), lowest scores dropped first.

4. **92% penalty (not removal)** — tag-mismatched candidates aren't deleted,
   just heavily penalized. They can still win if nothing else matches.

5. **Stop words include UI verbs** — "click", "enter", "type", "select", "toggle"
   are filtered from keywords so they don't pollute element matching.

---

## MAIN ORCHESTRATION FUNCTION (lines ~641–1237)

This is the **entry point** for the entire element locator pipeline. ~600 lines.

### Setup: DOM Parsing → KnowledgeGraph (lines ~641–660)

```python
    application_filename = f"{seal_id}_{project_name}_{component_name}_{formatted_title}_{run_id}.json"
    logger.info(f"Application filename: {application_filename}")
    parsing_start_time = time.time()
    results = []
    parser = DOMSemanticParser(verbose=True)
    parser.setPage(page)
    tree = await parser.run_full_sequence(application_filename)
    logger.info(f"DOM parsing completed in {time.time() - parsing_start_time:.2f} seconds.")

    # Convert parsed output to KnowledgeGraph
    logger.info("Converting parsed structure to KnowledgeGraph...")
    kg_conversion_start_time = time.time()
    kg = KnowledgeGraph()
    kg.load_parsed_structure(tree)
    kg.convert_to_graph()
    logger.info(f"Completed KnowledgeGraph conversion in {time.time() - kg_conversion_start_time:.2f} seconds.")
```

**Flow:** DOMSemanticParser → parsed tree → KnowledgeGraph → NetworkX graph

### Debug Logging (commented out, lines ~662–670)

```python
    # with open(f"kg_debug_{seal_id}_{project_name}_{component_name}_{formatted_title}_{run_id}.log", "w", encoding="utf-8") as debug_log:
    #     debug_log.write(f"Field to locate: name={field_name}, type={field_type}, action={action}, description={field_description}\n")
    #     debug_log.write("Knowledge Graph Nodes:\n")
    #     for node_id in kg.nodes:
    #         meta = kg.node_metadata.get(node_id, {})
    #         debug_log.write(f"Node ID: {node_id}, Metadata: {json.dumps(meta, ensure_ascii=False)}\n")
    #     debug_log.write("Knowledge Graph Relations:\n")
    #     for rel in kg.relations:
    #         debug_log.write(f"Relation from {rel[0]} to {rel[1]}, type: {rel[1]}\n")
```

### Step C: LLM Call #3 — Intent Extraction (lines ~672–731)

```python
    # Use the enhanced intent prompt from StructuredSearch module
    intent_instructions = ENHANCED_INTENT_PROMPT_TEMPLATE.replace(
        "__USER_QUERY__", field_description if isinstance(field_description, str) else field_name
    )

    access_token_time = time.time()
    set_access_token()
    openai()  # Ensure OpenAI client is initialized
    logger.info(f"Access token set in {time.time() - access_token_time:.2f} seconds.")

    kw_extraction_start_time = time.time()
    parsed_intent = None
    search_terms = [field_name]
    try:
        # CALL LLM API for structured intent
        intent_resp = call_using_ol_model_azure_openai(
            intent_instructions,
            user_query=f"Parse intent for locating {field_name} of type {field_type} to perform action {action}."
        )

        logger.info(f"Raw intent extraction response: {intent_resp}")

        # Parse the response
        _cleaned = (intent_resp or "").strip()
        if _cleaned.startswith("```"):
            # Strip code fence
            _cleaned = _cleaned.lstrip("`").lstrip("json").lstrip("\n")
            _end = _cleaned.rfind("```")
            if _end != -1:
                _cleaned = _cleaned[:_end].strip()
            try:
                parsed_intent = json.loads(_cleaned)
            except Exception:
                # Fallback: try to find JSON object in the response
                _start = _cleaned.find("{")
                if _start != -1:
                    _brace = 0
                    _json_end = -1
                    for _i, _ch in enumerate(_cleaned[_start:], start=_start):
                        if _ch == "{":
                            _brace += 1
                        elif _ch == "}":
                            _brace -= 1
                            if _brace == 0:
                                _json_end = _i + 1
                                break
                    if _json_end != -1:
                        try:
                            parsed_intent = json.loads(_cleaned[_start:_json_end])
                        except Exception:
                            pass

        if parsed_intent and isinstance(parsed_intent, dict):
            logger.info(f"Parsed intent: {json.dumps(parsed_intent, indent=2)}")
            # Extract fallback keywords from intent
            kw_from_intent = parsed_intent.get("keywords") or []
            target_text = (parsed_intent.get("target") or {}).get("text") or ""
            label_text = ((parsed_intent.get("label") or {}).get("text") or "") if parsed_intent.get("label") else ""
            anchor_text = ((parsed_intent.get("anchor") or {}).get("text") or "") if parsed_intent.get("anchor") else ""
            # Build search terms from intent for fallback
            fallback_terms = []
            if isinstance(kw_from_intent, list):
                fallback_terms = [str(kw) for kw in kw_from_intent if isinstance(kw, str)]
            if label_text:
                fallback_terms.append(label_text[:64])
            if target_text:
                fallback_terms.append(target_text[:64])
            if anchor_text:
                fallback_terms.append(anchor_text[:64])
            search_terms = fallback_terms if fallback_terms else [field_name]
        else:
            logger.warning("Failed to parse structured intent; falling back to keyword mode.")
            # Attempt to extract keywords from the raw response as fallback
            import re
            m = re.findall(r'"\{[^"}]+\}"', intent_resp or '')
            if m:
                search_terms = [kw[:64] for kw in m[:3]]
    except Exception as e:
        logger.exception("Error during intent extraction; falling back to keywords.")
        search_terms = [field_name]

    logger.info(f"Extracted search terms: {search_terms}")
    logger.info(f"Intent extraction completed in {time.time() - kw_extraction_start_time:.2f} seconds.")
```

**Key points:**
- Uses `ENHANCED_INTENT_PROMPT_TEMPLATE` from StructuredSearch module
- User query format: `"Parse intent for locating {field_name} of type {field_type} to perform action {action}."`
- Robust JSON extraction with code fence handling + brace-counting fallback
- Extracts `target_text`, `label_text`, `anchor_text`, `keywords` from intent
- Falls back to regex keyword extraction if intent parsing fails entirely

### Step D: PRIMARY PATH — StructuredSearch (lines ~755–772)

```python
    # PRIMARY PATH: StructuredSearch — two-phase target + anchor search
    results_k = []
    heuristic_search_start_time = time.time()
    structured_query: Optional[StructuredQuery] = None

    if parsed_intent and isinstance(parsed_intent, dict):
        try:
            structured_query = IntentQueryBuilder.build(parsed_intent)
            logger.info(f"[StructuredSearch] Built query: %s", structured_query.summary())

            ss_engine = StructuredSearchEngine(kg)
            results_k = ss_engine.search(structured_query, top_k=10, prefer_visible=True)
            logger.info("[StructuredSearch] Returned %d candidates", len(results_k))
        except Exception:
            logger.exception("[StructuredSearch] Failed; Falling back to EmbeddingEngine")
            results_k = []
```

**Key:** `IntentQueryBuilder.build(parsed_intent)` → `StructuredSearchEngine(kg).search()` with `top_k=10, prefer_visible=True`

### FALLBACK: EmbeddingEngine (lines ~775–792)

```python
    # FALLBACK: EmbeddingEngine intent-aware / heuristic search
    if not results_k:
        logger.info("Falling back to EmbeddingEngine search...")
        engine = EmbeddingEngine(kg, embedding_cache="embedding_cache.json")

        if parsed_intent and isinstance(parsed_intent, dict) and (parsed_intent.get("target") or parsed_intent.get("label")):
            logger.info("Using EmbeddingEngine intent-aware search with anchor/label proximity...")
            results_k = engine.search_with_intent(parsed_intent, top_k=10, prefer_visible=True)
            logger.info(f"EmbeddingEngine intent search returned {len(results_k)} candidates.")

        if not results_k:
            logger.info("Falling back to keyword-based heuristic search...")
            for term in search_terms:
                logger.info(f"Searching using term: {term}")
                results_k += engine.search_heuristic(term, top_k=10)
            if not results_k:
                results_k = engine.search_heuristic(field_name, top_k=10)
```

**Fallback chain:** StructuredSearch → EmbeddingEngine intent-aware → EmbeddingEngine keyword heuristic

### De-duplication & Pre-filter Diagnostics (lines ~794–811)

```python
    # De-duplicate nodes across multiple keyword searches by keeping the best score per node.
    best_by_node = {}
    for r in results_k:
        nid = r.get("node_id")
        if not nid:
            continue
        if nid not in best_by_node or float(r.get("score", 0)) > float(best_by_node[nid].get("score", 0)):
            best_by_node[nid] = r
    results_k = sorted(best_by_node.values(), key=lambda x: float(x.get("score", 0)), reverse=True)

    # Pre-filter diagnostics
    logger.info("Before relevance filter — %d candidates:", len(results_k))
    for r in results_k:
        meta = r.get("metadata", {}) or {}
        txt_preview = (meta.get("text") or meta.get("innerText") or meta.get("text_content_raw") or meta.get("text_desc_norm") or '')[:60]
        logger.info("  pre-filter: %s  score=%.2f  tag=%s  txt=%r",
                    r.get("node_id", ""), float(r.get("score", 0.0)),
                    meta.get("tag", ""), txt_preview,
                    )
```

### Relevance Filter (lines ~813–822)

```python
    # Relevance filter: prune garbage candidates before building context
    unfiltered_top = results_k[:5]  # safety copy before filtering
    results_k = _filter_relevant_candidates(
        results_k,
        parsed_intent=parsed_intent,
        field_name=field_name,
        max_candidates=5,
        min_abs_score=1.0,
        min_relative_pct=0.10,
    )
```

### Safety Fallback: Supplemental Keyword Search (lines ~824–862)

```python
    # Safety fallback: when the filter drops everything, try supplemental
    # keyword search using the intent keywords before restoring bad candidates.
    if not results_k:
        if parsed_intent and isinstance(parsed_intent, dict):
            intent_kws = parsed_intent.get("keywords") or []
            label_text = ((parsed_intent.get("label") or {}).get("text") or "").strip()
            if label_text and label_text not in intent_kws:
                intent_kws = [label_text] + list(intent_kws)
            if intent_kws:
                logger.warning("Relevance filter dropped ALL candidates — trying supplemental keyword search with intent keywords: %s", intent_kws)
                from EmbeddingEngine import EmbeddingEngine as EE_Fallback
                _fb_engine = EE_Fallback(kg, embedding_cache="embedding_cache.json")
                _fb_results = []
                for kw in intent_kws:
                    if isinstance(kw, str) and kw.strip():
                        _fb_results += _fb_engine.search_heuristic(kw.strip(), top_k=5)
                # De-duplicate
                _fb_best = {}
                for r in _fb_results:
                    nid = r.get("node_id")
                    if nid and (nid not in _fb_best or float(r.get("score", 0)) > float(_fb_best[nid].get("score", 0))):
                        _fb_best[nid] = r
                _fb_sorted = sorted(_fb_best.values(), key=lambda x: float(x.get("score", 0)), reverse=True)
                results_k = _filter_relevant_candidates(
                    _fb_sorted,
                    parsed_intent=parsed_intent,
                    field_name=field_name,
                    max_candidates=5,
                    min_abs_score=0.5,
                    min_relative_pct=0.05,
                )
                if results_k:
                    logger.info("Supplemental keyword search recovered %d candidates.", len(results_k))

        # Final fallback: if supplemental search also found nothing, keep top 3 unfiltered.
        if not results_k and unfiltered_top:
            logger.warning("Supplemental search also failed — falling back to top %d unfiltered.",
                          min(3, len(unfiltered_top)))
            results_k = unfiltered_top[:3]
```

**3-tier fallback:**
1. Re-run keyword search with intent keywords (lower thresholds: `min_abs_score=0.5, min_relative_pct=0.05`)
2. If still empty, keep top 3 unfiltered candidates
3. Never proceed with zero candidates

### Post-Filter: Element-Type Preference Sorting (lines ~864–907)

```python
    # Post-filter: element-type preference sorting
    # When intent specifies element hints (e.g. input/textarea), push
    # candidates whose tag matches to the top regardless of raw score.
    # This ensures the safety fallback (unfiltered_top) doesn't surface
    # headings or labels above actual input/textarea elements.
    if parsed_intent and isinstance(parsed_intent, dict):
        _hints = (parsed_intent.get("target") or {}).get("element_hints") or []
        _HINT_TAG_MAP = {
            "input": ("input", "textarea"), "textarea": ("textarea",),
            "textbox": ("input", "textarea"), "button": ("button", "a"),
            "link": ("a",), "checkbox": ("input",), "radio": ("input",),
            "select": ("select",), "combobox": ("select", "input"),
            "option": ("option", "li"), "menuitem": ("li", "a"),
            "tab": ("button", "a"), "icon": ("i", "svg", "span", "img"),
        }
        _preferred_tags = set()
        for h in _hints:
            h_low = h.strip().lower()
            _preferred_tags.update(_HINT_TAG_MAP.get(h_low, {h_low}))

        if _preferred_tags:
            # Build label-ID ancestor lookup —
            # When the intent has a label (e.g., "Overview"), check which
            # candidates are inside a container whose 'id' matches that
            # label text (e.g. div#OVERVIEW). Those get top priority.
            _label_id_upper = ""
            _label_info = parsed_intent.get("label") or {}
            if isinstance(_label_info, dict):
                _label_id_upper = (_label_info.get("text") or "").strip().upper()

            def _is_inside_label_container(nid: str) -> bool:
                """Walk ancestors to check if any has id matching label text."""
                if not _label_id_upper:
                    return False
                cur = kg.parent_of.get(nid)
                _depth = 0
                while cur and _depth < 30:
                    anc_meta = kg.node_metadata.get(cur, {})
                    anc_attrs = anc_meta.get("attrs", {}) or {}
                    anc_id = (anc_attrs.get("id") or "").strip()
                    if anc_id and anc_id.upper() == _label_id_upper:
                        return True
                    cur = kg.parent_of.get(cur)
                    _depth += 1
                return False
```

### Text-Match Check & Sorting (lines ~908–975)

```python
            # Build target text for text-match check
            _sort_target_text = ""
            if parsed_intent and isinstance(parsed_intent, dict):
                _sort_target_text = ((parsed_intent.get("target") or {}).get("text") or "").strip().lower()
                # Also consider placeholder from intent
            if not _sort_target_text:
                _sort_target_text = ((parsed_intent.get("target") or {}).get("placeholder") or "").strip().lower()

            def has_text_match(r):
                """Check if the candidate's visible text closely matches the query."""
                if not _sort_target_text:
                    return False
                meta = r.get("metadata") or {}
                attrs = meta.get("attrs", {}) or {}
                _texts = [
                    (meta.get("text") or ""),
                    (meta.get("innerText") or ""),
                    (meta.get("text_own_norm") or ""),
                    (meta.get("text_desc_norm") or ""),
                    (meta.get("text_content_raw") or ""),
                    (attrs.get("aria-label") or ""),
                    (attrs.get("title") or ""),
                    (attrs.get("placeholder") or ""),
                ]
                _all = " ".join(str(t).lower() for t in _texts if t)
                if _sort_target_text in _all:
                    return True
                _q_words = {w for w in _sort_target_text.split() if len(w) >= 3}
                if _q_words:
                    _m = sum(1 for w in _q_words if w in _all)
                    if _m >= len(_q_words) * 0.8:
                        return True
                return False
```

### Style/Script Pollution Detection & XPath Fixing (lines ~975–1050)

```python
    # Pollution-safe XPath fixer
    import re as regex_module

    _FORBIDDEN_XPATH_PATTERNS = [
        (r'\bjss\d+\b', 'JSS class'),
        (r'\bMui[A-Z][a-zA-Z]*-[\w]+\b', 'MUI class'),
        (r'\bsc-[a-zA-Z]{6,}\b', 'styled-components class'),
        (r'\bcss-[a-z0-9]{6,}\b', 'Emotion class'),
        (r'\b[a-zA-Z]+_[a-zA-Z]+_[a-zA-Z0-9]{5}\b', 'CSS module class'),
    ]

    # Pollution-safe XPath fixer
    # When the context shows has style_script pollution on any node in
    # the target subtree, normalize-space(.)='exact' will FAIL in real
    # browsers because XPath's '.' includes <style>/<script> text.
    # We auto-fix these patterns to contains(., 'text') instead.
    _NORMALIZE_EXACT_RE = regex_module.compile(
        r"normalize-space\((\.\s*|\s*\.\s*)\)\s*=\s*(['\"])(.*?)\2"
    )

    def _has_pollution_in_context(ctx: dict) -> bool:
        """Check if any subtree's target or node chain has style_script pollution."""
        for subtree in (ctx or {}).get("context_subtrees", []):
            ts = subtree.get("target_summary") or {}
            if ts.get("has_style_script_pollution"):
                return True
            for node in subtree.get("node_chain", []):
                meta = node.get("metadata") or {}
                if meta.get("has_style_script_pollution"):
                    return True
        return False

    def _fix_pollution_xpath(xpath: str) -> str:
        """Replace normalize-space(.)='X' with contains(., 'X') to handle pollution."""
        def _repl(m):
            text_val = m.group(3)
            return f"contains(., '{text_val}')"
        return _NORMALIZE_EXACT_RE.sub(_repl, xpath)

    def _parse_and_validate_locator(raw_response: str):
        """Parse LLM response → locator_data dict. Returns (locator_data, error_reason or None)."""
        cleaned = _clean_llm_response(raw_response)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            return None, f"Failed to parse LLM response as JSON: {e}"

        st = data.get("status", "found")
        if st in ("no_match", "error"):
            return data, data.get("reasoning", "LLM returned no_match / error status.")

        xp = data.get("xpath", "")
        for pat, pat_name in _FORBIDDEN_XPATH_PATTERNS:
            m = regex_module.search(pat, xp)
            if m:
                return None, f"Generated XPath contained forbidden {pat_name} '{m.group()}'. Original xpath: {xp}"

        # Auto-fix style/script pollution: replace normalize-space(.)='X'
        # with contains(., 'X') when context has polluted nodes.
        if xp and _has_pollution_in_context(prompt_context):
            fixed_xp = _fix_pollution_xpath(xp)
            if fixed_xp != xp:
                logger.info(
                    "[pollution-fix] Auto-fixed XPath for style/script pollution:\n"
                    "  BEFORE: %s\n  AFTER: %s", xp, fixed_xp,
                )
            data["xpath"] = fixed_xp
            # Also fix element_handler if it contains the xpath
            handler = data.get("element_handler", "")
            if handler and xp in handler:
                data["element_handler"] = handler.replace(xp, fixed_xp)

        return data, None
```

**Critical feature:** Auto-detects `style_script_pollution` in context subtrees and rewrites
`normalize-space(.)='exact'` → `contains(., 'exact')` to prevent XPath failures in browsers
where `<style>`/`<script>` text leaks into `.` text content.

### LLM Call #4 — Locator Generation (lines ~1060–1070)

```python
    #     prompt_log.write(user_query_text)
    llm_response = call_using_ol_model_azure_openai(assistant_instructions)
    logger.info(f"LLM response received in {time.time() - llm_query_start_time:.2f} seconds.")
    logger.info(f"Raw LLM response: {llm_response}")
    logger.info("User Query: " + (field_description if isinstance(field_description, str) else f"Locate the element with name: {field_name}"))
```

### Parse, Validate & Highlight (lines ~1073–1168)

```python
    # Parse, validate, and highlight the LLM locator
    locator_data, validation_error = _parse_and_validate_locator(llm_response)

    if locator_data and not validation_error:
        xpath = locator_data.get("xpath", "")
        if xpath:
            highlight_result = await _highlight_element_on_page(
                page, xpath,
                frame_url=locator_data.get("frame_url", ""),
                frame_name=locator_data.get("frame_name", ""),
            )
            if highlight_result["success"]:
                locator_data["match_count"] = highlight_result["match_count"]
            else:
                logger.warning(
                    "[highlight-check] XPath '%s' could not be located on the live page. "
                    "Error: %s  Match count: %s",
                    xpath, highlight_result["error"], highlight_result["match_count"],
                )
```

### Build Final Locator Data (lines ~1170–1237)

```python
    # Build final locator data if parsing/validation failed
    if locator_data is None:
        locator_data = {
            "status": "error",
            "confidence": "low",
            "name": "",
            "visible_text": "",
            "frame_url": "",
            "frame_name": "",
            "frame_selector": "",
            "xpath": "",
            "associated_element_type": "",
            "element_handler": "",
            "match_count": 0,
            "reasoning": validation_error or "Failed to generate a valid locator.",
            "suggestions": ["Retry the request or provide more specific element description"]
        }
    results.append({
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "user_prompt": f"Locate the element with description: {field_description if isinstance(field_description, str) else field_name}",
        "llm_response": llm_response,
        "status": "error",
    })
    logger.info(f"Scraping by knowledge graph completed (error) in {time.time() - start_time:.2f} seconds.")
    return locator_data, time.time() - start_time

    # Handle no match / error status from the locator
    status = locator_data.get("status", "found")
    if status in ("no_match", "error"):
        logger.warning(f"LLM could not confidently locate element: {locator_data.get('reasoning', 'No reason provided')}")
        results.append({
            "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
            "user_prompt": f"Locate the element with description: {field_description if isinstance(field_description, str) else field_name}",
            "llm_response": llm_response,
            "status": status,
        })
        logger.info(f"Scraping by knowledge graph completed (no match) in {time.time() - start_time:.2f} seconds.")
        return locator_data, time.time() - start_time

    # Process successful match
    llm_field_type = locator_data.get("associated_element_type", "custom")
    if isinstance(locator_data, dict):
        locator_data["associated_element_type"] = llm_field_type if llm_field_type in ["input", "icon"] else "text"
        if "status" not in locator_data:
            locator_data["status"] = "found"
        if "confidence" not in locator_data:
            locator_data["confidence"] = "high"
        # Default frame_url to the current page URL when frame_url or frame_name is empty
        if not locator_data.get("frame_url") or not locator_data.get("frame_name"):
            locator_data["frame_url"] = page_url

    logger.info(f"Locator data to append after processing: {locator_data}")

    # Aggregate responses to a JSON array on disk
    results.append({
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "user_prompt": f"Locate the element with description: {field_description if isinstance(field_description, str) else field_name}",
        "llm_response": llm_response,
        "status": "found",
    })
    logger.info(f"Scraping by knowledge graph completed in {time.time() - start_time:.2f} seconds.")

    try:
        parsed_llm = json.loads(llm_response)
    except Exception:
        parsed_llm = None
    logger.info(f"New locators added: {locator_data} | parsed_llm={parsed_llm}")

    return locator_data, time.time() - start_time
```

---

## COMPLETE PIPELINE FLOW (as implemented in this file)

```
┌─────────────────────────────────────────────────┐
│  scrape_by_knowledge_graph() entry point        │
├─────────────────────────────────────────────────┤
│                                                 │
│  1. DOMSemanticParser.run_full_sequence()        │ ← Step B
│     → parsed DOM tree (JSON)                    │
│                                                 │
│  2. KnowledgeGraph()                            │ ← Step B2
│     → kg.load_parsed_structure(tree)            │
│     → kg.convert_to_graph()                     │
│                                                 │
│  3. LLM Call #3 — Intent Extraction             │ ← Step C
│     → ENHANCED_INTENT_PROMPT_TEMPLATE           │
│     → parsed_intent {target, label, anchor,     │
│       keywords, element_hints}                  │
│                                                 │
│  4. PRIMARY: StructuredSearchEngine(kg)         │ ← Step D
│     → IntentQueryBuilder.build(parsed_intent)   │
│     → ss_engine.search(query, top_k=10)         │
│     FALLBACK 1: EmbeddingEngine.search_with_intent()
│     FALLBACK 2: EmbeddingEngine.search_heuristic()
│                                                 │
│  5. De-duplicate by node_id (best score wins)   │
│                                                 │
│  6. _filter_relevant_candidates()               │
│     → 4-strategy pruning (abs/rel/keyword/tag)  │
│     SAFETY: supplemental keyword search         │
│     SAFETY: keep top 3 unfiltered               │
│                                                 │
│  7. Post-filter: element-type preference sort   │
│     → tag-matching candidates boosted to top    │
│     → label-ID ancestor lookup                  │
│     → text-match check                          │
│                                                 │
│  8. _trim_prompt_context_to_token_limit()       │
│     → 50K token budget enforcement              │
│                                                 │
│  9. LLM Call #4 — Locator Generation            │ ← Step F
│     → assistant_instructions.txt (~940 lines)   │
│     → call_using_ol_model_azure_openai()        │
│                                                 │
│  10. _parse_and_validate_locator()              │
│      → JSON extraction                          │
│      → Forbidden pattern check (JSS/MUI/etc)    │
│      → Pollution auto-fix (normalize-space→     │
│        contains)                                │
│                                                 │
│  11. _highlight_element_on_page()               │ ← Visual verification
│      → Playwright locator count check           │
│      → JS highlight with pulse animation        │
│                                                 │
│  12. Return locator_data + elapsed_time         │
└─────────────────────────────────────────────────┘
```

---

## KEY DESIGN PATTERNS (full file)

1. **3-tier search fallback:** StructuredSearch → EmbeddingEngine intent-aware → EmbeddingEngine keyword heuristic. Never gives up.

2. **3-tier filter fallback:** Relevance filter → supplemental keyword search (lower thresholds) → keep top 3 unfiltered. Never proceeds with zero candidates.

3. **Pollution auto-fix:** Detects `style_script_pollution` flag in context subtrees and rewrites `normalize-space(.)='X'` → `contains(., 'X')` before returning the XPath. This handles React/Vue apps where `<style>` tags leak text into `.` content.

4. **Forbidden pattern validation:** Generated XPaths are checked against 5 regex patterns (JSS, MUI, styled-components, Emotion, CSS modules). If matched → reject + retry.

5. **Label-ID ancestor lookup:** When intent has a label like "Overview", checks if candidates are inside a container with `id="OVERVIEW"`. Those get priority.

6. **TEXT-FIRST principle (enforced twice):**
   - In `_filter_relevant_candidates()`: text match overrides tag penalty
   - In post-filter sorting: text-matching candidates sorted higher

7. **Timing instrumentation:** Every major step is timed with `time.time()` and logged.

---

## STATUS: FULLY CAPTURED (14 screenshots, lines 1–1237)

