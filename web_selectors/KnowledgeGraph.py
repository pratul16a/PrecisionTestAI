"""
KnowledgeGraph.py — V2 Knowledge Graph (ported from V2_Req/CAPTURE_KnowledgeGraph.md)

Two classes:
    EdgeTypes      — 29 semantic edge-type constants + tag/role → container maps
    KnowledgeGraph — DOM tree → indexed graph with semantic edges + stability info

Also exports GraphTraversal (defined here in the V2 source; kept split in GraphTraversal.py
for modularity). KGNode is kept as a thin compatibility wrapper.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class EdgeTypes:
    """Constants for all supported edge/relation types in the Knowledge Graph."""

    # Structural
    PARENT_OF = "parent_of"
    CHILD_OF = "child_of"

    # Containment
    CONTAINED_IN_FORM = "contained_in_form"
    CONTAINED_IN_DIALOG = "contained_in_dialog"
    CONTAINED_IN_TABLE = "contained_in_table"
    CONTAINED_IN_GRID = "contained_in_grid"
    CONTAINED_IN_NAV = "contained_in_nav"
    CONTAINED_IN_SECTION = "contained_in_section"
    CONTAINED_IN_FIELDSET = "contained_in_fieldset"
    CONTAINED_IN_MENU = "contained_in_menu"
    CONTAINED_IN_TOOLBAR = "contained_in_toolbar"
    CONTAINED_IN_TABPANEL = "contained_in_tabpanel"
    CONTAINED_IN_LISTBOX = "contained_in_listbox"
    CONTAINED_IN_HEADER = "contained_in_header"
    CONTAINED_IN_FOOTER = "contained_in_footer"
    CONTAINED_IN_ASIDE = "contained_in_aside"
    CONTAINED_IN_MAIN = "contained_in_main"

    # Label / describedby
    LABEL_FOR = "label_for"
    LABELED_BY = "labeled_by"
    ARIA_LABELLEDBY = "aria_labelledby"
    ARIA_DESCRIBEDBY = "aria_describedby"

    # Table / Grid
    HEADER_OF = "header_of"
    ROW_OF = "row_of"
    CELL_OF_ROW = "cell_of_row"
    CELL_OF_COLUMN = "cell_of_column"
    CAPTION_OF = "caption_of"

    # Grouping
    GROUPED_BY = "grouped_by"
    LEGEND_OF = "legend_of"

    # Tabs
    TAB_FOR = "tab_for"
    TAB_OF = "tab_of"

    CONTAINMENT_TYPES = frozenset({
        CONTAINED_IN_FORM, CONTAINED_IN_DIALOG, CONTAINED_IN_TABLE,
        CONTAINED_IN_GRID, CONTAINED_IN_NAV, CONTAINED_IN_SECTION,
        CONTAINED_IN_FIELDSET, CONTAINED_IN_MENU, CONTAINED_IN_TOOLBAR,
        CONTAINED_IN_TABPANEL, CONTAINED_IN_LISTBOX, CONTAINED_IN_HEADER,
        CONTAINED_IN_FOOTER, CONTAINED_IN_ASIDE, CONTAINED_IN_MAIN,
    })

    TAG_TO_CONTAINER_EDGE = {
        "form": CONTAINED_IN_FORM,
        "dialog": CONTAINED_IN_DIALOG,
        "table": CONTAINED_IN_TABLE,
        "nav": CONTAINED_IN_NAV,
        "section": CONTAINED_IN_SECTION,
        "fieldset": CONTAINED_IN_FIELDSET,
        "header": CONTAINED_IN_HEADER,
        "footer": CONTAINED_IN_FOOTER,
        "aside": CONTAINED_IN_ASIDE,
        "main": CONTAINED_IN_MAIN,
    }

    ROLE_TO_CONTAINER_EDGE = {
        "form": CONTAINED_IN_FORM,
        "dialog": CONTAINED_IN_DIALOG,
        "alertdialog": CONTAINED_IN_DIALOG,
        "grid": CONTAINED_IN_GRID,
        "treegrid": CONTAINED_IN_GRID,
        "table": CONTAINED_IN_TABLE,
        "navigation": CONTAINED_IN_NAV,
        "region": CONTAINED_IN_SECTION,
        "menu": CONTAINED_IN_MENU,
        "menubar": CONTAINED_IN_MENU,
        "toolbar": CONTAINED_IN_TOOLBAR,
        "tabpanel": CONTAINED_IN_TABPANEL,
        "listbox": CONTAINED_IN_LISTBOX,
        "complementary": CONTAINED_IN_ASIDE,
        "banner": CONTAINED_IN_HEADER,
        "contentinfo": CONTAINED_IN_FOOTER,
        "main": CONTAINED_IN_MAIN,
    }

    CONTAINER_NAMES = {
        CONTAINED_IN_FORM: "form",
        CONTAINED_IN_DIALOG: "dialog",
        CONTAINED_IN_TABLE: "table",
        CONTAINED_IN_GRID: "grid",
        CONTAINED_IN_NAV: "nav",
        CONTAINED_IN_SECTION: "section",
        CONTAINED_IN_FIELDSET: "fieldset",
        CONTAINED_IN_MENU: "menu",
        CONTAINED_IN_TOOLBAR: "toolbar",
        CONTAINED_IN_TABPANEL: "tabpanel",
        CONTAINED_IN_LISTBOX: "listbox",
        CONTAINED_IN_HEADER: "header",
        CONTAINED_IN_FOOTER: "footer",
        CONTAINED_IN_ASIDE: "aside",
        CONTAINED_IN_MAIN: "main",
    }


def _normalize_parser_node(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a DOMSemanticParser flat node into V2 metadata shape.

    Current parser emits fields like ariaLabel, dataTestId, directText. The V2 code expects:
        tag, role, text, text_own_norm, text_content_raw, attrs{...},
        rect, visible, xpath, frame_url, isFrame, isShadow,
        has_style_script_pollution.
    """
    if not isinstance(entry, dict):
        return {}

    tag = (entry.get("tag") or "").strip().lower()

    flat_attrs = {
        "id": entry.get("id"),
        "class": entry.get("class"),
        "role": entry.get("role"),
        "aria-label": entry.get("ariaLabel"),
        "aria-describedby": entry.get("ariaDescribedBy"),
        "aria-labelledby": entry.get("ariaLabelledBy"),
        "aria-controls": entry.get("ariaControls"),
        "aria-expanded": entry.get("ariaExpanded"),
        "aria-selected": entry.get("ariaSelected"),
        "aria-checked": entry.get("ariaChecked"),
        "placeholder": entry.get("placeholder"),
        "data-testid": entry.get("dataTestId"),
        "name": entry.get("name"),
        "type": entry.get("type"),
        "value": entry.get("value"),
        "href": entry.get("href"),
        "src": entry.get("src"),
        "title": entry.get("title"),
        "for": entry.get("htmlFor"),
        "contenteditable": entry.get("contenteditable"),
    }
    for k, v in (entry.get("attrs") or {}).items():
        if v is not None:
            flat_attrs[k] = v
    attrs = {k: v for k, v in flat_attrs.items() if v not in (None, "")}

    direct_text = (entry.get("directText") or "").strip()
    full_text = (entry.get("text") or "").strip()

    meta: Dict[str, Any] = {
        "tag": tag,
        "role": entry.get("role") or attrs.get("role") or "",
        "attrs": attrs,
        "text": direct_text or full_text,
        "text_own_norm": " ".join(direct_text.split()) if direct_text else "",
        "text_content_raw": full_text,
        "text_is_own": bool(direct_text) and direct_text == full_text,
        "innerText": full_text,
        "xpath": entry.get("xpath", ""),
        "visible": bool(entry.get("visible", False)),
        "rect": entry.get("rect") or {},
        "depth": entry.get("depth", 0),
        "frame_url": entry.get("frame_url", "") or entry.get("frameUrl", ""),
        "frame_name": entry.get("frame_name", ""),
        "isFrame": bool(entry.get("isFrame", False)) or tag == "iframe",
        "isShadow": bool(entry.get("isShadow", False)),
        "has_style_script_pollution": bool(entry.get("has_style_script_pollution", False)),
        "state": entry.get("state") or {},
        "style": entry.get("style") or {},
    }
    return meta


class KnowledgeGraph:
    """DOM parse tree → indexed graph with semantic edges."""

    def __init__(self) -> None:
        self.nodes: Set[str] = set()
        self.relations: List[Tuple[str, str, str]] = []
        self.node_metadata: Dict[str, Dict[str, Any]] = {}
        self.node_to_frame: Dict[str, Optional[str]] = {}
        self.frame_tree: Dict[str, list] = {}
        self.parent_of: Dict[str, str] = {}

        self._edges_by_type: Dict[str, List[Tuple[str, str]]] = {}
        self._edges_from: Dict[str, List[Tuple[str, str]]] = {}
        self._edges_to: Dict[str, List[Tuple[str, str]]] = {}

        self._container_children: Dict[str, Set[str]] = {}
        self._node_containers: Dict[str, List[Tuple[str, str]]] = {}
        self._label_for_index: Dict[str, str] = {}
        self._labeled_by_index: Dict[str, str] = {}
        self._table_structures: Dict[str, Dict[str, Any]] = {}

        self.parsed: Any = None
        self._local_counter: int = 0

    # ---- ingestion ----
    def load_parsed_structure(self, parsed_json: Any) -> None:
        if isinstance(parsed_json, dict) and "main" in parsed_json:
            self.parsed = parsed_json["main"]
        else:
            self.parsed = parsed_json

    def add_node(self, node_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.nodes.add(node_id)
        if metadata is not None:
            self.node_metadata[node_id] = metadata

    def add_relation(self, from_id: str, relation: str, to_id: str) -> None:
        self.relations.append((from_id, relation, to_id))
        self._edges_by_type.setdefault(relation, []).append((from_id, to_id))
        self._edges_from.setdefault(from_id, []).append((relation, to_id))
        self._edges_to.setdefault(to_id, []).append((relation, from_id))

    def get_edges_by_type(self, relation_type: str) -> List[Tuple[str, str]]:
        return self._edges_by_type.get(relation_type, [])

    def get_edges_from(self, node_id: str, relation_type: Optional[str] = None) -> List[Tuple[str, str]]:
        edges = self._edges_from.get(node_id, [])
        if relation_type:
            return [(r, t) for r, t in edges if r == relation_type]
        return edges

    def get_edges_to(self, node_id: str, relation_type: Optional[str] = None) -> List[Tuple[str, str]]:
        edges = self._edges_to.get(node_id, [])
        if relation_type:
            return [(r, f) for r, f in edges if r == relation_type]
        return edges

    def _find_label_for(self, input_id: str) -> Optional[str]:
        return self._label_for_index.get(input_id)

    def _find_labeled_input(self, label_id: str) -> Optional[str]:
        return self._labeled_by_index.get(label_id)

    def _frame_prefix(self, frame_id: Optional[str]) -> str:
        return str(frame_id or "frame-0")

    def _make_node_id(
        self,
        entry: Dict[str, Any],
        *,
        is_frame: bool,
        effective_frame_id: Optional[str],
    ) -> Optional[str]:
        if is_frame and entry.get("frameId"):
            return entry.get("frameId")
        local_id = entry.get("local_id")
        xpath = entry.get("xpath")
        prefix = self._frame_prefix(effective_frame_id)
        if not local_id:
            self._local_counter += 1
            local_id = f"n{self._local_counter}"
        return f"{prefix}::{local_id}"  # xpath fallback skipped — DOMSemanticParser always has local_id after this

    # ---- main graph build ----
    def convert_to_graph(self, node: Optional[Dict[str, Any]] = None, parent_id: Optional[str] = None) -> Optional[str]:
        """Build the graph from the loaded parsed tree.

        Signature supports both V2 (no args; walks self.parsed) and the legacy recursive form.
        """
        if node is None and parent_id is None:
            self._build_from_parsed()
            self._build_semantic_edges()
            return None
        return self._traverse(node or {}, parent_id, parent_frame=None)

    def _build_from_parsed(self) -> None:
        root = self.parsed
        if root is None:
            return
        if isinstance(root, list):
            for frame_entry in root:
                self._traverse(frame_entry, None, None)
        else:
            self._traverse(root, None, None)

    def _traverse(
        self,
        entry: Dict[str, Any],
        parent_id: Optional[str],
        parent_frame: Optional[str],
    ) -> Optional[str]:
        if not entry or not isinstance(entry, dict):
            return None

        is_frame = bool(entry.get("isFrame", False)) or (entry.get("tag") or "").lower() == "iframe"
        frame_id = entry.get("frameId") if is_frame else parent_frame

        cur_id = self._make_node_id(entry, is_frame=is_frame, effective_frame_id=frame_id)
        if not cur_id:
            return None

        meta = _normalize_parser_node(entry)
        if is_frame:
            meta.setdefault("isFrame", True)

        self.add_node(cur_id, meta)
        self.node_to_frame[cur_id] = frame_id

        if is_frame:
            self.frame_tree.setdefault(cur_id, [])
            if parent_frame and parent_frame in self.frame_tree:
                self.frame_tree[parent_frame].append(cur_id)

        if parent_id:
            self.add_relation(parent_id, EdgeTypes.PARENT_OF, cur_id)
            self.add_relation(cur_id, EdgeTypes.CHILD_OF, parent_id)
            self.parent_of[cur_id] = parent_id

        for child in entry.get("children", []) or []:
            self._traverse(child, cur_id, frame_id)

        # Handle iframes attached as _iframes array
        for iframe_data in entry.get("_iframes", []) or []:
            itree = iframe_data.get("tree") if isinstance(iframe_data, dict) else None
            if itree:
                iframe_meta = dict(itree)
                iframe_meta.setdefault("isFrame", True)
                iframe_meta.setdefault("frame_url", iframe_data.get("url", ""))
                iframe_meta.setdefault("frame_name", iframe_data.get("name", ""))
                iframe_meta.setdefault("frameId", f"frame-{len(self.frame_tree) + 1}")
                self._traverse(iframe_meta, cur_id, iframe_meta["frameId"])

        return cur_id

    # ---- semantic edge construction ----
    def _build_semantic_edges(self) -> None:
        logger.info("[KG] Building semantic edges for %d nodes...", len(self.nodes))
        self._build_containment_edges()
        self._build_label_edges()
        self._build_table_structure_edges()
        self._build_grouping_edges()
        self._build_tab_edges()

        semantic_edge_count = sum(
            len(edges)
            for etype, edges in self._edges_by_type.items()
            if etype not in (EdgeTypes.PARENT_OF, EdgeTypes.CHILD_OF)
        )
        logger.info(
            "[KG] Semantic edges: %d | containers=%d | label_for=%d | tables=%d",
            semantic_edge_count,
            len(self._container_children),
            len(self._label_for_index),
            len(self._table_structures),
        )

    def _build_containment_edges(self) -> None:
        container_nodes: List[Tuple[str, str]] = []
        for nid in self.nodes:
            meta = self.node_metadata.get(nid, {})
            if not meta:
                continue
            tag = (meta.get("tag") or "").lower().strip()
            attrs = meta.get("attrs", {}) or {}
            role = (attrs.get("role") or meta.get("role") or "").lower().strip()

            edge_type = None
            if role and role in EdgeTypes.ROLE_TO_CONTAINER_EDGE:
                edge_type = EdgeTypes.ROLE_TO_CONTAINER_EDGE[role]
            elif tag and tag in EdgeTypes.TAG_TO_CONTAINER_EDGE:
                edge_type = EdgeTypes.TAG_TO_CONTAINER_EDGE[tag]
            if edge_type:
                container_nodes.append((nid, edge_type))

        logger.debug("[KG] Found %d semantic containers", len(container_nodes))

        for container_id, edge_type in container_nodes:
            descendants: Set[str] = set()
            queue = [container_id]
            visited: Set[str] = set()
            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)
                children = [
                    to_id for rel, to_id in self._edges_from.get(cur, [])
                    if rel == EdgeTypes.PARENT_OF
                ]
                for c in children:
                    if c in descendants:
                        continue
                    descendants.add(c)
                    queue.append(c)
                    self.add_relation(c, edge_type, container_id)
                    self._node_containers.setdefault(c, []).append((edge_type, container_id))
            if descendants:
                self._container_children[container_id] = descendants

    def _build_label_edges(self) -> None:
        # <label for="X"> → input[id=X]
        id_index: Dict[str, str] = {}
        for nid, meta in self.node_metadata.items():
            attrs = meta.get("attrs", {}) or {}
            _id = attrs.get("id")
            if isinstance(_id, str) and _id:
                id_index[_id] = nid

        for nid, meta in self.node_metadata.items():
            tag = (meta.get("tag") or "").lower()
            attrs = meta.get("attrs", {}) or {}
            if tag == "label":
                for_id = attrs.get("for")
                if isinstance(for_id, str) and for_id in id_index:
                    target_nid = id_index[for_id]
                    self.add_relation(nid, EdgeTypes.LABEL_FOR, target_nid)
                    self.add_relation(target_nid, EdgeTypes.LABELED_BY, nid)
                    self._label_for_index[target_nid] = nid
                    self._labeled_by_index[nid] = target_nid

            # aria-labelledby → space-separated list of ids
            alb = attrs.get("aria-labelledby")
            if isinstance(alb, str) and alb.strip():
                for ref_id in alb.split():
                    if ref_id in id_index:
                        self.add_relation(nid, EdgeTypes.ARIA_LABELLEDBY, id_index[ref_id])
                        self._label_for_index.setdefault(nid, id_index[ref_id])

            adb = attrs.get("aria-describedby")
            if isinstance(adb, str) and adb.strip():
                for ref_id in adb.split():
                    if ref_id in id_index:
                        self.add_relation(nid, EdgeTypes.ARIA_DESCRIBEDBY, id_index[ref_id])

    def _build_table_structure_edges(self) -> None:
        for nid, meta in self.node_metadata.items():
            tag = (meta.get("tag") or "").lower()
            role = (meta.get("role") or (meta.get("attrs", {}) or {}).get("role") or "").lower()
            attrs = meta.get("attrs", {}) or {}

            if tag == "table" or role in ("grid", "treegrid", "table"):
                rows: List[str] = []
                headers: List[str] = []
                for c in self._container_children.get(nid, set()):
                    cm = self.node_metadata.get(c, {})
                    ctag = (cm.get("tag") or "").lower()
                    crole = (cm.get("role") or (cm.get("attrs", {}) or {}).get("role") or "").lower()
                    if ctag == "tr" or crole == "row":
                        rows.append(c)
                        self.add_relation(c, EdgeTypes.ROW_OF, nid)
                    if ctag == "th" or crole == "columnheader":
                        headers.append(c)
                        self.add_relation(c, EdgeTypes.HEADER_OF, nid)
                    if ctag == "caption":
                        self.add_relation(c, EdgeTypes.CAPTION_OF, nid)
                self._table_structures[nid] = {
                    "rows": rows,
                    "headers": headers,
                    "header_texts": {h: (self.node_metadata.get(h, {}).get("text") or "") for h in headers},
                    "cells": {},
                }

            # col-id linking (ag-Grid)
            col_id = attrs.get("col-id") or attrs.get("aria-colindex")
            if col_id and tag in ("td", "th") or (role in ("gridcell", "columnheader") and col_id):
                # store on the table structures we've already initialized (best-effort)
                for tbl_id, ts in self._table_structures.items():
                    if nid in self._container_children.get(tbl_id, set()):
                        ts.setdefault("cells", {}).setdefault(col_id, []).append(nid)

        # cell-of-row: any td/gridcell whose parent is tr/row
        for nid, meta in self.node_metadata.items():
            tag = (meta.get("tag") or "").lower()
            role = (meta.get("role") or (meta.get("attrs", {}) or {}).get("role") or "").lower()
            if tag in ("td", "th") or role in ("gridcell", "columnheader"):
                p = self.parent_of.get(nid)
                if p:
                    ptag = (self.node_metadata.get(p, {}).get("tag") or "").lower()
                    prole = (self.node_metadata.get(p, {}).get("role") or "").lower()
                    if ptag == "tr" or prole == "row":
                        self.add_relation(nid, EdgeTypes.CELL_OF_ROW, p)

    def _build_grouping_edges(self) -> None:
        for nid, meta in self.node_metadata.items():
            tag = (meta.get("tag") or "").lower()
            role = (meta.get("role") or (meta.get("attrs", {}) or {}).get("role") or "").lower()
            if tag == "fieldset" or role == "group":
                for c in self._container_children.get(nid, set()):
                    self.add_relation(c, EdgeTypes.GROUPED_BY, nid)
            if tag == "legend":
                p = self.parent_of.get(nid)
                if p and (self.node_metadata.get(p, {}).get("tag") or "").lower() == "fieldset":
                    self.add_relation(nid, EdgeTypes.LEGEND_OF, p)

    def _build_tab_edges(self) -> None:
        id_index = {}
        for nid, meta in self.node_metadata.items():
            _id = (meta.get("attrs", {}) or {}).get("id")
            if _id:
                id_index[_id] = nid

        for nid, meta in self.node_metadata.items():
            attrs = meta.get("attrs", {}) or {}
            role = (meta.get("role") or attrs.get("role") or "").lower()
            if role == "tab":
                controls = attrs.get("aria-controls")
                if isinstance(controls, str) and controls:
                    for ref in controls.split():
                        if ref in id_index:
                            self.add_relation(nid, EdgeTypes.TAB_FOR, id_index[ref])
                            self.add_relation(id_index[ref], EdgeTypes.TAB_OF, nid)

    # ---- stability info ----
    def _compute_stability_info(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Per-node stability: text_source, stable attrs, reject dynamic IDs/classes."""
        attrs = meta.get("attrs", {}) or {}
        role = meta.get("role") or attrs.get("role") or ""

        text = (meta.get("text") or "").strip()
        if not text:
            raw_text = (meta.get("text_content_raw") or "").strip()
            if raw_text and len(raw_text) <= 80 and "\n" not in raw_text:
                text = raw_text

        def _looks_random(val: Any) -> bool:
            if not val or not isinstance(val, str):
                return True
            s = val.strip()
            if not s or len(s) > 80:
                return True
            low = s.lower()
            if low.startswith("data:") or ("base64" in low and len(low) > 40):
                return True
            if s.isdigit():
                return True
            if re.match(r"^[a-f0-9]{8,}$", low):
                return True
            if re.match(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$", low):
                return True
            if len(low) >= 16:
                hex_chars = sum(1 for c in low if c in "0123456789abcdef")
                if hex_chars / len(low) > 0.8:
                    return True
            return False

        _GRID_BARE_ATTRS = frozenset({
            "col-id", "row-id", "row-index",
            "aria-colindex", "aria-rowindex", "aria-colcount", "aria-rowcount",
        })
        stable_data_attrs: Dict[str, str] = {}
        for attr_name, attr_val in attrs.items():
            if not isinstance(attr_name, str):
                continue
            lname = attr_name.lower().strip()
            if lname.startswith(("data-", "ag-", "test-", "qa-", "auto-")):
                if isinstance(attr_val, str) and not _looks_random(attr_val):
                    stable_data_attrs[attr_name] = attr_val.strip()
            elif lname in _GRID_BARE_ATTRS:
                if isinstance(attr_val, str) and not _looks_random(attr_val):
                    stable_data_attrs[attr_name] = attr_val.strip()

        _own_text = (meta.get("text") or "").strip()
        if _own_text:
            text_source = "own"
        elif text:
            text_source = "descendant"
        else:
            text_source = "none"

        stability: Dict[str, Any] = {
            "stable_data_attrs": stable_data_attrs if stable_data_attrs else None,
            "aria_label": attrs.get("aria-label") or None,
            "aria_labelledby": attrs.get("aria-labelledby") or None,
            "aria_controls": attrs.get("aria-controls") or None,
            "role": role or None,
            "id": None,
            "name": attrs.get("name") or None,
            "placeholder": attrs.get("placeholder") or None,
            "title": attrs.get("title") or None,
            "for_attr": attrs.get("for") or None,
            "has_text": bool(text),
            "text_length": len(text) if text else 0,
            "text_source": text_source,
            "aria_expanded": attrs.get("aria-expanded"),
            "aria_selected": attrs.get("aria-selected"),
            "aria_checked": attrs.get("aria-checked"),
        }

        dynamic_patterns = [
            r"[a-f0-9]{16,}",
            r"[a-z]+-[a-f0-9]{6,}$",
            r"^\d+$",
            r"^:r\d+:$",
            r"ember\d+$",
            r"text-gen\d+$",
            r"[a-z]+-\d{4,}$",
            r"jpmui-\d+.*",
            r"^jpmui-.*",
            r"label-salt-\d+$",
            r"HelperText-salt-\d+$",
            r"salt-\d+$",
        ]
        node_id = attrs.get("id")
        if isinstance(node_id, str) and node_id:
            is_dynamic = any(re.match(p, node_id, re.IGNORECASE) for p in dynamic_patterns)
            if not is_dynamic:
                stability["id"] = node_id
            else:
                stability["id_rejected_dynamic"] = node_id

        def _class_looks_random(c: str) -> bool:
            if not c or len(c) < 2:
                return True
            low = c.lower()
            if c.isdigit():
                return True
            if re.search(r"[a-f0-9]{6,}$", low):
                return True
            if re.match(r"^(jss|sc-|css-|emotion-|styled-)[a-z0-9]+", low):
                return True
            if re.search(r"_[a-z]+_[a-z0-9]{5,}$", low):
                return True
            if re.match(r"^Mui[A-Z].*\d+$", c):
                return True
            if len(c) >= 12:
                digit_ratio = sum(ch.isdigit() for ch in c) / len(c)
                if digit_ratio > 0.4:
                    return True
            return False

        cls = attrs.get("class", "")
        if isinstance(cls, list):
            cls = " ".join(c for c in cls if isinstance(c, str))
        if cls:
            classes = str(cls).split()
            stable = [c for c in classes if not _class_looks_random(c)]
            if stable:
                stability["stable_classes"] = stable[:5]

        has_stable_attrs = bool(
            stability.get("stable_data_attrs")
            or stability.get("aria_label")
            or stability.get("role")
            or stability.get("id")
            or stability.get("name")
            or stability.get("placeholder")
            or stability.get("title")
            or stability.get("stable_classes")
        )
        stability["has_stable_attrs"] = has_stable_attrs
        return stability

    # ---- diagnostics / utilities ----
    def all_node_ids(self) -> Iterable[str]:
        return iter(self.nodes)

    def get_children_ids(self, nid: str) -> List[str]:
        return [t for r, t in self._edges_from.get(nid, []) if r == EdgeTypes.PARENT_OF]

    # Legacy-compat for the old KGNode-based API used by any still-extant callers
    def get_node(self, nid: str) -> Optional["KGNode"]:
        if nid in self.node_metadata:
            return KGNode(nid, self, self.node_metadata[nid])
        return None

    def get_ancestors(self, nid: str, max_depth: int = 15) -> List["KGNode"]:
        out: List[KGNode] = []
        cur = self.parent_of.get(nid)
        depth = 0
        while cur and depth < max_depth:
            out.append(KGNode(cur, self, self.node_metadata.get(cur, {})))
            cur = self.parent_of.get(cur)
            depth += 1
        return out

    def get_all_nodes(self) -> List["KGNode"]:
        return [KGNode(nid, self, self.node_metadata.get(nid, {})) for nid in self.nodes]

    def validate_graph(self) -> Dict[str, Any]:
        issues: Dict[str, Any] = {
            "nodes_missing_metadata": [],
            "orphan_nodes": [],
            "frames_without_children": [],
            "total_nodes": len(self.nodes),
            "total_relations": len(self.relations),
        }
        for nid in self.nodes:
            if nid not in self.node_metadata or not self.node_metadata[nid]:
                issues["nodes_missing_metadata"].append(nid)
        child_nodes = {to for _, r, to in ((f, r, t) for f, r, t in self.relations) if r == EdgeTypes.PARENT_OF}
        for nid in self.nodes:
            if nid not in child_nodes and len(self.nodes) > 1:
                issues["orphan_nodes"].append(nid)
        for nid, meta in self.node_metadata.items():
            if meta.get("tag") == "iframe":
                has_child = any(f == nid and r == EdgeTypes.PARENT_OF for f, r, _ in self.relations)
                if not has_child:
                    issues["frames_without_children"].append(nid)
        return issues


class KGNode:
    """Compatibility wrapper around a node metadata dict + its ID.

    The V2 search/traversal code reads meta dicts directly; KGNode is retained only for
    any caller still using attribute-access."""

    __slots__ = ("id", "_kg", "_meta")

    def __init__(self, node_id: str, kg: KnowledgeGraph, meta: Dict[str, Any]):
        self.id = node_id
        self._kg = kg
        self._meta = meta or {}

    @property
    def meta(self) -> Dict[str, Any]:
        return self._meta

    @property
    def tag(self) -> str:
        return (self._meta.get("tag") or "").lower()

    @property
    def text(self) -> str:
        return self._meta.get("text") or ""

    @property
    def direct_text(self) -> str:
        return self._meta.get("text_own_norm") or self._meta.get("text") or ""

    @property
    def role(self) -> str:
        return self._meta.get("role") or (self._meta.get("attrs", {}) or {}).get("role", "") or ""

    @property
    def aria_label(self) -> str:
        return (self._meta.get("attrs", {}) or {}).get("aria-label", "") or ""

    @property
    def placeholder(self) -> str:
        return (self._meta.get("attrs", {}) or {}).get("placeholder", "") or ""

    @property
    def data_testid(self) -> str:
        return (self._meta.get("attrs", {}) or {}).get("data-testid", "") or ""

    @property
    def element_id(self) -> str:
        return (self._meta.get("attrs", {}) or {}).get("id", "") or ""

    @property
    def class_name(self) -> str:
        cls = (self._meta.get("attrs", {}) or {}).get("class", "") or ""
        if isinstance(cls, list):
            cls = " ".join(cls)
        return str(cls)

    @property
    def xpath(self) -> str:
        return self._meta.get("xpath", "")

    @property
    def visible(self) -> bool:
        return bool(self._meta.get("visible", False))

    @property
    def rect(self) -> dict:
        return self._meta.get("rect") or {}

    @property
    def frame_url(self) -> str:
        return self._meta.get("frame_url", "") or ""

    @property
    def frame_name(self) -> str:
        return self._meta.get("frame_name", "") or ""

    @property
    def parent_id(self) -> Optional[str]:
        return self._kg.parent_of.get(self.id)

    @property
    def child_ids(self) -> List[str]:
        return self._kg.get_children_ids(self.id)

    @property
    def sibling_ids(self) -> List[str]:
        p = self.parent_id
        if not p:
            return []
        return [c for c in self._kg.get_children_ids(p) if c != self.id]
