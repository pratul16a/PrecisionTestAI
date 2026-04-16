"""
GraphTraversal.py — V2 Context Builder (ported from V2_Req/CAPTURE_KnowledgeGraph.md)

For a set of target nodes, produces the rich prompt context consumed by LLM Call #4.
Returns a list of subtree dicts (one per target) with:
  target_node_id, target_summary, ancestors, siblings, descendants,
  label_resolution, anchor_resolution, locator_suggestions, scoping_container.

The shape matches what _trim_prompt_context_to_token_limit() and
_has_pollution_in_context() expect in scraping_by_knowledge_graph.py.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .KnowledgeGraph import EdgeTypes, KnowledgeGraph

logger = logging.getLogger(__name__)


_SCOPING_ROLES = frozenset({
    "dialog", "alertdialog",
    "tabpanel",
    "menu", "menubar",
    "navigation",
    "region",
    "form",
    "grid", "treegrid",
    "toolbar",
})

_SCOPING_TAGS = frozenset({
    "dialog", "section", "nav", "form", "table", "main", "aside",
})


class GraphTraversal:
    """Builds subtree prompt context for LLM Call #4."""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    # ---- main entry ----
    def build_subtree_context_locatable_v2(
        self,
        target_ids: List[str],
        parsed_intent: Optional[Dict[str, Any]] = None,
        max_ancestors: int = 6,
        max_siblings: int = 8,
        max_descendants: int = 30,
    ) -> List[Dict[str, Any]]:
        """Return a list of subtree context dicts, one per target."""
        out: List[Dict[str, Any]] = []
        for tid in target_ids:
            meta = self.kg.node_metadata.get(tid)
            if not meta:
                continue
            already_seen: set = {tid}
            subtree = self._build_subtree(
                tid, meta, parsed_intent, already_seen,
                max_ancestors=max_ancestors,
                max_siblings=max_siblings,
                max_descendants=max_descendants,
            )
            out.append(subtree)
        return out

    # ---- per-target subtree ----
    def _build_subtree(
        self,
        target_id: str,
        target_meta: Dict[str, Any],
        parsed_intent: Optional[Dict[str, Any]],
        already_seen: set,
        *,
        max_ancestors: int,
        max_siblings: int,
        max_descendants: int,
    ) -> Dict[str, Any]:
        t_stability = self.kg._compute_stability_info(target_meta)
        target_summary = self._slim_meta(target_meta)
        target_summary["has_style_script_pollution"] = bool(target_meta.get("has_style_script_pollution"))

        # Ancestor chain
        ancestors: List[Dict[str, Any]] = []
        cur = self.kg.parent_of.get(target_id)
        while cur and len(ancestors) < max_ancestors:
            a_meta = self.kg.node_metadata.get(cur, {})
            a_stab = self.kg._compute_stability_info(a_meta)
            ancestors.append({
                "node_id": cur,
                "metadata": self._slim_meta(a_meta),
                "stability": a_stab,
                "is_scoping": self._is_scoping_container(a_meta),
            })
            already_seen.add(cur)
            cur = self.kg.parent_of.get(cur)

        # Siblings (direct siblings of target)
        siblings: List[Dict[str, Any]] = []
        p = self.kg.parent_of.get(target_id)
        if p:
            sib_ids = [c for c in self.kg.get_children_ids(p) if c != target_id]
            for sid in sib_ids[:max_siblings]:
                s_meta = self.kg.node_metadata.get(sid, {})
                s_stab = self.kg._compute_stability_info(s_meta)
                siblings.append({
                    "node_id": sid,
                    "metadata": self._slim_meta(s_meta),
                    "stability": s_stab,
                    "spatial_relation": self.spatial_relation(target_meta, s_meta),
                    "tree_relation": self._compute_tree_relation(target_id, sid),
                })
                already_seen.add(sid)

        # Descendants (BFS, limited)
        descendants: List[Dict[str, Any]] = []
        queue = list(self.kg.get_children_ids(target_id))
        visited: set = set()
        while queue and len(descendants) < max_descendants:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            dmeta = self.kg.node_metadata.get(nid, {})
            d_stab = self.kg._compute_stability_info(dmeta)
            descendants.append({
                "node_id": nid,
                "metadata": self._slim_meta(dmeta),
                "stability": d_stab,
            })
            for c in self.kg.get_children_ids(nid):
                if c not in visited:
                    queue.append(c)
            already_seen.add(nid)

        # Label & anchor resolution (semantic edges first, text fallback)
        label_resolution = self._resolve_label_nodes(target_id, parsed_intent, already_seen)
        anchor_resolution = self._resolve_anchor_nodes(target_id, parsed_intent, already_seen)

        # Scoping container
        scoping = self._find_scoping_container(target_id)

        # Locator suggestions
        locator_suggestions = self._compute_locator_suggestions(target_meta, t_stability)

        subtree: Dict[str, Any] = {
            "target_node_id": target_id,
            "target_summary": target_summary,
            "target_stability": t_stability,
            "locator_suggestions": locator_suggestions,
            "ancestors": ancestors,
            "siblings": siblings,
            "descendants": descendants,
            "label_resolution": label_resolution,
            "anchor_resolution": anchor_resolution,
            "scoping_container": scoping,
            "frame_url": target_meta.get("frame_url", ""),
            "frame_name": target_meta.get("frame_name", ""),
            "node_chain": [{"node_id": target_id, "metadata": target_summary}],
        }
        return subtree

    # ---- slim metadata for LLM context ----
    def _slim_meta(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(meta, dict):
            return {}
        out: Dict[str, Any] = {}

        def _truncate(s: str, n: int = 100) -> str:
            return s[:n] if len(s) > n else s

        out["tag"] = meta.get("tag", "")

        if "text_is_own" in meta:
            out["text_is_own"] = bool(meta.get("text_is_own"))

        ton = meta.get("text_own_norm")
        if isinstance(ton, str) and ton:
            out["text_own_norm"] = _truncate(ton, 160)

        tcr = meta.get("text_content_raw")
        if isinstance(tcr, str) and tcr:
            out["text_content_raw"] = tcr[:240]

        for k in ("text_nodes_total", "text_nodes_non_ws", "text_nodes_first_ws_only"):
            if k in meta:
                out[k] = meta.get(k)

        if meta.get("has_style_script_pollution"):
            out["has_style_script_pollution"] = True

        frame_url = meta.get("frameUrl") or meta.get("frame_url")
        if frame_url:
            out["frameUrl"] = frame_url

        text = str(meta.get("text", "") or "")
        inner = str(meta.get("innerText", "") or "")
        if text:
            out["text"] = _truncate(text)
        if inner and inner != text:
            out["innerText"] = _truncate(inner)

        role = meta.get("role") or (meta.get("attrs", {}) or {}).get("role")
        if role:
            out["role"] = role

        attrs = meta.get("attrs", {}) or {}
        try:
            src = attrs.get("src")
            if isinstance(src, str):
                s = src.strip().lower()
                if s.startswith("data:"):
                    attrs = dict(attrs)
                    attrs.pop("src", None)
        except Exception:
            attrs = dict(attrs)
            attrs.pop("src", None)
        out["attrs"] = attrs

        for key in ("style", "visible", "state", "isShadow"):
            if key in meta:
                out[key] = meta.get(key)
        if "FormAttrs" in meta:
            fa = meta.get("FormAttrs")
            try:
                if isinstance(fa, dict) and isinstance(fa.get("src"), str):
                    if fa.get("src", "").strip().lower().startswith("data:"):
                        fa = dict(fa)
                        fa.pop("src", None)
            except Exception:
                pass
            out["FormAttrs"] = fa

        return out

    # ---- tree helpers ----
    def _ancestor_depth_map(self, node_id: str) -> Dict[str, int]:
        depth_map: Dict[str, int] = {}
        depth = 0
        cur = self.kg.parent_of.get(node_id)
        visited: set = set()
        while cur and cur not in visited and depth < 50:
            visited.add(cur)
            depth += 1
            depth_map[cur] = depth
            cur = self.kg.parent_of.get(cur)
        return depth_map

    def _compute_tree_relation(self, a: str, b: str) -> str:
        if a == b:
            return "self"
        if self.kg.parent_of.get(b) == a:
            return "parent"
        if self.kg.parent_of.get(a) == b:
            return "child"
        pa = self.kg.parent_of.get(a)
        pb = self.kg.parent_of.get(b)
        if pa and pa == pb:
            return "sibling"
        # ancestor/descendant check
        cur = self.kg.parent_of.get(b)
        depth = 0
        while cur and depth < 25:
            if cur == a:
                return "ancestor"
            cur = self.kg.parent_of.get(cur)
            depth += 1
        cur = self.kg.parent_of.get(a)
        depth = 0
        while cur and depth < 25:
            if cur == b:
                return "descendant"
            cur = self.kg.parent_of.get(cur)
            depth += 1
        return "cousin"

    def spatial_relation(self, a_meta: Dict[str, Any], b_meta: Dict[str, Any]) -> str:
        ra = a_meta.get("rect") or {}
        rb = b_meta.get("rect") or {}
        try:
            ax = float(ra.get("x", 0)); ay = float(ra.get("y", 0))
            aw = float(ra.get("width", 0)); ah = float(ra.get("height", 0))
            bx = float(rb.get("x", 0)); by = float(rb.get("y", 0))
            bw = float(rb.get("width", 0)); bh = float(rb.get("height", 0))
        except Exception:
            return "unknown"

        if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
            return "unknown"

        a_cx, a_cy = ax + aw / 2, ay + ah / 2
        b_cx, b_cy = bx + bw / 2, by + bh / 2
        dx, dy = b_cx - a_cx, b_cy - a_cy

        # treat as overlapping when both rects overlap
        overlap_x = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        overlap_y = max(0, min(ay + ah, by + bh) - max(ay, by))
        if overlap_x > 0 and overlap_y > 0:
            return "overlapping"

        if abs(dy) >= abs(dx):
            return "below" if dy > 0 else "above"
        return "right_of" if dx > 0 else "left_of"

    # ---- anchor/label resolution ----
    def _resolve_anchor_nodes(
        self,
        target_id: str,
        parsed_intent: Optional[Dict[str, Any]],
        already_seen: set,
    ) -> List[Dict[str, Any]]:
        if not parsed_intent:
            return []
        anchor = parsed_intent.get("anchor") or {}
        anchor_text = (anchor.get("text") or "").strip()
        if not anchor_text:
            return []

        anchor_lower = anchor_text.lower()
        target_meta = self.kg.node_metadata.get(target_id, {})
        t_ancestors = self._ancestor_depth_map(target_id)

        candidates: List[Tuple[int, str, Dict[str, Any]]] = []

        # Strategy 1: container whose label/text matches anchor
        for edge_type, container_id in self.kg._node_containers.get(target_id, []):
            c_meta = self.kg.node_metadata.get(container_id, {})
            c_attrs = c_meta.get("attrs", {}) or {}
            c_text_fields = [
                (c_meta.get("text") or "").strip(),
                (c_attrs.get("aria-label") or "").strip(),
                (c_attrs.get("title") or "").strip(),
                (c_attrs.get("id") or "").strip(),
            ]
            for ct in c_text_fields:
                if ct and anchor_lower in ct.lower():
                    candidates.append((0, container_id, c_meta))
                    break

        # Strategy 2: text search
        _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "label", "legend",
                         "span", "p", "strong", "b", "em"}
        for nid, meta in self.kg.node_metadata.items():
            if nid == target_id or nid in already_seen:
                continue
            if any(c[1] == nid for c in candidates):
                continue
            text = (meta.get("text") or "").strip()
            own_norm = (meta.get("text_own_norm") or "").strip()
            attrs = meta.get("attrs", {}) or {}
            aria = (attrs.get("aria-label") or "").strip()

            matched = False
            for cand_text in (text, own_norm, aria):
                if cand_text and anchor_lower in cand_text.lower():
                    tag = (meta.get("tag") or "").lower()
                    if tag in _HEADING_TAGS or len(cand_text) < 120:
                        matched = True
                    break
            if not matched:
                continue

            dist = 999
            cur = nid
            depth = 0
            while cur and depth < 256:
                if cur in t_ancestors:
                    dist = t_ancestors[cur] + depth
                    break
                cur = self.kg.parent_of.get(cur)
                depth += 1
            candidates.append((dist, nid, meta))

        if not candidates:
            return []
        candidates.sort(key=lambda x: x[0])
        results: List[Dict[str, Any]] = []
        for dist, anc_id, anc_meta in candidates[:2]:
            stab = self.kg._compute_stability_info(anc_meta)
            entry = {
                "node_id": anc_id,
                "metadata": self._slim_meta(anc_meta),
                "stability": stab,
                "spatial_relation": self.spatial_relation(target_meta, anc_meta),
                "tree_relation": self._compute_tree_relation(target_id, anc_id),
                "usable_as_anchor": True,
                "anchor_match": True,
            }
            if stab.get("has_stable_attrs") or stab.get("has_text"):
                entry["locator_suggestions"] = self._compute_locator_suggestions(anc_meta, stab)
            results.append(entry)
            already_seen.add(anc_id)
        return results

    def _resolve_label_nodes(
        self,
        target_id: str,
        parsed_intent: Optional[Dict[str, Any]],
        already_seen: set,
    ) -> List[Dict[str, Any]]:
        if not parsed_intent:
            return []
        label_info = parsed_intent.get("label") or {}
        label_text = (label_info.get("text") or "").strip()
        if not label_text:
            return []

        label_lower = label_text.lower()
        target_meta = self.kg.node_metadata.get(target_id, {})
        t_ancestors = self._ancestor_depth_map(target_id)

        candidates: List[Tuple[int, str, Dict[str, Any]]] = []

        # Strategy 1: direct label_for edge
        label_from_edge = self.kg._find_label_for(target_id)
        if label_from_edge and label_from_edge not in already_seen:
            lm = self.kg.node_metadata.get(label_from_edge, {})
            lt = (lm.get("text") or lm.get("text_own_norm") or "").strip()
            if lt and label_lower in lt.lower():
                candidates.append((0, label_from_edge, lm))

        input_from_edge = self.kg._find_labeled_input(target_id)
        if input_from_edge and input_from_edge not in already_seen:
            im = self.kg.node_metadata.get(input_from_edge, {})
            candidates.append((0, input_from_edge, im))

        # Strategy 2: text search
        _LABEL_TAGS = {"label", "legend", "span", "p", "strong", "b", "em",
                       "h1", "h2", "h3", "h4", "h5", "h6"}
        for nid, meta in self.kg.node_metadata.items():
            if nid == target_id or nid in already_seen:
                continue
            if any(c[1] == nid for c in candidates):
                continue
            text = (meta.get("text") or "").strip()
            own_norm = (meta.get("text_own_norm") or "").strip()
            attrs = meta.get("attrs", {}) or {}
            aria = (attrs.get("aria-label") or "").strip()

            matched = False
            for cand_text in (text, own_norm, aria):
                if cand_text and label_lower in cand_text.lower():
                    tag = (meta.get("tag") or "").lower()
                    if tag in _LABEL_TAGS or len(cand_text) < 200:
                        matched = True
                    break
            if not matched:
                continue

            dist = 999
            cur = nid
            depth = 0
            while cur and depth < 256:
                if cur in t_ancestors:
                    dist = t_ancestors[cur] + depth
                    break
                cur = self.kg.parent_of.get(cur)
                depth += 1
            candidates.append((dist, nid, meta))

        if not candidates:
            return []
        candidates.sort(key=lambda x: x[0])
        results: List[Dict[str, Any]] = []
        for dist, lab_id, lab_meta in candidates[:2]:
            stab = self.kg._compute_stability_info(lab_meta)
            entry = {
                "node_id": lab_id,
                "metadata": self._slim_meta(lab_meta),
                "stability": stab,
                "spatial_relation": self.spatial_relation(target_meta, lab_meta),
                "tree_relation": self._compute_tree_relation(target_id, lab_id),
                "usable_as_anchor": True,
                "label_match": True,
            }
            if stab.get("has_stable_attrs") or stab.get("has_text"):
                entry["locator_suggestions"] = self._compute_locator_suggestions(lab_meta, stab)
            results.append(entry)
            already_seen.add(lab_id)
        return results

    # ---- scoping container ----
    def _is_scoping_container(self, meta: Dict[str, Any]) -> bool:
        tag = (meta.get("tag") or "").lower()
        role = (meta.get("role") or (meta.get("attrs", {}) or {}).get("role") or "").lower()
        return role in _SCOPING_ROLES or tag in _SCOPING_TAGS

    def _find_scoping_container(self, target_id: str) -> Optional[Dict[str, Any]]:
        cur = self.kg.parent_of.get(target_id)
        depth = 0
        while cur and depth < 30:
            meta = self.kg.node_metadata.get(cur, {})
            if self._is_scoping_container(meta):
                stab = self.kg._compute_stability_info(meta)
                return {
                    "node_id": cur,
                    "metadata": self._slim_meta(meta),
                    "stability": stab,
                    "locator_suggestions": self._compute_locator_suggestions(meta, stab),
                }
            cur = self.kg.parent_of.get(cur)
            depth += 1
        return None

    # ---- locator suggestions ----
    def _compute_locator_suggestions(
        self,
        meta: Dict[str, Any],
        stability: Dict[str, Any],
    ) -> List[str]:
        """Return prioritized XPath suggestions (data-testid > aria-* > role+text > id > text)."""
        suggestions: List[str] = []
        attrs = meta.get("attrs", {}) or {}
        tag = (meta.get("tag") or "*").lower() or "*"

        stable_data = stability.get("stable_data_attrs") or {}
        # data-testid first
        dt = stable_data.get("data-testid") or attrs.get("data-testid")
        if dt:
            suggestions.append(f"//*[@data-testid='{_escape_xp(dt)}']")
        # other data-* (ag-grid col-id etc.)
        for k, v in stable_data.items():
            if k == "data-testid":
                continue
            if isinstance(v, str):
                suggestions.append(f"//*[@{k}='{_escape_xp(v)}']")

        aria_label = attrs.get("aria-label")
        if aria_label:
            suggestions.append(f"//*[@aria-label='{_escape_xp(aria_label)}']")

        role = stability.get("role") or meta.get("role")
        text_own = meta.get("text_own_norm") or meta.get("text")
        if role and text_own:
            suggestions.append(
                f"//*[@role='{_escape_xp(role)}' and contains(normalize-space(.), '{_escape_xp(text_own[:50])}')]"
            )

        stable_id = stability.get("id")
        if stable_id:
            suggestions.append(f"//*[@id='{_escape_xp(stable_id)}']")

        placeholder = attrs.get("placeholder")
        if placeholder:
            suggestions.append(f"//{tag}[@placeholder='{_escape_xp(placeholder)}']")

        if text_own:
            text_src = stability.get("text_source", "own")
            if text_src == "own":
                suggestions.append(f"//{tag}[normalize-space(text())='{_escape_xp(text_own[:50])}']")
            else:
                suggestions.append(f"//{tag}[contains(., '{_escape_xp(text_own[:50])}')]")

        # De-dupe preserving order
        seen: set = set()
        out: List[str] = []
        for s in suggestions:
            if s not in seen:
                seen.add(s)
                out.append(s)
        return out[:10]


def _escape_xp(s: str) -> str:
    """Escape a string for safe inclusion inside an XPath literal."""
    if not isinstance(s, str):
        return ""
    return s.replace("'", "&#39;")
