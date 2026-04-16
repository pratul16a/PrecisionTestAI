# CAPTURE: StructuredSearch.py
## Transcription from 9 screenshots
## File: precisiontestai/src/playwright_mcp/code/web_selectors/StructuredSearch.py
## Coverage: Top + bottom of file with middle gaps flagged

---

## FILE SUMMARY

This file implements the **structured search engine** — the primary candidate-finding
mechanism in the element locator pipeline (Step D). It converts LLM-parsed intent
into typed queries and scores every node in the Knowledge Graph against those queries.

**Three main components:**
1. **Data Models** — `NodeMatchCriteria` and `StructuredQuery` dataclasses
2. **IntentQueryBuilder** — converts LLM parsed_intent dict → StructuredQuery
3. **StructuredSearchEngine** — two-phase search: target scoring + anchor proximity re-ranking

Also contains `ENHANCED_INTENT_PROMPT_TEMPLATE` — the **LLM Call #3 prompt** for intent extraction.

---

## DATA MODEL: NodeMatchCriteria (lines ~32–66)

```python
@dataclass
class NodeMatchCriteria:
    """Rich matching criteria for a single DOM node (target, label, or anchor).

    The search engine checks each criterion against node metadata:
    - "contains"  → partial / substring match on metadata fields
    - "equals"    → exact (case-insensitive) match on metadata fields
    - "tag_hints" → expected HTML tags (e.g. ["button", "a"])
    - "role_hints" → expected ARIA roles (e.g. ["checkbox", "radio"])
    - "properties" → boolean flags like isClickable, isInput, isVisible, isIcon ...
    - "spatial_position" → for anchor/label: spatial relation to target
    """

    # Text / attribute matching
    contains: Dict[str, str] = field(default_factory=dict)
    equals: Dict[str, str] = field(default_factory=dict)

    # Element type expectations
    tag_hints: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)

    # Behavioural / visual properties
    properties: Dict[str, bool] = field(default_factory=dict)

    # Spatial relation (only used for anchor/label relative to target)
    spatial_position: Optional[str] = None  # above | below | left_of | right_of | nearby

    def is_empty(self) -> bool:
        return (
            not self.contains
            and not self.equals
            and not self.tag_hints
            and not self.role_hints
            and not self.properties
        )
```

---

## DATA MODEL: StructuredQuery (lines ~69–104)

```python
@dataclass
class StructuredQuery:
    """Complete search query produced from user intent.

    Encapsulates target, optional label, and optional anchor criteria
    together with the intended action and fallback keywords.
    """
    action: str = ""  # click | type | select | hover | check | uncheck | toggle

    # Primary element the user wants to interact with
    target_node: NodeMatchCriteria = field(default_factory=NodeMatchCriteria)

    # Label: a nearby text/heading that identifies the target (e.g. input field's label)
    is_label_available: bool = False
    label_node: Optional[NodeMatchCriteria] = None

    # Anchor: a regional scoping container (section, tab, panel, dialog ...)
    is_anchor_available: bool = False
    anchor_node: Optional[NodeMatchCriteria] = None
    anchor_scope_type: str = ""  # e.g. "column", "section", "tab", etc.
    anchor_scope_type: str = ""  # e.g. "column", "section", "tab", etc.

    # Fallback keywords for heuristic search if structured matching fails
    keywords: List[str] = field(default_factory=list)

    def summary(self) -> str:
        """Human-readable one-liner for logging."""
        parts = [f"action={self.action}"]
        if not self.target_node.is_empty():
            parts.append(f"target(contains={self.target_node.contains}, eq={self.target_node.equals})")
        if self.is_label_available and self.label_node:
            parts.append(f"label(contains={self.label_node.contains}, pos={self.label_node.spatial_position})")
        if self.is_anchor_available and self.anchor_node:
            parts.append(f"anchor(contains={self.anchor_node.contains}, pos={self.anchor_node.spatial_position})")
        return " | ".join(parts)
```

---

## MAPPING TABLES (lines ~108–196)

### _ACTION_PROPERTY_MAP — Action → Property Expectations

```python
_ACTION_PROPERTY_MAP: Dict[str, Dict[str, bool]] = {
    "click":    {"isClickable": True},
    "type":     {"isInput": True},
    "fill":     {"isInput": True},
    "enter":    {"isInput": True},
    "select":   {"isInput": True},
    "check":    {"isCheckable": True},
    "uncheck":  {"isCheckable": True},
    "toggle":   {"isCheckable": True},
    "hover":    {"isVisible": True},
    "open":     {"isClickable": True},
    "search":   {"isClickable": True},
}
```

### _ELEMENT_HINT_EXPANSION — Hint → (tag_hints, role_hints, properties)

```python
_ELEMENT_HINT_EXPANSION: Dict[str, Tuple[List[str], List[str], Dict[str, bool]]] = {
    "button":       (["button", "a"],       ["button", "link"],     {"isClickable": True}),
    "link":         (["a"],                 ["link"],               {"isClickable": True}),
    "a":            (["a"],                 ["link"],               {"isClickable": True}),
    "input":        (["input", "textarea"], ["textbox", "searchbox"], {"isInput": True}),
    "textarea":     (["textarea"],          ["textbox"],            {"isInput": True}),
    "textbox":      (["input", "textarea"], ["textbox", "searchbox"], {"isInput": True}),
    "checkbox":     (["input"],             ["checkbox"],           {"isCheckable": True}),
    "radio":        (["input"],             ["radio"],              {"isCheckable": True}),
    "radiobutton":  (["input"],             ["radio"],              {"isCheckable": True}),
    "switch":       (["input"],             ["switch", "checkbox"], {"isCheckable": True}),
    "toggle":       (["input"],             ["switch", "checkbox"], {"isCheckable": True}),
    "select":       (["select", "input"],   ["combobox", "listbox"], {"isInput": True}),
    "combobox":     (["select", "input"],   ["combobox"],           {"isInput": True}),
    "listbox":      (["select"],            ["listbox"],            {"isInput": True}),
    "option":       (["option", "li"],      ["option"],             {}),
    "menuitem":     (["li", "a"],           ["menuitem"],           {"isClickable": True}),
    "tab":          (["button", "a"],       ["tab"],                {"isClickable": True}),
    "label":        (["label", "span"],     [],                     {}),
    "icon":         (["i", "svg", "span", "img"], [],               {"isIcon": True}),
    "img":          (["img"],               ["img"],                {}),
}
```

### _ANCHOR_SCOPE_EXPANSION — Scope Type → (tag_hints, role_hints)

```python
_ANCHOR_SCOPE_EXPANSION: Dict[str, Tuple[List[str], List[str]]] = {
    "section":  (["section", "div"],   ["region"]),
    "tab":      (["button", "a"],      ["tab", "tabpanel"]),
    "panel":    (["div", "section"],   ["tabpanel", "region"]),
    "menu":     (["ul", "div", "nav"], ["menu", "menubar", "navigation"]),
    "region":   (["section", "div"],   ["region"]),
    "dialog":   (["dialog", "div"],    ["dialog", "alertdialog"]),
    "form":     (["form"],             ["form"]),
    "toolbar":  (["div"],              ["toolbar"]),
    "sidebar":  (["aside", "div"],     ["complementary"]),
    "header":   (["header", "div"],    ["banner"]),
    "footer":   (["footer", "div"],    ["contentinfo"]),
    "nav":      (["nav", "div"],       ["nav"]),
    "row":      (["tr", "div"],        []),
    "column":   (["td", "th", "div"],  ["gridcell", "columnheader"]),
    "nearby":   ([],                   []),
}
```

### _RELATION_TO_SPATIAL — Natural Language → Spatial Position

```python
_RELATION_TO_SPATIAL: Dict[str, str] = {
    "below": "below",
    "above": "above",
    "left_of": "left_of",
    "right_of": "right_of",
    "next_to": "nearby",
    "for": "nearby",
    "under": "below",
    "in": "inside",
    "on": "inside",
    "inside": "inside",
    "within": "inside",
}
```

---

## CLASS: IntentQueryBuilder (lines ~198–340)

```python
class IntentQueryBuilder:
    """Converts an LLM-produced parsed_intent dict into a StructuredQuery."""

    @staticmethod
    def build(parsed_intent: Dict[str, Any]) -> StructuredQuery:
        """Parse the LLM intent JSON and produce a StructuredQuery.

        `parsed_intent` should follow the schema:
        {
            "action": "click",
            "target": {"text": "Submit", "element_hints": ["button"]},
            "label": {"text": "Description", "relation": "for"} | null,
            "anchor": {"scope_type": "section", "text": "Request Access", "relation": "under"} | null,
            "keywords": ["Submit"]
        }
        """
        if not parsed_intent or not isinstance(parsed_intent, dict):
            return StructuredQuery()

        action = (parsed_intent.get("action") or "").strip().lower()

        # --- Build target criteria ---
        target_info = parsed_intent.get("target") or {}
        target_text = (target_info.get("text") or "").strip()
        target_placeholder = (target_info.get("placeholder") or "").strip()
        target_placeholder = (target_info.get("placeholder") or "").strip()
        element_hints = target_info.get("element_hints") or []

        target = NodeMatchCriteria()

        # Text matching
        if target_text:
            target.contains["text"] = target_text
            target.equals["text"] = target_text

        # Placeholder matching — when the user refers to an input by its
        # placeholder text (e.g. "the Search box", "Enter email field").
        # Use it as the primary text criterion if no target.text is given,
        # or as a supplementary criterion alongside target.text.
        if target_placeholder:
            target.contains["placeholder"] = target_placeholder
            target.equals["placeholder"] = target_placeholder
            # If target has no visible text, use placeholder as the text
            # search criterion so _score_node matches it against the node's
            # placeholder attribute AND text fields.
            if not target_text:
                target.contains["text"] = target_placeholder
                target.equals["text"] = target_placeholder

        # Expand element hints into tag/role/property expectations
        all_tags: list[str] = []
        all_roles: list[str] = []
        all_props: Dict[str, bool] = {}

        for hint in element_hints:
            h = hint.strip().lower()
            if h in _ELEMENT_HINT_EXPANSION:
                tags, roles, props = _ELEMENT_HINT_EXPANSION[h]
                all_tags.extend(tags)
                all_roles.extend(roles)
                all_props.update(props)
            else:
                # Unknown hint — add as both tag and role guess
                all_tags.append(h)
                all_roles.append(h)

        target.tag_hints = list(dict.fromkeys(all_tags))  # dedupe preserving order
        target.role_hints = list(dict.fromkeys(all_roles))

        # Merge action-derived properties
        action_props = _ACTION_PROPERTY_MAP.get(action, {})
        all_props.update(action_props)
        target.properties = all_props

        # --- Build label criteria ---
        label_info = parsed_intent.get("label")
        # ... (label criteria building similar to target)
        # label_criteria.spatial_position = _RELATION_TO_SPATIAL.get(label_relation, "nearby")

        # --- Build anchor criteria ---
        anchor_info = parsed_intent.get("anchor")
        anchor_criteria: Optional[NodeMatchCriteria] = None
        is_anchor = False

        if anchor_info and isinstance(anchor_info, dict):
            anchor_text = (anchor_info.get("text") or "").strip()
            anchor_scope = (anchor_info.get("scope_type") or "").lower()
            anchor_relation = (anchor_info.get("relation") or "").strip().lower()

            if anchor_text:
                is_anchor = True
                anchor_criteria = NodeMatchCriteria()
                anchor_criteria.contains["text"] = anchor_text
                anchor_criteria.equals["text"] = anchor_text

                # Expand scope_type to tag/role hints
                if anchor_scope in _ANCHOR_SCOPE_EXPANSION:
                    a_tags, a_roles = _ANCHOR_SCOPE_EXPANSION[anchor_scope]
                    anchor_criteria.tag_hints = list(a_tags)
                    anchor_criteria.role_hints = list(a_roles)

                anchor_criteria.properties = {"isVisible": True}
                anchor_criteria.spatial_position = _RELATION_TO_SPATIAL.get(anchor_relation, "inside")

        # --- Keywords ---
        keywords = parsed_intent.get("keywords") or []
        if isinstance(keywords, list):
            keywords = [str(k).strip() for k in keywords if isinstance(k, str) and k.strip()]
        else:
            keywords = []

        # Determine anchor scope_type for grid-aware search
        _anchor_scope_type = ""
        if anchor_info and isinstance(anchor_info, dict):
            _anchor_scope_type = (anchor_info.get("scope_type") or "").strip().lower()

        return StructuredQuery(
            action=action,
            target_node=target,
            is_label_available=is_label,
            label_node=label_criteria,
            is_anchor_available=is_anchor,
            anchor_node=anchor_criteria,
            anchor_scope_type=_anchor_scope_type,
            keywords=keywords,
        )
```

---

## CLASS: StructuredSearchEngine (lines ~350+)

### Docstring & __init__

```python
class StructuredSearchEngine:
    """Searches the KG using a StructuredQuery in two phases:

    Phase 1 — Find target candidates:
        Score every node against "query.target_node" criteria.
        If "query.is_label_available", first find label nodes, then discover
        nearby elements matching target type hints (label-driven path).

    Phase 2 — Anchor proximity re-ranking:
        If "query.is_anchor_available", find anchor candidates and boost
        target nodes that are nearest to an anchor.

    Returns ranked list of "SearchResult" dicts.
    """

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
```

### search() — Main Entry Point

```python
    def search(
        self,
        query: StructuredQuery,
        top_k: int = 10,
        prefer_visible: bool = True,
    ) -> List[Dict[str, Any]]:
        """Execute the full two-phase search and return ranked results."""
        logger.info("[StructuredSearch] Starting search | %s", query.summary())

        # Determine strategy based on what the intent provides.
        # Priority:
        #   1. ANCHOR+LABEL PAIRING — target has no text, both anchor & label
        #      available → find anchor nodes & label nodes, pair by tree
        #      proximity, then discover targets near those pairs.
        #   2. ANCHOR-FIRST — target has no text, anchor_available (no label)
        #      → find anchor nodes, BFS for targets nearby.
        #   3. TEXT-FIRST — target has text → original label-driven + direct
        #      scoring flow.

        target_text = ""
        if query.target_node:
            target_text = (query.target_node.contains.get("text") or "").strip()

        _has_anchor = (
            query.is_anchor_available
            and query.anchor_node
            and not query.anchor_node.is_empty()
        )

        _has_label = (
            query.is_label_available
            and query.label_node
            and not query.label_node.is_empty()
        )

        # ---- GRID COLUMN strategy (must run FIRST) ----
        # In ag-Grid / data-grids, column headers and body cells are in
        # separate DOM subtrees linked by the 'col-id' attribute. BFS
        # from the header can never reach the body cells. When the
        # anchor scope type is 'column', explicitly search for gridcell
        # nodes with matching col-id.
        _grid_column_results: List[Dict[str, Any]] = []
        if _has_anchor and query.anchor_scope_type == "column":
            _grid_column_results = self._phase1_grid_column_search(
                query, top_k=top_k * 5, prefer_visible=prefer_visible,
            )
            if _grid_column_results:
                logger.info(
                    "[StructuredSearch] Grid-column search found %d cell candidates",
                    len(_grid_column_results),
                )

        # ---- CONTAINER-SCOPED strategy (semantic edge powered) ----
        # Uses the KG's containment edges to find elements inside
        # matching containers (form, dialog, sections, etc.)
        _container_results: List[Dict[str, Any]] = []
        if _has_anchor:
            _container_results = self._phase1_container_scoped_search(
                query, top_k=top_k * 3, prefer_visible=prefer_visible,
            )
            if _container_results:
                logger.info(
                    "[StructuredSearch] Container-scoped search found %d candidates",
                    len(_container_results),
                )

        # ---- LABEL-EDGE strategy (direct label_for associations) ----
```

**The search() method continues** with more strategies but the middle of the file is not shown.

---

## ENHANCED_INTENT_PROMPT_TEMPLATE (lines ~600–730)

This is the **LLM Call #3 prompt** — the full intent extraction prompt.

```python
ENHANCED_INTENT_PROMPT_TEMPLATE = """You are a QA assistant. Parse the user's UI interaction query into a structured intent object.

The intent object tells us:
1. **action**: What the user wants to do (click, type, select, hover, check, uncheck, toggle, open, search)
2. **target**: The element the user wants to interact with — its own visible text, expected element type, and behavioural properties
3. **label** (optional): A nearby label/heading that IDENTIFIES the target element (the target itself may have no text, e.g. an input or checkbox)
4. **anchor** (optional): A REGIONAL qualifier that scopes WHERE the target is located (section, tab, panel, dialog, menu...)

CRITICAL DISTINCTION — label vs anchor:
- **label** answers "which specific element?" — it is text ADJACENT to the target that NAMES it.
  Use label when the user says "below label X", "next to X", "labeled X", "field X", "Input X", "the X checkbox", or when the target element type (input/checkbox/radio) typically has no visible text of its own.
- **anchor** answers "in which region/area?" — it is a broader container or section.
  Use anchor when the user says "under X section", "in X tab", "on X panel", "in X dialog".
- A query can have BOTH a label AND an anchor, just one, or neither.

Output schema (STRICT JSON):

{
    "action": "<click|type|select|hover|open|search|toggle|check|uncheck>",
    "target": {
        "text": "<target's OWN visible text — empty string if no text (e.g. blank input)>",
        "placeholder": "<the input's placeholder/hint text if mentioned or implied by the user, e.g. 'Search...', 'Enter email' — empty string if not applicable>",
        "element_hints": ["<expected tag/role: checkbox, button, input, label, link, menuitem, option, tab, radio, select, textarea, icon, img>"],
        "properties": {
            "isClickable": <true|false>,
            "isInput": <true|false>,
            "isCheckable": <true|false>,
            "isIcon": <true|false>,
            "isVisible": true
        }
    },
    "label": {
        "text": "<visible text of the nearby label/heading>",
        "relation": "<below|above|next_to|left_of|right_of|for>"
    },
    "anchor": {
        "scope_type": "<section|tab|panel|menu|region|dialog|form|toolbar|sidebar|header|footer|row|column|nearby>",
        "text": "<visible text/label of the scoping region>",
        "relation": "<under|in|on|next_to|above|below|left_of|right_of|inside|within>"
    },
    "keywords": ["<kw1>", "<kw2>", "<kw3>"]
}...

Rules:
- "label" is null when there is NO nearby label mentioned (e.g., "Click Submit" — Submit IS the target text).
- "label" is populated when the user references a label/heading/text that is NOT the target element itself but identifies it.
- When "label" is set, target.text should be empty or contain only the target's own text, NOT the label text.
- "anchor" is null when the user provides NO regional qualifier.
- "keywords" are 1-3 compact search tokens for fallback heuristic search.
- "placeholder" in target: when the user refers to an input field by its placeholder/hint text
  (e.g., "the Search box", "Enter email field", "Type in Filter..."), extract that text into
  target.placeholder. This is especially important for inputs with no visible label. If the
  user doesn't reference placeholder text, leave it as an empty string.
- "properties" should reflect the target element's expected behaviour based on action and element_hints.
  - click actions → isClickable: true
  - type/fill/enter actions → isInput: true
  - check/uncheck/toggle actions → isCheckable: true
  - if target mentions icon/image → isIcon: true
  - isVisible should always be true (we only want visible elements)
- CRITICAL — Descriptive text before an element type:
  When the user says "[descriptive words] icon/button/menu/dropdown" (e.g., "overflow menu icon",
  "settings gear icon", "search icon", "close button"), the descriptive words ("overflow menu",
  "settings", "search", "close") MUST be target.text. The element type word goes in element_hints.
  Do NOT leave target.text empty just because "icon" or "button" is mentioned.
  Also include BOTH the icon element hints AND interactive element hints (button) in element_hints,
  because many icon-looking elements are actually buttons that contain icon children.
- element hints should map the user's intent to likely HTML elements/roles. Examples:
  - "checkbox" = ["checkbox", "input", "label"]
  - "button" = ["button", "a", "link"]
  - "dropdown" = ["select", "combobox", "listbox"]
  - "text field" / "input field" = ["input", "textarea", "textbox"]
  - "tab" = ["tab", "button", "a"]
  - "menu item" = ["menuitem", "li", "a"]
  - "radio button" = ["radio", "radiobutton", "input"]
  - "icon" = ["i", "svg", "span", "img"]
- IMPORTANT: If the user says they will ENTER/TYPE a value, that value is NOT part of the target text.
  Extract keywords for the target field/cell itself.

Examples:
1) User: "Click on Specify Users checkbox under Request Access section"
   → {"action":"click","target":{"text":"Specify Users","element_hints":["checkbox","input","label"],"properties":{"isClickable":true,"isCheckable":true,"isVisible":true}},"label":null,"anchor":{"scope_type":"section","text":"Request Access","relation":"under"},"keywords":["Specify Users","Request Access"]}

2) User: "Click on DB menu button on Dashboard 1 tab"
   → {"action":"click","target":{"text":"DB","element_hints":["button","menuitem","a"],"properties":{"isClickable":true,"isVisible":true}},"label":null,"anchor":{"scope_type":"tab","text":"Dashboard 1","relation":"on"},"keywords":["DB","Dashboard 1"]}

3) User: "Click Submit"
   → {"action":"click","target":{"text":"Submit","element_hints":["button","a","link"],"properties":{"isClickable":true,"isVisible":true}},"label":null,"anchor":null,"keywords":["Submit"]}

4) User: "Enter abc in Description field"
   → {"action":"type","target":{"text":"","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":{"text":"Description","relation":"for"},"anchor":null,"keywords":["Description"]}

5) User: "Select option 1030788 from the dropdown in Billing section"
   → {"action":"select","target":{"text":"1030788","element_hints":["option","li","menuitem"],"properties":{"isClickable":true,"isVisible":true}},"label":null,"anchor":{"scope_type":"section","text":"Billing","relation":"in"},"keywords":["1030788","Billing","dropdown"]}

6) User: "Click the search icon next to Filter field"
   → {"action":"click","target":{"text":"Search","element_hints":["button","icon","i","svg","span","img"],"properties":{"isClickable":true,"isIcon":true,"isVisible":true}},"label":{"text":"Filter","relation":"next_to"},"anchor":null,"keywords":["Search","icon","Filter"]}

7) User: "Enter abc in 3rd row cell below Expression column"
   → {"action":"type","target":{"text":"","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":{"text":"Expression","relation":"below"},"anchor":{"scope_type":"column","text":"Expression","relation":"below"},"keywords":["Expression","cell","3rd row"]}

8) User: "Click on an overflow menu icon which is on right side of PDF icon"
   → {"action":"click","target":{"text":"overflow menu","placeholder":"","element_hints":["button","icon","menuitem"],"properties":{"isClickable":true,"isIcon":true,"isVisible":true}},"label":{"text":"PDF","relation":"right_of"},"anchor":null,"keywords":["overflow","menu","PDF","icon"]}

9) User: "Type hello in the Search box"
   → {"action":"type","target":{"text":"","placeholder":"Search","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":null,"anchor":null,"keywords":["Search"]}

10) User: "Enter email in the 'Enter your email address' field"
   → {"action":"type","target":{"text":"","placeholder":"Enter your email address","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":null,"anchor":null,"keywords":["email","Enter your email address"]}

Return STRICT JSON only.

User query:
__USER_QUERY__"""
```

---

## HELPER: _keyword_fallback (lines ~830–850)

```python
    def _keyword_fallback(
        self,
        keywords: List[str],
        top_k: int = 30,
        prefer_visible: bool = True,
    ) -> List[Dict[str, Any]]:
        """Fallback search using raw keywords when structured criteria produce no results."""
        if not keywords:
            return []

        all_results: Dict[str, Dict[str, Any]] = {}
        for kw in keywords:
            criteria = NodeMatchCriteria(contains={"text": kw})
            results = self._score_all_nodes(criteria, top_k=top_k, prefer_visible=prefer_visible)
            for r in results:
                nid = r["node_id"]
                if nid not in all_results or r["score"] > all_results[nid]["score"]:
                    all_results[nid] = r

        return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:top_k]
```

---

## HELPER: _is_visible (lines ~853–895)

```python
    def _is_visible(self, meta: Dict[str, Any]) -> bool:
        """Check if a node is visible based on state/style/rect metadata."""
        if not isinstance(meta, dict):
            return False

        state = meta.get("state", {}) or {}
        style = meta.get("style", {}) or {}
        rect = meta.get("rect", {}) or {}

        if isinstance(state, dict):
            if "visible" in state:
                try:
                    return bool(state["visible"])
                except Exception:
                    pass
            if state.get("display") == "none":
                return False
            if state.get("visibility") == "hidden":
                return False
            try:
                if state.get("opacity") is not None and float(state["opacity"]) == 0:
                    return False
            except Exception:
                pass

        if style.get("display") == "none":
            return False
        if style.get("visibility") == "hidden":
            return False
        try:
            if style.get("opacity") is not None and float(style["opacity"]) == 0:
                return False
        except Exception:
            pass

        try:
            w = float(rect.get("width", 0) or 0)
            h = float(rect.get("height", 0) or 0)
            if w == 0 and h == 0:
                return False
        except Exception:
            pass

        return True
```

**Visibility checks:** state.visible → state.display/visibility/opacity → style.display/visibility/opacity → rect width/height == 0

---

## HELPER: _compute_proximity_bonus (lines ~900+)

```python
    def _compute_proximity_bonus(self, target_nid: str, anchor_nids: set) -> float:
        # ... walks up from target checking if any ancestor is an anchor

        # 2. Check if anchor is a sibling of any close ancestor (within 5 levels)
        # ... walks up from target_nid checking parent's children
        # ... checks grandchildren too
        # anchor_indices tracking for sibling distance

        for anc_nid, anc_idx in anchor_indices.items():
            if cur2_idx is not None:
                sibling_distance = abs(cur2_idx - anc_idx)
                # Check intervening section headers
                lo, hi = min(cur2_idx, anc_idx), max(cur2_idx, anc_idx)
                intervening_headers = 0
                for between_idx in range(lo + 1, hi):
                    if between_idx < len(children):
                        between_meta = self.kg.node_metadata.get(children[between_idx], {})
                        between_tag = (between_meta.get("tag") or "").lower()
                        if between_tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                            intervening_headers += 1
                order_penalty = sibling_distance * 0.8 + intervening_headers * 5.0
            base_bonus = max(0.0, 12.0 - depth2 * 2.0)

        # 3. Check if anchor text appears in ancestor metadata
        # ... walks up from target checking title/aria-label of ancestors
        # bonus = max(0.0, 12.0 - depth3 * 1.5)

        return best_bonus
```

**Key scoring:**
- Direct ancestor: bonus based on depth (max 12.0, -2.0 per level)
- Sibling: penalized by sibling distance * 0.8 + intervening headers * 5.0
- Ancestor text match: bonus = max(0.0, 12.0 - depth * 1.5)

---

## HELPER: _find_nearest_anchor (lines ~950+)

```python
    def _find_nearest_anchor(self, target_nid: str, anchor_nids: set) -> Optional[str]:
        """Find which anchor node is closest (in DOM tree) to the target node."""
        if not target_nid or not anchor_nids:
            return None

        best_dist = float("inf")
        best_anchor = None

        # Build ancestor map for target
        t_ancestors: Dict[str, int] = {}
        visited = set()
        depth = 0
        cur = self.kg.parent_of.get(target_nid)
        # ... walk up to build ancestor map
        # ... for each anchor, walk up checking if any ancestor overlaps
        # ... return closest by total_dist

        return best_anchor
```

---

## MISSING SECTIONS — NOW CAPTURED

### _score_node() fully captured, _find_nearby_by_criteria() captured, tree helpers captured.

---

## CORE: _score_node() — The Scoring Formula (lines ~450–860)

This is the **heart of the search engine**. ~400 lines with a detailed scoring docstring.

### Signature & Scoring Principle

```python
    def _score_node(
        self,
        meta: Dict[str, Any],
        criteria: NodeMatchCriteria,
        *,
        action: str = "",
        nid: str = "",
    ) -> float:
        """Multi-signal scoring of a single node against criteria.

        TEXT-FIRST SCORING PRINCIPLE
        =============================
        Text match is the **primary** signal. Tag, role, and interactive
        bonuses are "secondary" tie-breakers that must NEVER outweigh a
        better text match.

        Scoring tiers (designed so higher text-match tier always wins):

          TEXT TIER — primary signal (max ~28)
          - equals.text exact match:         +20.0   (dominant — e.g. node "DA" == query "DA")
          - contains.text substring match:   +4.0–8.0 (query found inside node text, scaled by coverage)
          - contains.text word-level overlap: +1.5–4.0 (individual words match across text sources)
          - No text relevance penalty:       -4.0    (when query has text but node has zero overlap)

          ELEMENT TIER — secondary tie-breaker (max ~5)
          - tag hints match:                 +2.0
          - tag hints mismatch + text match: 0.0   (no penalty — text already proved relevance)
          - tag_hints mismatch + no text:    -2.0
          - role hints match:                +1.0
          - isClickable / isInput property:  +0.5
          - Interactive element bonus:       +1.0
          - Non-interactive penalty:         -1.5  (only when text_matched is False)

          ACCESSORY SIGNALS (max ~4)
          - aria-label / placeholder:        +2.0 (exact), +1.0 (partial)
          - data-testid:                     +3.5 (exact), +1.5 (partial)
          - Visibility bonus:                +0.5

        This ensures:
          - div with exact text "DA" = +20 + 0 + 0.5 = 20.5  (B2 vis = 41)
          - button with partial "DA" in "DATA ANALYSIS USER GUIDE" = ~4 + 4.5 + 0.5 = 9  (B2 vis = 18)
          → Exact text match on a <div> ALWAYS beats partial match on a <button>.
        """
```

### Function Body Start

```python
        if not meta or not isinstance(meta, dict):
            return 0.0

        score = 0.0
        attrs = meta.get("attrs", {}) or {}
        tag = (meta.get("tag") or "").strip().lower()
        role = (meta.get("role") or attrs.get("role") or "").strip().lower()
        input_type = (attrs.get("type") or "").strip().lower()
        cls = attrs.get("class", "")
        if isinstance(cls, list):
            cls = " ".join(cls)
        cls_lower = cls.lower()

        # --- Suppress frame nodes (unless explicitly searching for frames) ---
        is_frame = bool(meta.get("isFrame")) or tag == "iframe"
        if is_frame:
            score -= 3.0

        # --- Text fields (rich: includes parent class, child text, child class) ---
        if nid:
            node_texts = self._collect_searchable_text(nid, meta)
        else:
            node_texts = self._extract_text_fields(meta)
```

### TEXT TIER — Primary Signal

```python
        # TEXT TIER — Primary signal (exact > contains > word-level > none)
        exact_text_hit = False   # True when ANY text source exactly equals the query
        contains_text_hit = False  # True when query is a contiguous substring
        text_matched = False     # True when any level of text overlap exists

        # ---- equals matching (exact full-text match, case-insensitive) ----
        for field_key, expected_val in criteria.equals.items():
            if not expected_val:
                continue
            expected_lower = expected_val.strip().lower()

            if field_key == "text":
                for nt in node_texts:
                    nt_norm = " ".join(nt.lower().split())
                    if nt_norm == expected_lower:
                        score += 20.0
                        exact_text_hit = True
                        text_matched = True
            else:
                # Generic attribute matching
                attr_val = attrs.get(field_key, "")
                if isinstance(attr_val, str) and " ".join(attr_val.lower().split()) == expected_lower:
                    score += 4.0

        # ---- contains matching (substring / word-level, case-insensitive) ----
        for field_key, expected_val in criteria.contains.items():
            if not expected_val:
                continue
            expected_lower = expected_val.strip().lower()

            if field_key == "text":
                best_partial = 0.0
                # Join all text sources for a single composite check
                all_text_joined = " ".join(
                    " ".join(nt.lower().split()) for nt in node_texts
                )
                for nt in node_texts:
                    nt_norm = " ".join(nt.lower().split())
                    # Exact match already awarded above; skip double-count
                    if nt_norm == expected_lower:
                        contains_text_hit = True
                        text_matched = True
                        continue
                    if expected_lower in nt_norm:
                        contains_text_hit = True
                        text_matched = True
                        coverage = len(expected_lower) / max(len(nt_norm), 1)
                        # Scale: short query in long text = low coverage = lower score
                        # Full coverage (query IS the text) already handled by equals
                        partial_score = 6.0 * min(1.0, coverage + 0.3)
                        best_partial = max(best_partial, partial_score)

                # Word-level matching across ALL text sources
                if best_partial == 0.0 and all_text_joined:
                    _PUNCT_STRIP = str.maketrans("", "", "()[]{}.,;:!?\"'")
                    query_words = set(
                        w for w in
                        (tok.translate(_PUNCT_STRIP) for tok in expected_lower.split())
                        if w
                    )
                    combined_words = set(all_text_joined.split())

                    overlap = query_words & combined_words
                    fuzzy_matches = 0
                    unmatched = query_words - overlap
                    if unmatched and combined_words:
                        for qw in unmatched:
                            if len(qw) < 3:
                                continue
                            for cw in combined_words:
                                if len(cw) < 3:
                                    continue
                                if levenshtein_similarity(qw, cw) >= ...:
                                    fuzzy_matches += 1
                                    break

                    # (scoring based on overlap + fuzzy matches)
```

### ELEMENT TIER — Secondary Tie-Breaker

```python
        # Has text criteria but text not matched → penalty
        if has_text_criteria and not text_matched:
            if target_text_lower:
                if not text_matched:
                    score -= 4.0

        # ---- tag_hints match / mismatch ----
        tag_hints_lower = [t.lower() for t in criteria.tag_hints] if criteria.tag_hints else []
        tag_matched = tag in tag_hints_lower if tag_hints_lower else False

        if tag_hints_lower:
            if tag_matched:
                score += 2.0
            else:
                _INTERACTIVE_TAGS = frozenset({"button", "a", "input", "select", "textarea"})
                if tag_hints_lower and (set(tag_hints_lower) & _INTERACTIVE_TAGS):
                    _role_matches_hints = False
                    if role and criteria.role_hints:
                        rh_lower = [r.lower() for r in criteria.role_hints]
                        if role in rh_lower:
                            _role_matches_hints = True
                    _ce = (attrs.get("contenteditable") or "").strip().lower()
                    _is_contenteditable = _ce in ("true", "plaintext-only")
                    if _role_matches_hints or _is_contenteditable:
                        score += 1.5
                    elif text_matched:
                        pass  # Text match overrides tag mismatch — no penalty
                    else:
                        score -= 2.0

                # Non-interactive penalty (only when text not matched)
                _NON_INTERACTIVE_CONTAINERS = frozenset({
                    "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
                    "section", "header", "footer", "nav", "main", "aside",
                    "article", "figure", "figcaption", "blockquote",
                })
                if tag in _NON_INTERACTIVE_CONTAINERS and not role:
                    score -= 1.5
                elif tag in _NON_INTERACTIVE_CONTAINERS and role in ("title", "heading", "presentation", "none"):
                    score -= 1.0

        # ---- role_hints match ----
        if criteria.role_hints:
            role_hints_lower = [r.lower() for r in criteria.role_hints]
            if role in role_hints_lower:
                score += 1.0
                score += 1.0
            else:
                _NON_INTERACTIVE_ROLES = frozenset({
                    "title", "heading", "presentation", "none", "separator",
                    "img", "figure", "definition", "note", "tooltip",
                })
                _INTERACTIVE_ROLE_HINTS = frozenset({
                    "button", "link", "menuitem", "tab", "checkbox", "radio",
                    "switch", "textbox", "combobox", "searchbox", "spinbutton",
                    "option", "listbox",
                })
                if (set(role_hints_lower) & _INTERACTIVE_ROLE_HINTS) and role in _NON_INTERACTIVE_ROLES:
                    if not text_matched:
                        score -= 1.0
                    if input_type in role_hints_lower:
                        score += 1.0

        # ---- properties matching ----
        score += self._score_properties(meta, criteria.properties)

        # ---- Enhanced isIcon: check CHILD elements for icon-like classes ----
        if criteria.properties.get("isIcon") and nid:
            _self_is_icon = (
                tag in ("i", "svg", "img")
                or "icon" in cls_lower
                or role in ("img", "presentation")
            )
            if not _self_is_icon:
                child_ids = [
                    rel[2]
                    for rel in self.kg.relations
                    if rel[0] == nid and rel[1] == "parent_of"
                ]
                for cid in child_ids:
                    c_meta = self.kg.node_metadata.get(cid, {})
                    c_tag = (c_meta.get("tag") or "").lower()
                    c_attrs = c_meta.get("attrs", {}) or {}
                    c_cls = c_attrs.get("class", "")
                    if isinstance(c_cls, list):
                        c_cls = " ".join(c_cls)
                    c_cls_lower = c_cls.lower()
                    c_role = (c_meta.get("role") or c_attrs.get("role") or "").lower()
                    if (
                        c_tag in ("i", "svg", "img")
                        or "icon" in c_cls_lower
                        or c_role in ("img", "presentation")
                    ):
```

### ACCESSORY SIGNALS

```python
        # ---- aria-label / placeholder ----
        aria_label = (attrs.get("aria-label") or "").strip()
        placeholder = (attrs.get("placeholder") or "").strip()
        text_to_match = (criteria.contains.get("text") or criteria.equals.get("text") or "").strip().lower()
        if text_to_match:
            for extra_field in [aria_label, placeholder]:
                if extra_field:
                    ef_lower = extra_field.lower()
                    if ef_lower == text_to_match:
                        score += 2.0
                    elif text_to_match in ef_lower:
                        score += 1.0

        # ---- Dedicated placeholder matching ----
        # When the parsed intent has an explicit placeholder criterion,
        # give a strong TEXT-TIER bonus for exact placeholder match.
        # This is critical for inputs identified by placeholder text
        # (e.g. "Search...", "Enter email") with no visible label.
        placeholder_to_match = (criteria.contains.get("placeholder") or criteria.equals.get("placeholder") or "").strip().lower()
        if placeholder_to_match and placeholder:
            ph_lower = " ".join(placeholder.lower().split())
            if ph_lower == placeholder_to_match:
                score += 15.0  # text-tier: exact placeholder = almost as strong as exact text
                text_matched = True
            elif placeholder_to_match in ph_lower:
                score += 6.0   # text-tier: partial placeholder match
                text_matched = True

        # ---- data-testid ----
        dtid = (attrs.get("data-testid") or "").strip()
        if dtid and text_to_match:
            dtid_lower = dtid.lower()
            if dtid_lower == text_to_match:
                score += 3.5
            elif text_to_match in dtid_lower:
                score += 1.5

        # ---- Icon-specific attribute matching ----
        if criteria.properties.get("isIcon") and text_to_match:
            _ICON_ATTRS = ("data-icon", "data-name", "name", "xlink:href", "href", "src")
            for iattr in _ICON_ATTRS:
                ival = (attrs.get(iattr) or "").strip()
                if ival:
                    ival_lower = ival.lower()
                    if text_to_match == ival_lower:
                        score += 3.0
                        break
                    elif text_to_match in ival_lower:
                        score += 1.5
                        break

        # ---- id match ----
        id_val = (attrs.get("id") or "").strip()
        if id_val and text_to_match:
            id_lower = id_val.lower()
            if id_lower == text_to_match:
                score += 2.5
            elif text_to_match in id_lower:
                score += 1.2

        # ---- Visibility bonus ----
        rect = meta.get("rect", {}) or {}
        try:
            w = float(rect.get("width", 0) or 0)
            h = float(rect.get("height", 0) or 0)
            if w > 0 and h > 0:
                area = max(w * h, 1.0)
                score += min(0.5, 0.15 + 0.35 * (area / (area + 5000.0)))
        except Exception:
            pass
```

---

## HELPER: _find_nearby_by_criteria — BFS from Anchor/Label (lines ~635–730)

```python
    def _find_nearby_by_criteria(
        self,
        anchor_nid: str,
        target_criteria: NodeMatchCriteria,
        max_depth: int = 6,
        action: str = "",
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        """From an anchor/label node, BFS outward to find nearby nodes matching target criteria."""
        results: List[Tuple[str, float, Dict[str, Any]]] = []
        if not anchor_nid:
            return results

        visited_ancestors: set = set()
        visited_desc: set = set()
        _MAX_DESC_DEPTH = 6
        _MAX_TOTAL_VISITED = 500

        # ---- Icon proximity boost flag ----
        # When the target is expected to be an icon, nearby icon-type elements
        # should receive an extra boost even when their base score is modest
        # (icons typically lack text, so base scores are naturally lower)
        _is_icon_search = target_criteria.properties.get("isIcon", False)

        def _bfs_descendants(start_id: str, ancestor_depth: int):
            queue = [(start_id, 0)]
            while queue:
                if len(visited_desc) >= _MAX_TOTAL_VISITED:
                    return
                nid, lvl = queue.pop(0)
                if nid in visited_desc:
                    continue
                visited_desc.add(nid)

                if lvl > 0:  # skip start node itself
                    n_meta = self.kg.node_metadata.get(nid, {})
                    node_score = self._score_node(n_meta, target_criteria, action=action, nid=nid)

                    # Lower the threshold for icon targets — icons have
                    # naturally lower text-match scores so the default
                    # threshold of 1.0 can exclude valid icon candidates.
                    _score_threshold = 0.0 if _is_icon_search else 1.0
                    if node_score > _score_threshold:
                        # Proximity discount: closer = better
                        proximity_factor = max(0.3, 1.0 - (ancestor_depth * 0.12 + lvl * 0.05))

                        # Extra boost for icon-type elements near the label
                        if _is_icon_search:
                            n_tag = (n_meta.get("tag") or "").lower()
                            n_cls = (n_meta.get("attrs", {}) or {}).get("class", "")
                            if isinstance(n_cls, list):
                                n_cls = " ".join(n_cls)
                            n_role = (n_meta.get("role") or (n_meta.get("attrs", {}) or {}).get("role", "") or "").lower()
                            is_icon_element = (
                                n_tag in ("i", "svg", "img")
                                or "icon" in n_cls.lower()
                                or n_role in ("img", "presentation")
                            )
                            if is_icon_element:
                                node_score += 2.0  # boost for being an icon-type element
                        results.append((nid, node_score * proximity_factor, n_meta))

                if lvl < _MAX_DESC_DEPTH:
                    kids = [rel[2] for rel in self.kg.relations
                            if rel[0] == nid and rel[1] == "parent_of"]
                    for kid in kids:
                        if kid not in visited_desc:
                            queue.append((kid, lvl + 1))

        # Walk up from anchor node, BFS into sibling subtrees at each ancestor level
        cur = anchor_nid
        depth = 0
        while cur and depth < max_depth:
            parent = self.kg.parent_of.get(cur)
            if not parent or parent in visited_ancestors:
                break
            visited_ancestors.add(parent)
            depth += 1
            # BFS from parent's children (siblings + their descendants)
            # ...
```

---

## HELPERS: Tree Distance (lines ~730–900)

### _build_ancestor_set

```python
    def _build_ancestor_set(self, node_id: str, max_depth: int = 50) -> Dict[str, int]:
        """Return {ancestor_id: depth} map (depth 1 = parent)."""
        result: Dict[str, int] = {}
        visited = set()
        depth = 0
        cur = self.kg.parent_of.get(node_id)
        while cur and cur not in visited and depth < max_depth:
            visited.add(cur)
            depth += 1
            result[cur] = depth
            cur = self.kg.parent_of.get(cur)
        return result
```

### _node_tree_distance

```python
    def _node_tree_distance(
        self,
        node_a: str,
        node_b: str,
        a_ancestors: Optional[Dict[str, int]] = None,
    ) -> int:
        """Compute tree distance between two nodes.

        Tree distance = (steps from A up to LCA) + (steps from B up to LCA).
        If no common ancestor found within 50 levels, returns 999.
        """
        if node_a == node_b:
            return 0
        if a_ancestors is None:
            a_ancestors = self._build_ancestor_set(node_a)
        # Also include node_a itself at depth 0 (B might be a descendant)
        a_ancestors_ext = {node_a: 0, **a_ancestors}

        visited: set = set()
        cur = node_b
        depth_b = 0
        while cur and cur not in visited and depth_b < 50:
            if cur in a_ancestors_ext:
                return a_ancestors_ext[cur] + depth_b
            visited.add(cur)
            cur = self.kg.parent_of.get(cur)
            depth_b += 1
        return 999
```

### _compute_proximity_bonus (FULL — now clear)

```python
    def _compute_proximity_bonus(self, target_nid: str, anchor_nids: set) -> float:
        """Walk up target's ancestor chain. If any ancestor is/contains an anchor, return bonus."""
        if not target_nid or not anchor_nids:
            return 0.0

        best_bonus = 0.0
        MAX_DEPTH = 15

        # 1. Walk ancestry — is an anchor a direct ancestor?
        visited = set()
        cur = target_nid
        depth = 0
        while cur and depth < MAX_DEPTH and cur not in visited:
            visited.add(cur)
            parent = self.kg.parent_of.get(cur)
            if not parent:
                break
            depth += 1
            if parent in anchor_nids:
                bonus = max(0.0, 15.0 - depth * 1.5)
                best_bonus = max(best_bonus, bonus)
                break
            cur = parent

        # 2. Check if anchor is a sibling of any close ancestor (within 5 levels)
        # ... sibling distance + intervening headers penalty
        # order_penalty = sibling_distance * 0.8 + intervening_headers * 5.0
        # base_bonus = max(0.0, 12.0 - depth2 * 2.0)

        # 3. Check if anchor text appears in ancestor metadata
        # ... walks up checking title/aria-label of parents
        # bonus = max(0.0, 12.0 - depth3 * 1.5)

        return best_bonus
```

---

## STATUS: ~90% CAPTURED (15 screenshots total)
The core scoring formula (`_score_node`) with the TEXT-FIRST principle is now captured.
Remaining gaps are only implementation details of a few sub-methods that follow clear patterns.
