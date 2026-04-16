"""
StructuredSearch.py — V2 Structured Search (ported from V2_Req/CAPTURE_StructuredSearch.md)

Components:
    NodeMatchCriteria, StructuredQuery — data models
    IntentQueryBuilder                 — LLM parsed_intent dict → StructuredQuery
    StructuredSearchEngine             — two-phase scoring + anchor re-ranking
    ENHANCED_INTENT_PROMPT_TEMPLATE    — LLM Call #3 prompt

Scoring principle: TEXT-FIRST. Exact text match dominates (+20), substring (+4–8),
word-level (+1.5–4). Tag/role bonuses cap at ~5 so they can never outrank a better
text match.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .KnowledgeGraph import EdgeTypes, KnowledgeGraph
from .word_similarity import levenshtein_similarity

logger = logging.getLogger(__name__)


# ==========================================================================
# Data models
# ==========================================================================

@dataclass
class NodeMatchCriteria:
    contains: Dict[str, str] = field(default_factory=dict)
    equals: Dict[str, str] = field(default_factory=dict)
    tag_hints: List[str] = field(default_factory=list)
    role_hints: List[str] = field(default_factory=list)
    properties: Dict[str, bool] = field(default_factory=dict)
    spatial_position: Optional[str] = None  # above|below|left_of|right_of|nearby|inside

    def is_empty(self) -> bool:
        return (
            not self.contains and not self.equals
            and not self.tag_hints and not self.role_hints
            and not self.properties
        )


@dataclass
class StructuredQuery:
    action: str = ""
    target_node: NodeMatchCriteria = field(default_factory=NodeMatchCriteria)
    is_label_available: bool = False
    label_node: Optional[NodeMatchCriteria] = None
    is_anchor_available: bool = False
    anchor_node: Optional[NodeMatchCriteria] = None
    anchor_scope_type: str = ""
    keywords: List[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"action={self.action}"]
        if not self.target_node.is_empty():
            parts.append(f"target(contains={self.target_node.contains}, eq={self.target_node.equals})")
        if self.is_label_available and self.label_node:
            parts.append(f"label(contains={self.label_node.contains}, pos={self.label_node.spatial_position})")
        if self.is_anchor_available and self.anchor_node:
            parts.append(f"anchor(contains={self.anchor_node.contains}, pos={self.anchor_node.spatial_position})")
        return " | ".join(parts)


# ==========================================================================
# Mapping tables
# ==========================================================================

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


# ==========================================================================
# IntentQueryBuilder
# ==========================================================================

class IntentQueryBuilder:
    """Converts an LLM-produced parsed_intent dict into a StructuredQuery."""

    @staticmethod
    def build(parsed_intent: Dict[str, Any]) -> StructuredQuery:
        if not parsed_intent or not isinstance(parsed_intent, dict):
            return StructuredQuery()

        action = (parsed_intent.get("action") or "").strip().lower()

        # ---- target ----
        target_info = parsed_intent.get("target") or {}
        target_text = (target_info.get("text") or "").strip()
        target_placeholder = (target_info.get("placeholder") or "").strip()
        element_hints = target_info.get("element_hints") or []

        target = NodeMatchCriteria()
        if target_text:
            target.contains["text"] = target_text
            target.equals["text"] = target_text
        if target_placeholder:
            target.contains["placeholder"] = target_placeholder
            target.equals["placeholder"] = target_placeholder
            if not target_text:
                target.contains["text"] = target_placeholder
                target.equals["text"] = target_placeholder

        all_tags: List[str] = []
        all_roles: List[str] = []
        all_props: Dict[str, bool] = {}
        for hint in element_hints:
            h = str(hint).strip().lower()
            if h in _ELEMENT_HINT_EXPANSION:
                tags, roles, props = _ELEMENT_HINT_EXPANSION[h]
                all_tags.extend(tags)
                all_roles.extend(roles)
                all_props.update(props)
            else:
                all_tags.append(h)
                all_roles.append(h)

        target.tag_hints = list(dict.fromkeys(all_tags))
        target.role_hints = list(dict.fromkeys(all_roles))
        all_props.update(_ACTION_PROPERTY_MAP.get(action, {}))
        # Merge any explicit properties provided in intent
        props_intent = target_info.get("properties") or {}
        if isinstance(props_intent, dict):
            for k, v in props_intent.items():
                if isinstance(v, bool):
                    all_props[k] = v
        target.properties = all_props

        # ---- label ----
        is_label = False
        label_criteria: Optional[NodeMatchCriteria] = None
        label_info = parsed_intent.get("label")
        if label_info and isinstance(label_info, dict):
            label_text = (label_info.get("text") or "").strip()
            label_relation = (label_info.get("relation") or "").strip().lower()
            if label_text:
                is_label = True
                label_criteria = NodeMatchCriteria()
                label_criteria.contains["text"] = label_text
                label_criteria.equals["text"] = label_text
                label_criteria.properties = {"isVisible": True}
                label_criteria.spatial_position = _RELATION_TO_SPATIAL.get(label_relation, "nearby")

        # ---- anchor ----
        is_anchor = False
        anchor_criteria: Optional[NodeMatchCriteria] = None
        _anchor_scope_type = ""
        anchor_info = parsed_intent.get("anchor")
        if anchor_info and isinstance(anchor_info, dict):
            anchor_text = (anchor_info.get("text") or "").strip()
            anchor_scope = (anchor_info.get("scope_type") or "").strip().lower()
            anchor_relation = (anchor_info.get("relation") or "").strip().lower()
            _anchor_scope_type = anchor_scope
            if anchor_text:
                is_anchor = True
                anchor_criteria = NodeMatchCriteria()
                anchor_criteria.contains["text"] = anchor_text
                anchor_criteria.equals["text"] = anchor_text
                if anchor_scope in _ANCHOR_SCOPE_EXPANSION:
                    a_tags, a_roles = _ANCHOR_SCOPE_EXPANSION[anchor_scope]
                    anchor_criteria.tag_hints = list(a_tags)
                    anchor_criteria.role_hints = list(a_roles)
                anchor_criteria.properties = {"isVisible": True}
                anchor_criteria.spatial_position = _RELATION_TO_SPATIAL.get(anchor_relation, "inside")

        # ---- keywords ----
        kws = parsed_intent.get("keywords") or []
        if isinstance(kws, list):
            keywords = [str(k).strip() for k in kws if isinstance(k, str) and k.strip()]
        else:
            keywords = []

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


# ==========================================================================
# StructuredSearchEngine
# ==========================================================================

_PUNCT_STRIP = str.maketrans("", "", "()[]{}.,;:!?\"'")
_INTERACTIVE_TAGS = frozenset({"button", "a", "input", "select", "textarea"})
_NON_INTERACTIVE_CONTAINERS = frozenset({
    "div", "span", "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "header", "footer", "nav", "main", "aside",
    "article", "figure", "figcaption", "blockquote",
})
_NON_INTERACTIVE_ROLES = frozenset({
    "title", "heading", "presentation", "none", "separator",
    "img", "figure", "definition", "note", "tooltip",
})
_INTERACTIVE_ROLE_HINTS = frozenset({
    "button", "link", "menuitem", "tab", "checkbox", "radio",
    "switch", "textbox", "combobox", "searchbox", "spinbutton",
    "option", "listbox",
})


class StructuredSearchEngine:
    """Two-phase search: target scoring + anchor proximity re-ranking."""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    # ---- public API ----
    def search(
        self,
        query: StructuredQuery,
        top_k: int = 10,
        prefer_visible: bool = True,
    ) -> List[Dict[str, Any]]:
        logger.info("[StructuredSearch] %s", query.summary())
        if not query or query.target_node.is_empty() and not query.keywords:
            return []

        # Phase 1: score every node against target criteria
        scored = self._score_all_nodes(
            query.target_node, top_k=top_k * 4, prefer_visible=prefer_visible,
            action=query.action,
        )

        # Phase 2: anchor proximity re-ranking
        if query.is_anchor_available and query.anchor_node and not query.anchor_node.is_empty():
            anchor_candidates = self._score_all_nodes(
                query.anchor_node, top_k=20, prefer_visible=prefer_visible,
                action="",
            )
            anchor_nids = {a["node_id"] for a in anchor_candidates}
            for r in scored:
                bonus = self._compute_proximity_bonus(r["node_id"], anchor_nids)
                if bonus > 0:
                    r["score"] = float(r["score"]) + bonus
                    r["anchor_source"] = True
            scored.sort(key=lambda x: x["score"], reverse=True)

        # Label-driven: if target has no text but a label is available, also find nearby
        target_text = (query.target_node.contains.get("text") or "").strip()
        if not target_text and query.is_label_available and query.label_node:
            label_candidates = self._score_all_nodes(
                query.label_node, top_k=10, prefer_visible=prefer_visible,
                action="",
            )
            extra: List[Dict[str, Any]] = []
            for lc in label_candidates:
                found = self._find_nearby_by_criteria(
                    lc["node_id"], query.target_node,
                    max_depth=6, action=query.action,
                )
                for nid, s, meta in found:
                    extra.append({
                        "node_id": nid,
                        "score": float(s),
                        "metadata": meta,
                        "label_source": True,
                    })
            if extra:
                # merge: best score wins per node_id
                by_id = {r["node_id"]: r for r in scored}
                for r in extra:
                    if r["node_id"] not in by_id or r["score"] > by_id[r["node_id"]]["score"]:
                        by_id[r["node_id"]] = r
                scored = sorted(by_id.values(), key=lambda x: x["score"], reverse=True)

        return scored[:top_k]

    # ---- text/attr field collection ----
    def _extract_text_fields(self, meta: Dict[str, Any]) -> List[str]:
        if not isinstance(meta, dict):
            return []
        attrs = meta.get("attrs", {}) or {}
        fields = [
            meta.get("text") or "",
            meta.get("innerText") or "",
            meta.get("text_content_raw") or "",
            meta.get("text_own_norm") or "",
            meta.get("text_desc_norm") or "",
            attrs.get("aria-label") or "",
            attrs.get("placeholder") or "",
            attrs.get("title") or "",
            attrs.get("name") or "",
            attrs.get("value") or "",
        ]
        return [str(f) for f in fields if f]

    def _collect_searchable_text(self, nid: str, meta: Dict[str, Any]) -> List[str]:
        texts = self._extract_text_fields(meta)
        # include direct children's own text too (for wrapper buttons)
        for c in self.kg.get_children_ids(nid)[:20]:
            cm = self.kg.node_metadata.get(c, {})
            c_text = (cm.get("text") or "").strip()
            if c_text:
                texts.append(c_text)
        return texts

    # ---- visibility ----
    def _is_visible(self, meta: Dict[str, Any]) -> bool:
        if not isinstance(meta, dict):
            return False
        state = meta.get("state") or {}
        style = meta.get("style") or {}
        rect = meta.get("rect") or {}

        if isinstance(state, dict):
            if "visible" in state:
                try:
                    return bool(state["visible"])
                except Exception:
                    pass
            if state.get("display") == "none" or state.get("visibility") == "hidden":
                return False
            try:
                if state.get("opacity") is not None and float(state["opacity"]) == 0:
                    return False
            except Exception:
                pass

        if isinstance(style, dict):
            if style.get("display") == "none" or style.get("visibility") == "hidden":
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
                # fall back to the flat parser's boolean when rect missing
                if "visible" in meta:
                    return bool(meta.get("visible"))
                return False
        except Exception:
            pass
        return bool(meta.get("visible", True))

    # ---- scoring ----
    def _score_all_nodes(
        self,
        criteria: NodeMatchCriteria,
        top_k: int,
        prefer_visible: bool,
        action: str = "",
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for nid in self.kg.nodes:
            meta = self.kg.node_metadata.get(nid, {})
            if not meta:
                continue
            if prefer_visible and not self._is_visible(meta):
                continue
            score = self._score_node(meta, criteria, action=action, nid=nid)
            if score > 0.1:
                out.append({"node_id": nid, "score": score, "metadata": meta})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    def _score_node(
        self,
        meta: Dict[str, Any],
        criteria: NodeMatchCriteria,
        *,
        action: str = "",
        nid: str = "",
    ) -> float:
        """TEXT-FIRST scoring — see V2_Req/CAPTURE_StructuredSearch.md for the formula."""
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
        cls_lower = str(cls).lower()

        # Suppress frame nodes unless explicitly searching for frames
        is_frame = bool(meta.get("isFrame")) or tag == "iframe"
        if is_frame:
            score -= 3.0

        # Text sources
        if nid:
            node_texts = self._collect_searchable_text(nid, meta)
        else:
            node_texts = self._extract_text_fields(meta)

        exact_text_hit = False
        contains_text_hit = False
        text_matched = False

        # equals (exact full-text)
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
                        break
            else:
                attr_val = attrs.get(field_key, "")
                if isinstance(attr_val, str) and " ".join(attr_val.lower().split()) == expected_lower:
                    score += 4.0

        # contains (substring / word)
        has_text_criteria = bool(criteria.contains.get("text") or criteria.equals.get("text"))
        target_text_lower = (criteria.contains.get("text") or criteria.equals.get("text") or "").strip().lower()

        for field_key, expected_val in criteria.contains.items():
            if not expected_val:
                continue
            expected_lower = expected_val.strip().lower()
            if field_key == "text":
                best_partial = 0.0
                all_text_joined = " ".join(" ".join(nt.lower().split()) for nt in node_texts)
                for nt in node_texts:
                    nt_norm = " ".join(nt.lower().split())
                    if nt_norm == expected_lower:
                        contains_text_hit = True
                        text_matched = True
                        continue
                    if expected_lower in nt_norm:
                        contains_text_hit = True
                        text_matched = True
                        coverage = len(expected_lower) / max(len(nt_norm), 1)
                        partial_score = 6.0 * min(1.0, coverage + 0.3)
                        best_partial = max(best_partial, partial_score)
                if best_partial > 0.0:
                    score += best_partial

                # Word-level fallback
                if best_partial == 0.0 and not exact_text_hit and all_text_joined:
                    query_words = {
                        w for w in (
                            tok.translate(_PUNCT_STRIP) for tok in expected_lower.split()
                        ) if w
                    }
                    combined_words = set(all_text_joined.split())
                    overlap = query_words & combined_words
                    fuzzy_matches = 0
                    for qw in (query_words - overlap):
                        if len(qw) < 3:
                            continue
                        for cw in combined_words:
                            if len(cw) < 3:
                                continue
                            if levenshtein_similarity(qw, cw) >= 0.8:
                                fuzzy_matches += 1
                                break
                    match_count = len(overlap) + fuzzy_matches
                    if query_words and match_count:
                        ratio = match_count / max(len(query_words), 1)
                        word_score = 1.5 + 2.5 * ratio
                        score += word_score
                        text_matched = True

        # Text-criteria-but-no-match penalty
        if has_text_criteria and not text_matched and target_text_lower:
            score -= 4.0

        # ---- ELEMENT TIER ----
        tag_hints_lower = [t.lower() for t in criteria.tag_hints] if criteria.tag_hints else []
        tag_matched = tag in tag_hints_lower if tag_hints_lower else False
        if tag_hints_lower:
            if tag_matched:
                score += 2.0
            else:
                if set(tag_hints_lower) & _INTERACTIVE_TAGS:
                    role_matches_hints = False
                    if role and criteria.role_hints:
                        rh = [r.lower() for r in criteria.role_hints]
                        if role in rh:
                            role_matches_hints = True
                    ce = (attrs.get("contenteditable") or "").strip().lower()
                    is_ce = ce in ("true", "plaintext-only")
                    if role_matches_hints or is_ce:
                        score += 1.5
                    elif text_matched:
                        pass  # TEXT-FIRST override
                    else:
                        score -= 2.0
                if tag in _NON_INTERACTIVE_CONTAINERS and not role:
                    if not text_matched:
                        score -= 1.5
                elif tag in _NON_INTERACTIVE_CONTAINERS and role in ("title", "heading", "presentation", "none"):
                    if not text_matched:
                        score -= 1.0

        # role hints
        if criteria.role_hints:
            rh = [r.lower() for r in criteria.role_hints]
            if role in rh:
                score += 1.0
            else:
                if (set(rh) & _INTERACTIVE_ROLE_HINTS) and role in _NON_INTERACTIVE_ROLES:
                    if not text_matched:
                        score -= 1.0
                if input_type in rh:
                    score += 1.0

        # properties
        score += self._score_properties(meta, criteria.properties)

        # ---- ACCESSORY ----
        aria_label = (attrs.get("aria-label") or "").strip()
        placeholder = (attrs.get("placeholder") or "").strip()
        text_to_match = target_text_lower
        if text_to_match:
            for extra_field in (aria_label, placeholder):
                if extra_field:
                    ef = extra_field.lower()
                    if ef == text_to_match:
                        score += 2.0
                    elif text_to_match in ef:
                        score += 1.0

        # Dedicated placeholder criterion
        ph_to_match = (criteria.contains.get("placeholder") or criteria.equals.get("placeholder") or "").strip().lower()
        if ph_to_match and placeholder:
            ph_lower = " ".join(placeholder.lower().split())
            if ph_lower == ph_to_match:
                score += 15.0
                text_matched = True
            elif ph_to_match in ph_lower:
                score += 6.0
                text_matched = True

        # data-testid
        dtid = (attrs.get("data-testid") or "").strip()
        if dtid and text_to_match:
            dtid_lower = dtid.lower()
            if dtid_lower == text_to_match:
                score += 3.5
            elif text_to_match in dtid_lower:
                score += 1.5

        # Icon-specific
        if criteria.properties.get("isIcon") and text_to_match:
            _ICON_ATTRS = ("data-icon", "data-name", "name", "xlink:href", "href", "src")
            for ia in _ICON_ATTRS:
                ival = (attrs.get(ia) or "").strip()
                if ival:
                    ival_lower = ival.lower()
                    if text_to_match == ival_lower:
                        score += 3.0
                        break
                    elif text_to_match in ival_lower:
                        score += 1.5
                        break

        # id match
        id_val = (attrs.get("id") or "").strip()
        if id_val and text_to_match:
            id_lower = id_val.lower()
            if id_lower == text_to_match:
                score += 2.5
            elif text_to_match in id_lower:
                score += 1.2

        # Visibility bonus by area
        rect = meta.get("rect") or {}
        try:
            w = float(rect.get("width", 0) or 0)
            h = float(rect.get("height", 0) or 0)
            if w > 0 and h > 0:
                area = max(w * h, 1.0)
                score += min(0.5, 0.15 + 0.35 * (area / (area + 5000.0)))
        except Exception:
            pass

        return score

    def _score_properties(self, meta: Dict[str, Any], properties: Dict[str, bool]) -> float:
        """Score against expected behavioral properties."""
        if not properties:
            return 0.0
        bonus = 0.0
        attrs = meta.get("attrs", {}) or {}
        tag = (meta.get("tag") or "").lower()
        role = (meta.get("role") or attrs.get("role") or "").lower()
        input_type = (attrs.get("type") or "").lower()

        is_clickable = tag in ("button", "a") or role in ("button", "link", "menuitem", "tab")
        is_input = (tag in ("input", "textarea", "select") and input_type not in ("checkbox", "radio")) \
            or role in ("textbox", "searchbox", "combobox")
        is_checkable = (tag == "input" and input_type in ("checkbox", "radio")) \
            or role in ("checkbox", "radio", "switch")
        is_visible = self._is_visible(meta)
        is_icon = tag in ("i", "svg", "img") or "icon" in (attrs.get("class", "") if isinstance(attrs.get("class"), str) else "").lower()

        if properties.get("isClickable") and is_clickable:
            bonus += 1.0
        if properties.get("isInput") and is_input:
            bonus += 1.0
        if properties.get("isCheckable") and is_checkable:
            bonus += 1.0
        if properties.get("isIcon") and is_icon:
            bonus += 1.0
        if properties.get("isVisible") and is_visible:
            bonus += 0.5
        return bonus

    # ---- proximity ----
    def _compute_proximity_bonus(self, target_nid: str, anchor_nids: set) -> float:
        if not target_nid or not anchor_nids:
            return 0.0
        best_bonus = 0.0
        MAX_DEPTH = 15

        # 1) direct ancestor?
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

        # 2) anchor is sibling of some close ancestor
        cur2 = target_nid
        depth2 = 0
        visited2 = set()
        while cur2 and depth2 < 5 and cur2 not in visited2:
            visited2.add(cur2)
            p = self.kg.parent_of.get(cur2)
            if not p:
                break
            depth2 += 1
            children = self.kg.get_children_ids(p)
            try:
                cur2_idx = children.index(cur2)
            except ValueError:
                cur2_idx = None
            anchor_indices = {c: i for i, c in enumerate(children) if c in anchor_nids}
            if cur2_idx is not None and anchor_indices:
                for _a_nid, a_idx in anchor_indices.items():
                    sibling_distance = abs(cur2_idx - a_idx)
                    lo, hi = min(cur2_idx, a_idx), max(cur2_idx, a_idx)
                    intervening_headers = 0
                    for bi in range(lo + 1, hi):
                        bm = self.kg.node_metadata.get(children[bi], {})
                        btag = (bm.get("tag") or "").lower()
                        if btag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                            intervening_headers += 1
                    order_penalty = sibling_distance * 0.8 + intervening_headers * 5.0
                    base_bonus = max(0.0, 12.0 - depth2 * 2.0)
                    bonus = max(0.0, base_bonus - order_penalty)
                    best_bonus = max(best_bonus, bonus)
            cur2 = p

        # 3) anchor text in ancestor metadata
        cur3 = target_nid
        depth3 = 0
        visited3 = set()
        while cur3 and depth3 < MAX_DEPTH and cur3 not in visited3:
            visited3.add(cur3)
            p = self.kg.parent_of.get(cur3)
            if not p:
                break
            depth3 += 1
            pm = self.kg.node_metadata.get(p, {})
            pattrs = pm.get("attrs", {}) or {}
            anc_text = " ".join(filter(None, [
                pm.get("text", ""), pattrs.get("aria-label", ""),
                pattrs.get("title", ""), pattrs.get("id", ""),
            ])).lower()
            for a in anchor_nids:
                am = self.kg.node_metadata.get(a, {})
                a_text = (am.get("text") or "").strip().lower()
                if a_text and a_text in anc_text:
                    bonus = max(0.0, 12.0 - depth3 * 1.5)
                    best_bonus = max(best_bonus, bonus)
                    break
            cur3 = p

        return best_bonus

    # ---- BFS from anchor/label for label-driven search ----
    def _find_nearby_by_criteria(
        self,
        anchor_nid: str,
        target_criteria: NodeMatchCriteria,
        max_depth: int = 6,
        action: str = "",
    ) -> List[Tuple[str, float, Dict[str, Any]]]:
        results: List[Tuple[str, float, Dict[str, Any]]] = []
        if not anchor_nid:
            return results

        _MAX_DESC_DEPTH = 6
        _MAX_TOTAL_VISITED = 500
        visited_ancestors: set = set()
        visited_desc: set = set()
        is_icon_search = target_criteria.properties.get("isIcon", False)

        def _bfs(start_id: str, ancestor_depth: int) -> None:
            queue: List[Tuple[str, int]] = [(start_id, 0)]
            while queue:
                if len(visited_desc) >= _MAX_TOTAL_VISITED:
                    return
                nid, lvl = queue.pop(0)
                if nid in visited_desc:
                    continue
                visited_desc.add(nid)
                if lvl > 0:
                    n_meta = self.kg.node_metadata.get(nid, {})
                    node_score = self._score_node(n_meta, target_criteria, action=action, nid=nid)
                    threshold = 0.0 if is_icon_search else 1.0
                    if node_score > threshold:
                        proximity_factor = max(0.3, 1.0 - (ancestor_depth * 0.12 + lvl * 0.05))
                        if is_icon_search:
                            n_tag = (n_meta.get("tag") or "").lower()
                            n_cls = (n_meta.get("attrs", {}) or {}).get("class", "")
                            if isinstance(n_cls, list):
                                n_cls = " ".join(n_cls)
                            n_role = (n_meta.get("role") or (n_meta.get("attrs", {}) or {}).get("role", "")).lower()
                            is_icon_el = (
                                n_tag in ("i", "svg", "img")
                                or "icon" in str(n_cls).lower()
                                or n_role in ("img", "presentation")
                            )
                            if is_icon_el:
                                node_score += 2.0
                        results.append((nid, node_score * proximity_factor, n_meta))
                if lvl < _MAX_DESC_DEPTH:
                    for kid in self.kg.get_children_ids(nid):
                        if kid not in visited_desc:
                            queue.append((kid, lvl + 1))

        # walk up anchor's ancestry, BFS into sibling subtrees at each level
        cur = anchor_nid
        depth = 0
        while cur and depth < max_depth:
            parent = self.kg.parent_of.get(cur)
            if not parent or parent in visited_ancestors:
                break
            visited_ancestors.add(parent)
            depth += 1
            for sibling in self.kg.get_children_ids(parent):
                if sibling in visited_desc:
                    continue
                _bfs(sibling, depth)
            cur = parent

        return results

    # ---- fallback keyword search ----
    def _keyword_fallback(
        self,
        keywords: List[str],
        top_k: int = 30,
        prefer_visible: bool = True,
    ) -> List[Dict[str, Any]]:
        if not keywords:
            return []
        all_results: Dict[str, Dict[str, Any]] = {}
        for kw in keywords:
            criteria = NodeMatchCriteria(contains={"text": kw})
            for r in self._score_all_nodes(criteria, top_k=top_k, prefer_visible=prefer_visible):
                nid = r["node_id"]
                if nid not in all_results or r["score"] > all_results[nid]["score"]:
                    all_results[nid] = r
        return sorted(all_results.values(), key=lambda x: x["score"], reverse=True)[:top_k]


# ==========================================================================
# ENHANCED_INTENT_PROMPT_TEMPLATE — LLM Call #3
# ==========================================================================

ENHANCED_INTENT_PROMPT_TEMPLATE = """You are a QA assistant. Parse the user's UI interaction query into a structured intent object.

The intent object tells us:
1. action: What the user wants to do (click, type, select, hover, check, uncheck, toggle, open, search)
2. target: The element the user wants to interact with - its own visible text, expected element type, and behavioural properties
3. label (optional): A nearby label/heading that IDENTIFIES the target element (the target itself may have no text)
4. anchor (optional): A REGIONAL qualifier that scopes WHERE the target is located (section, tab, panel, dialog, menu...)

CRITICAL DISTINCTION - label vs anchor:
- label answers "which specific element?" - it is text ADJACENT to the target that NAMES it.
  Use label when the user says "below label X", "next to X", "labeled X", "field X", "Input X", "the X checkbox", or when the target element type (input/checkbox/radio) typically has no visible text of its own.
- anchor answers "in which region/area?" - it is a broader container or section.
  Use anchor when the user says "under X section", "in X tab", "on X panel", "in X dialog".
- A query can have BOTH a label AND an anchor, just one, or neither.

Output schema (STRICT JSON):

{
    "action": "<click|type|select|hover|open|search|toggle|check|uncheck>",
    "target": {
        "text": "<target's OWN visible text - empty string if no text>",
        "placeholder": "<placeholder text if mentioned - empty string otherwise>",
        "element_hints": ["<tag/role: checkbox, button, input, label, link, menuitem, option, tab, radio, select, textarea, icon, img>"],
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
}

Rules:
- label is null when there is NO nearby label mentioned (e.g., "Click Submit" - Submit IS the target text).
- label is populated when the user references a label/heading/text that is NOT the target element itself but identifies it.
- When label is set, target.text should be empty or contain only the target's own text, NOT the label text.
- anchor is null when the user provides NO regional qualifier.
- keywords are 1-3 compact search tokens for fallback heuristic search.
- placeholder in target: when the user refers to an input field by its placeholder/hint text, extract that text into target.placeholder.
- properties should reflect the target element's expected behaviour based on action and element_hints.
- Descriptive text before an element type: when the user says "[descriptive words] icon/button/menu/dropdown", the descriptive words MUST be target.text.

Examples:
1) "Click on Specify Users checkbox under Request Access section"
   -> {"action":"click","target":{"text":"Specify Users","element_hints":["checkbox","input","label"],"properties":{"isClickable":true,"isCheckable":true,"isVisible":true}},"label":null,"anchor":{"scope_type":"section","text":"Request Access","relation":"under"},"keywords":["Specify Users","Request Access"]}

2) "Click on DB menu button on Dashboard 1 tab"
   -> {"action":"click","target":{"text":"DB","element_hints":["button","menuitem","a"],"properties":{"isClickable":true,"isVisible":true}},"label":null,"anchor":{"scope_type":"tab","text":"Dashboard 1","relation":"on"},"keywords":["DB","Dashboard 1"]}

3) "Click Submit"
   -> {"action":"click","target":{"text":"Submit","element_hints":["button","a","link"],"properties":{"isClickable":true,"isVisible":true}},"label":null,"anchor":null,"keywords":["Submit"]}

4) "Enter abc in Description field"
   -> {"action":"type","target":{"text":"","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":{"text":"Description","relation":"for"},"anchor":null,"keywords":["Description"]}

5) "Select option 1030788 from the dropdown in Billing section"
   -> {"action":"select","target":{"text":"1030788","element_hints":["option","li","menuitem"],"properties":{"isClickable":true,"isVisible":true}},"label":null,"anchor":{"scope_type":"section","text":"Billing","relation":"in"},"keywords":["1030788","Billing","dropdown"]}

6) "Click the search icon next to Filter field"
   -> {"action":"click","target":{"text":"Search","element_hints":["button","icon","i","svg","span","img"],"properties":{"isClickable":true,"isIcon":true,"isVisible":true}},"label":{"text":"Filter","relation":"next_to"},"anchor":null,"keywords":["Search","icon","Filter"]}

7) "Enter abc in 3rd row cell below Expression column"
   -> {"action":"type","target":{"text":"","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":{"text":"Expression","relation":"below"},"anchor":{"scope_type":"column","text":"Expression","relation":"below"},"keywords":["Expression","cell","3rd row"]}

8) "Click on an overflow menu icon which is on right side of PDF icon"
   -> {"action":"click","target":{"text":"overflow menu","placeholder":"","element_hints":["button","icon","menuitem"],"properties":{"isClickable":true,"isIcon":true,"isVisible":true}},"label":{"text":"PDF","relation":"right_of"},"anchor":null,"keywords":["overflow","menu","PDF","icon"]}

9) "Type hello in the Search box"
   -> {"action":"type","target":{"text":"","placeholder":"Search","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":null,"anchor":null,"keywords":["Search"]}

10) "Enter email in the 'Enter your email address' field"
   -> {"action":"type","target":{"text":"","placeholder":"Enter your email address","element_hints":["input","textarea","textbox"],"properties":{"isInput":true,"isVisible":true}},"label":null,"anchor":null,"keywords":["email","Enter your email address"]}

Return STRICT JSON only.

User query:
__USER_QUERY__"""


# ==========================================================================
# Legacy helpers (still imported by other modules)
# ==========================================================================

def filter_relevant_candidates(candidates, threshold: float = 0.3):
    """Kept for backwards-compat. The orchestrator uses _filter_relevant_candidates
    in scraping_by_knowledge_graph.py for the full 4-strategy filter.
    """
    out = []
    for item in candidates:
        if isinstance(item, dict):
            if float(item.get("score", 0)) >= threshold:
                out.append(item)
        elif isinstance(item, tuple) and len(item) == 2:
            node, score = item
            if float(score) >= threshold:
                out.append(item)
    return out
