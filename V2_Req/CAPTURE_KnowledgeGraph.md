# CAPTURE: KnowledgeGraph.py
## Transcription from 7 screenshots (6 unique — images 6 & 7 are duplicates)
## File: precisiontestai/src/playwright_mcp/code/web_selectors/KnowledgeGraph.py
## Coverage: lines ~1–2241 (with gaps — see MISSING SECTIONS below)

---

## FILE SUMMARY

This file defines the **Knowledge Graph** that transforms the flat DOM parse tree
(from DOMSemanticParser) into a rich, queryable graph with semantic edges.
Two main classes: `EdgeTypes` (constants) and `KnowledgeGraph` (graph + builders).
Also contains `_compute_stability_info()` — the enhanced context builder that tells
the LLM which attributes are stable for locator building.

---

## CLASS: EdgeTypes (lines 1–96)

```python
from typing import Dict, List, Any, Optional, Set, Tuple
import logging
logger = logging.getLogger(__name__)

# Semantic Edge Types
class EdgeTypes:
    """Constants for all supported edge/relation types in the Knowledge Graph."""

    # --- Structural (DOM tree) ---
    PARENT_OF = "parent_of"
    CHILD_OF = "child_of"

    # --- Semantic containment (element is logically inside a container) ---
    CONTAINED_IN_FORM = "contained in form"
    CONTAINED_IN_DIALOG = "contained in dialog"
    CONTAINED_IN_TABLE = "contained in table"
    CONTAINED_IN_GRID = "contained in grid"
    CONTAINED_IN_NAV = "contained in nav"
    CONTAINED_IN_SECTION = "contained in section"
    CONTAINED_IN_FIELDSET = "contained in fieldset"
    CONTAINED_IN_MENU = "contained in menu"
    CONTAINED_IN_TOOLBAR = "contained in toolbar"
    CONTAINED_IN_TABPANEL = "contained in tabpanel"
    CONTAINED_IN_LISTBOX = "contained in listbox"
    CONTAINED_IN_HEADER = "contained in header"
    CONTAINED_IN_FOOTER = "contained in footer"
    CONTAINED_IN_ASIDE = "contained in aside"
    CONTAINED_IN_MAIN = "contained in main"

    # --- Label / describedby associations ---
    LABEL_FOR = "label_for"       # <label for="X"> → <input id="X">
    LABELED_BY = "labeled_by"     # target → label (reverse of LABEL_FOR)
    ARIA_LABELLEDBY = "aria_labelledby"   # target aria-labelledby → label element
    ARIA_DESCRIBEDBY = "aria_describedby" # target aria-describedby → description element

    # --- Table / Grid structure ---
    HEADER_OF = "header_of"       # <th> → column
    ROW_OF = "row_of"             # <tr> → <table>/<tbody>
    CELL_OF_ROW = "cell_of_row"   # <td>/<th> → <tr>
    CELL_OF_COLUMN = "cell_of_column"  # cell → column (via col-id or position)
    CAPTION_OF = "caption_of"     # <caption> → <table>

    # --- Grouping ---
    GROUPED_BY = "grouped_by"     # element → grouping container (fieldset, optgroup, etc.)
    LEGEND_OF = "legend_of"       # <legend> → <fieldset>

    # --- Tabs ---
    TAB_FOR = "tab_for"           # tab button → tabpanel
    TAB_OF = "tab_of"             # tabpanel → tab button (reverse)

    # --- All containment edge types (for container queries) ---
    CONTAINMENT_TYPES = frozenset({
        CONTAINED_IN_FORM, CONTAINED_IN_DIALOG, CONTAINED_IN_TABLE,
        CONTAINED_IN_GRID, CONTAINED_IN_NAV, CONTAINED_IN_SECTION,
        CONTAINED_IN_FIELDSET, CONTAINED_IN_MENU, CONTAINED_IN_TOOLBAR,
        CONTAINED_IN_TABPANEL, CONTAINED_IN_LISTBOX, CONTAINED_IN_HEADER,
        CONTAINED_IN_FOOTER, CONTAINED_IN_ASIDE, CONTAINED_IN_MAIN,
    })

    # --- Map from tag/role to containment edge type ---
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

    # --- Map from container edge type → human-friendly name ---
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
```

**29 edge types** organized into 6 categories: structural, containment, label/describedby,
table/grid, grouping, and tabs. The containment system supports **15 container types**
with both tag-based and ARIA role-based detection.

---

## CLASS: KnowledgeGraph (lines ~119–178+)

### __init__ — All Data Structures

```python
class KnowledgeGraph:

    def __init__(self):
        self.nodes: Set[str] = set()
        self.relations: List[List[str]] = []
        self.node_metadata: Dict[str, Dict[str, Any]] = {}
        self.node_to_frame: Dict[str, str] = {}
        self.frame_tree: Dict[str, list] = {}
        self.parent_of: Dict[str, str] = {}

        # --- Indexed edge lookups (populated by add_relation) ---
        # edges by type["label_for"] = [(from_id, to_id), ...]
        self._edges_by_type: Dict[str, List[Tuple[str, str]]] = {}
        # edges from["n1"] = [("label_for", "n3"), ("parent_of", "n5"), ...]
        self._edges_from: Dict[str, List[Tuple[str, str]]] = {}
        # edges_to["n3"] = [("parent_of", "n1"), ("label_for", "n4"), ...]
        self._edges_to: Dict[str, List[Tuple[str, str]]] = {}

        # --- Semantic container index (populated by _build_semantic_edges) ---
        # container_id → set of descendant node ids in that container
        self._container_children: Dict[str, Set[str]] = {}
        # node_id → list of (container_type, container_id) it belongs to
        self._node_containers: Dict[str, List[Tuple[str, str]]] = {}
        # label_for_index: input_id → label_id (via <label for=> or aria-labelledby)
        self._label_for_index: Dict[str, str] = {}
        # Reverse: label_id → input_id
        self._labeled_by_index: Dict[str, str] = {}
        # table_id → {headers: [...], header_map: {col_id: header_nid, rows: [...]}
        self._table_structures: Dict[str, Dict[str, Any]] = {}
```

**Key data structures:**
- `nodes` — set of all node IDs
- `relations` — list of [from, relation_type, to] triples
- `node_metadata` — per-node metadata dict (tag, attrs, text, role, etc.)
- `node_to_frame` — node_id → frame_id mapping
- `frame_tree` — frame hierarchy
- `parent_of` — node_id → parent_id (fast lookup)
- Indexed edges: `_edges_by_type`, `_edges_from`, `_edges_to`
- Semantic indexes: `_container_children`, `_node_containers`, `_label_for_index`, `_labeled_by_index`, `_table_structures`

### Core Methods

```python
    def load_parsed_structure(self, parsed_json: Dict[str, Any]):
        if isinstance(parsed_json, dict) and "main" in parsed_json:
            self.parsed = parsed_json["main"]
        else:
            self.parsed = parsed_json

    def add_node(self, node_id: str, metadata: Dict[str, Any] = None):
        self.nodes.add(node_id)
        if metadata:
            self.node_metadata[node_id] = metadata

    def add_relation(self, from_id: str, relation: str, to_id: str):
        self.relations.append((from_id, relation, to_id))
        # Maintain indexed lookups
        self._edges_by_type.setdefault(relation, []).append((from_id, to_id))
        self._edges_from.setdefault(from_id, []).append((relation, to_id))
        self._edges_to.setdefault(to_id, []).append((relation, from_id))

    def get_edges_by_type(self, relation_type: str) -> List[Tuple[str, str]]:
        """Get all edges of a specific type. Returns list of (from_id, to_id)."""
        return self._edges_by_type.get(relation_type, [])

    def get_edges_from(self, node_id: str, relation_type: Optional[str] = None) -> List[Tuple[str, str]]:
        """Get all outgoing edges from a node. Returns list of (relation, to_id)."""
        edges = self._edges_from.get(node_id, [])
        if relation_type:
            return [(r, t) for r, t in edges if r == relation_type]
        return edges

    def get_edges_to(self, node_id: str, relation_type: Optional[str] = None) -> List[Tuple[str, str]]:
        """Get all incoming edges to a node. Returns list of (relation, from_id)."""
        edges = self._edges_to.get(node_id, [])
        if relation_type:
            return [(r, f) for r, f in edges if r == relation_type]
        return edges
```

---

## convert_to_graph() — DOM Tree → Graph (lines ~180–295)

### _frame_prefix helper

```python
    def _frame_prefix(frame_id: Optional[str]) -> str:
        return str(frame_id or "frame-0")
```

### _make_node_id — Collision-Free Node IDs

```python
    def _make_node_id(entry: Dict[str, Any], *, is_frame: bool, effective_frame_id: Optional[str]) -> Optional[str]:
        """Create a stable, collision-free node id.

        Rationale:
        - DOMSemanticParser assigns local id like n0/n1... per frame. Those restart from n0 in each frame.
        - If we use raw local id as the node id, nodes collide across frames and overwrite each other.
        - We therefore namespace node ids by their effective frame id.

        Rules:
        - Frame nodes keep their canonical frameId (e.g., frame-4) so frame references remain simple.
        - Non-frame DOM nodes use <frameId>::<local_id> when local_id exists.
        - Fallback to <frameId>::<xpath> when local id missing.
        - As a last resort, use <frameId>::node-<python_id>.
        """
        if is_frame and entry.get('frameId'):
            return entry.get('frameId')

        local_id = entry.get('local_id')
        xpath = entry.get('xpath')
        prefix = _frame_prefix(effective_frame_id)

        if local_id:
            return f"{prefix}::{local_id}"
        if xpath:
            return f"{prefix}::{xpath}"
        # Last resort: stable only within-process, but avoids dropping nodes
        return f"{prefix}::node-{id(entry)}"
```

### traverse() — Recursive DOM Walker

```python
    def traverse(entry, parent_id=None, parent_frame=None):
        # Prefer frameId if explicitly marked as frame
        is_frame = entry.get('isFrame', False)

        # The frame id that scopes DOM nodes under this entry.
        # If this entry is a frame node, it defines a new frame scope.
        # Otherwise, it inherits the parent frame scope.
        frame_id = entry.get('frameId') if is_frame else parent_frame

        cur_id = make_node_id(entry, is_frame=is_frame, effective_frame_id=frame_id)
        if not cur_id:
            return

        meta = {k: v for k, v in entry.items() if k != "children"}
        if is_frame:
            meta.setdefault("isFrame", True)

        self.add_node(cur_id, meta)
        self.node_to_frame[cur_id] = frame_id

        if is_frame:
            self.frame_tree.setdefault(cur_id, [])
            if parent_frame:
                self.frame_tree[parent_frame].append(cur_id)

        if parent_id:
            self.add_relation(parent_id, "parent_of", cur_id)
            self.add_relation(cur_id, "child_of", parent_id)
            self.parent_of[cur_id] = parent_id

        for c in entry.get("children", []):
            traverse(c, cur_id, frame_id)

    root = self.parsed
    if isinstance(root, list):
        for f in root:
            traverse(f)
    else:
        traverse(root)

    # Build all semantic edges after the structural tree is constructed
    self._build_semantic_edges()
```

**Key design:** Node IDs are namespaced by frame (`frame-0::n5`, `frame-4::n12`) to prevent
collisions across frames. Frame nodes keep their canonical `frameId`.

---

## _build_semantic_edges() — Post-Processing (lines ~300–340)

```python
    def _build_semantic_edges(self):
        """Post-process the graph to add semantic edges beyond parent/child.

        Called automatically after convert_to_graph(). Adds:
        1. Containment edges (contained_in_form, contained_in_dialog, etc.)
        2. Label-for associations (label_for, labeled_by, aria_labelledby)
        3. Table/grid structure (header_of, row_of, cell_of_row, cell_of_column)
        4. Grouping edges (grouped_by, legend_of)
        5. Tab associations (tab_for, tab_of)
        """
        logger.info("[KG] Building semantic edges for %d nodes...", len(self.nodes))

        self._build_containment_edges()
        self._build_label_edges()
        self._build_table_structure_edges()
        self._build_grouping_edges()
        self._build_tab_edges()

        # Log summary
        semantic_edge_count = sum(
            len(edges) for etype, edges in self._edges_by_type.items()
            if etype not in (EdgeTypes.PARENT_OF, EdgeTypes.CHILD_OF)
        )
        logger.info(
            "[KG] Semantic edges built: %d new edges | containers=%d | label_for=%d | tables=%d",
            semantic_edge_count,
            len(self._container_children),
            len(self._label_for_index),
            len(self._table_structures),
        )
```

---

## _build_containment_edges() — Container Detection via BFS (lines ~340–420)

```python
    def _build_containment_edges(self):
        """Detect semantic containers (form, dialog, table, grid, nav, section, etc.)
        and create containment edges for all their descendants.

        For each container node found, all descendants get a "contained in *" edge
        pointing to the container. This enables fast container-scoped queries like
        "find all inputs in this form" without tree traversal.
        """
        # First, identify all container nodes
        container_nodes: list[Tuple[str, str]] = []  # (node_id, edge_type)

        for nid in self.nodes:
            meta = self.node_metadata.get(nid, {})
            if not meta:
                continue

            tag = (meta.get("tag") or "").lower().strip()
            attrs = meta.get("attrs", {}) or {}
            role = (attrs.get("role") or meta.get("role") or "").lower().strip()

            # Check role first (more specific), then tag
            edge_type = None
            if role and role in EdgeTypes.ROLE_TO_CONTAINER_EDGE:
                edge_type = EdgeTypes.ROLE_TO_CONTAINER_EDGE[role]
            elif tag and tag in EdgeTypes.TAG_TO_CONTAINER_EDGE:
                edge_type = EdgeTypes.TAG_TO_CONTAINER_EDGE[tag]

            if edge_type:
                container_nodes.append((nid, edge_type))

        logger.debug("[KG] Found %d semantic containers", len(container_nodes))

        # For each container, BFS through children and add containment edges
        for container_id, edge_type in container_nodes:
            descendants: Set[str] = set()
            queue = [container_id]
            visited: Set[str] = set()

            while queue:
                cur = queue.pop(0)
                if cur in visited:
                    continue
                visited.add(cur)

                # Get children via parent_of edges
                children = [
                    to_id for rel_type, to_id
                    in self._edges_from.get(cur, [])
                    if rel_type == EdgeTypes.PARENT_OF
                ]
```

**Visible logic:** BFS from each container node, adding `CONTAINED_IN_*` edges to all descendants.
The rest of this method (adding edges to descendants) is cut off but follows the obvious pattern.

---

## _compute_stability_info() — Enhanced Context Builder v2 (lines ~500–2241)

This is the **largest function** in the file. It computes per-node stability information
that tells the LLM which attributes are safe for building locators.

### Text Extraction with Fallback

```python
    def _compute_stability_info(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute stability information for a node to help LLM decide locator strategy.
        This is INFORMATIONAL ONLY - does not affect target selection.

        Returns a dict describing what stable attributes are available for building locators.
        """
        import re
        attrs = meta.get("attrs", {}) or {}
        role = meta.get("role") or attrs.get("role")

        # Text extraction with fallback to text_content_raw
        text = (meta.get("text") or "").strip()
        if not text:
            # Fall back to text_content_raw if it's short and meaningful
            raw_text = (meta.get("text_content_raw") or "").strip()
            # Only use raw text if it's short enough to be useful for locators
            # and doesn't look like concatenated page content
            if raw_text and len(raw_text) <= 80 and '\n' not in raw_text:
                text = raw_text
```

### _looks_random() — Dynamic Value Detector

```python
        def _looks_random(val: str) -> bool:
            if not val or not isinstance(val, str):
                return True
            s = val.strip()
            if not s or len(s) > 80:  # Too long → likely not a good locator
                return True
            low = s.lower()
            # Data URIs / base64
            if low.startswith("data:") or ("base64" in low and len(low) > 40):
                return True
            # Pure digits
            if s.isdigit():
                return True
            # Hex hashes (8+ hex chars)
            if re.match(r'^[a-f0-9]{8,}$', low):
                return True
            # UUID-like patterns
            if re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', low):
                return True
            # High hex ratio in long strings
            if len(low) >= 16:
                hex_chars = sum(1 for c in "0123456789abcdef" for c in low)
                if hex_chars / len(low) > 0.8:
                    return True
            return False
```

### Stable data-* Attribute Collection

```python
        # Collect ALL stable data-* and similar attributes dynamically
        stable_data_attrs = {}
        # Grid-specific bare attributes that don't follow the data-* prefix convention
        # but are stable identifiers in ag-Grid, SlickGrid, and similar grid libraries.
        _GRID_BARE_ATTRS = frozenset({
            "col-id", "row-id", "row-index",
            "aria-colindex", "aria-rowindex", "aria-colcount", "aria-rowcount",
        })
        for attr_name, attr_val in attrs.items():
            if not isinstance(attr_name, str):
                continue
            lname = attr_name.lower().strip()
            # Accept data-*, ag-* (ag-Grid), and similar automation-friendly prefixes
            if lname.startswith(("data-", "ag-", "test-", "qa-", "auto-")):
                if isinstance(attr_val, str) and not _looks_random(attr_val):
                    stable_data_attrs[attr_name] = attr_val.strip()
            # Also accept known grid bare attributes (col-id, row-id, etc.)
            elif lname in _GRID_BARE_ATTRS:
                if isinstance(attr_val, str) and not _looks_random(attr_val):
                    stable_data_attrs[attr_name] = attr_val.strip()
```

### text_source Detection (Critical for text() vs "." Decision)

```python
        # Track whether the resolved text is the element's own direct text or descendant text.
        # This is critical for choosing text() vs. in XPath:
        #   "own"        → element has its own non-empty text nodes → text() and . both work
        #   "descendant" → text came from text_content_raw (child spans) → ONLY . works, text() is empty
        #   "none"       → no usable text at all
        _own_text = (meta.get("text") or "").strip()
        if _own_text:
            text_source = "own"
        elif text:  # text was resolved from text_content_raw fallback above
            text_source = "descendant"
        else:
            text_source = "none"
```

### The stability Dict (Complete)

```python
        stability = {
            # Available stable attributes (LLM should prefer these for locators)
            "stable_data_attrs": stable_data_attrs if stable_data_attrs else None,  # All stable data-* attrs found
            "aria_label": attrs.get("aria-label") or None,
            "aria_labelledby": attrs.get("aria-labelledby") or None,
            "aria_controls": attrs.get("aria-controls") or None,
            "role": role or None,
            "id": None,  # Will be set below if non-dynamic
            "name": attrs.get("name") or None,
            "placeholder": attrs.get("placeholder") or None,
            "title": attrs.get("title") or None,  # HTML title attribute - stable for menus, links, etc.
            "for_attr": attrs.get("for") or None,  # label[for] → input[id] association
            "has_text": bool(text),
            "text_length": len(text) if text else 0,
            # Where the resolved text came from — critical for text() vs . decision:
            # "own" → element's direct text nodes (text() works), "descendant" → child spans (MUST use . not text())
            "text_source": text_source,
            # State indicators (useful for tabs, trees, accordions, checkboxes)
            "aria_expanded": attrs.get("aria-expanded"),    # "true"/"false" on collapsibles
            "aria_selected": attrs.get("aria-selected"),    # "true"/"false" on tabs/options
            "aria_checked": attrs.get("aria-checked"),      # "true"/"false" on checkboxes
        }
```

### Dynamic ID Detection & Rejection

```python
        # Check ID — reject if looks random/dynamic
        node_id = attrs.get("id")
        if node_id and isinstance(node_id, str):
            # Patterns that indicate auto-generated IDs
            dynamic_patterns = [
                r"[a-f0-9]{16,}",           # hex hash
                r"[a-z]+-[a-f0-9]{6,}$",    # prefix-hash
                r"^\d+$",                    # pure numbers
                r"^[a-z0-9]+$",             # React internal IDs
                r"^:r\d+:$",               # React internal IDs (colon format)
                r"ember\d+$",              # Ember
                r"text-gen\d+$",           # ExtJS
                r"[a-z]+-\d{4,}$",         # prefix + many digits
                r"jpmui-\d+.*",            # JPMU framework auto IDs (jpmui-12610-input, etc.)
                r"^jpmui-.*",              # JPMU numeric variant
                r"label-salt-\d+$",        # Salt Design System sequential label IDs
                r"HelperText-salt-\d+$",   # Salt Design System sequential helper IDs
                r"salt-\d+$",              # Salt Design System sequential name/group IDs
            ]
            is_dynamic = any(re.match(p, node_id, re.IGNORECASE) for p in dynamic_patterns)
            if not is_dynamic:
                stability["id"] = node_id
            else:
                stability["id_rejected_dynamic"] = node_id
```

**Key:** IDs matching JPMC-specific patterns (`jpmui-*`, `salt-*`, `HelperText-salt-*`) are
rejected as dynamic. This is tuned for the Salt Design System used at JPMC.

### _class_looks_random() — Class Name Validator

```python
        def _class_looks_random(c: str) -> bool:
            if not c or len(c) < 2:
                return True
            low = c.lower()
            # Pure numbers or very short
            if c.isdigit():
                return True
            # Long hex suffix (6+ hex chars at end)
            if re.search(r'[a-f0-9]{6,}$', low):
                return True
            # CSS-in-JS patterns: jss123, sc-abcdef, css-xyz123, emotion-abc
            if re.match(r'^(jss|sc-|css-|emotion-|styled-)[a-z0-9]+', low):
                return True
            # BEM with hash: block__element_hash12345
            if re.search(r'_[a-z]+_[a-z0-9]{5,}$', low):
                return True
            # MUI generated: MuiButton-root-123
            if re.match(r'^Mui[A-Z].*\d+$', c):
                return True
            # High ratio of digits in short class
            if len(c) >= 12:
                digit_ratio = sum(ch.isdigit() for ch in c) / len(c)
                if digit_ratio > 0.4:
                    return True
            return False

        # Collect stable classes (any class that doesn't look random)
        cls = attrs.get("class", "")
        if isinstance(cls, list):
            cls = " ".join(c for c in cls if isinstance(c, str))
        if cls:
            classes = cls.split()
            stable = []
            for c in classes:
                if not _class_looks_random(c):
                    stable.append(c)
            if stable:
                stability["stable_classes"] = stable[:5]  # Keep more classes, LLM can decide

        # Summary of what's available for locator building
        available = {}
```

**The `available` dict building continues** but is cut off at the end of the screenshots.

---

## ADDITIONAL KnowledgeGraph METHODS (from batch 2 screenshots)

### compare_with() — Graph Diffing (lines ~738–755)

```python
    def compare_with(self, other_kg: 'KnowledgeGraph') -> Dict[str, Any]:
        diff = {
            "frame_tree_changed": False
        }

        # 1. Compare nodes added / removed
        current_nodes = set(self.nodes)
        old_nodes = set(other_kg.nodes)
        diff["added_nodes"] = list(current_nodes - old_nodes)
        diff["removed_nodes"] = list(old_nodes - current_nodes)

        # 2. Detect metadata changes for shared nodes
        for nid in current_nodes & old_nodes:
            old_meta = other_kg.node_metadata.get(nid, {})
            new_meta = self.node_metadata.get(nid, {})
            if old_meta != new_meta:
                diff["changed_nodes"].append({
                    "node_id": nid,
                    "old": old_meta,
                    "new": new_meta,
                })

        # 3. Frame tree change detection
        if self.frame_tree != other_kg.frame_tree:
            diff["frame_tree_changed"] = True

        return diff
```

### validate_graph() — Integrity Checks (lines ~826–660)

```python
    def validate_graph(self) -> Dict[str, Any]:
        """
        Validate integrity of Knowledge Graph.
        Returns summary statistics & suspicious cases.
        """
        issues = {
            "nodes_missing_metadata": [],
            "orphan_nodes": [],
            "frames_without_children": [],
            "total_nodes": len(self.nodes),
            "total_relations": len(self.relations)
        }

        # 1) Check nodes missing metadata
        for nid in self.nodes:
            if nid not in self.node_metadata or not self.node_metadata[nid]:
                issues["nodes_missing_metadata"].append(nid)

        # 2) Detect orphan nodes (no parent_of relation)
        child_nodes = {rel[2] for rel in self.relations if rel[1] == "parent_of"}
        for nid in self.nodes:
            if nid not in child_nodes:  # may be root OR missing relation
                # exclude root: if ONLY one node exists
                if len(self.nodes) > 1:
                    issues["orphan_nodes"].append(nid)

        # 3) Find frames missing children
        for nid, meta in self.node_metadata.items():
            if meta.get("tag") == "iframe":
                has_child = any(rel[0] == nid and rel[1] == "parent_of" for rel in self.relations)
                if not has_child:
                    issues["frames_without_children"].append(nid)

        return issues
```

### export_json() — Full Graph Serialization (lines ~668–883)

```python
    def export_json(self, path: str):
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "nodes": list(self.nodes),
                "relations": self.relations,
                "metadata": self.node_metadata,
                "node_to_frame": self.node_to_frame,
                "frame_tree": self.frame_tree,
                "semantic_summary": self.get_semantic_summary(),
                "container_children": {k: list(v) for k, v in self._container_children.items()},
                "label_for_index": self._label_for_index,
                "table_structures": {
                    tid: {
                        "headers": ts.get("headers", {}),
                        "header_texts": ts.get("header_texts", {}),
                        "rows": ts.get("rows", []),
                        "cells": ts.get("cells", {}),
                    }
                    for tid, ts in self._table_structures.items()
                },
            }, f, indent=2)
```

---

## CLASS: GraphTraversal (lines ~887+) — NOW CAPTURED

This is the **critical class** that builds prompt context for LLM Call #4.

### __init__

```python
class GraphTraversal:

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg
```

### _slim_meta() — Metadata Trimming for LLM Context (lines ~891–958)

```python
    def _slim_meta(self, meta: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize and reduce metadata tokens for LLM context:
        - Omit high-chars or redundant fields: text_nodes, parent_xpath, rect, path, local_id, hierarchy, FrameChain
        - Keep essential fields only: tag, text, innerText, role, attrs, xpath, style, FormAttrs, visible, state, isShadow
        - Truncate long text fields
        """
        if not isinstance(meta, dict):
            return {}
        out: Dict[str, Any] = {}

        # Core text fields (truncate to reduce tokens)
        text = str(meta.get("text", '') or '')
        inner = str(meta.get("innerText", '') or '')
        def _truncate(s: str, n: int = 100) -> str:
            return s[:n] if len(s) > n else s
        out["tag"] = meta.get("tag", "")

        # Preserve text semantics hint (own-text-only vs unknown) so the LLM can choose text() vs . safely.
        if "text_is_own" in meta:
            out["text_is_own"] = bool(meta.get("text_is_own"))

        # Pre-normalized text helpers (computed at parse time).
        ton = meta.get("text_own_norm")
        # NOTE: text_desc_norm is intentionally excluded from LLM-facing context.
        if isinstance(ton, str) and ton:
            out["text_own_norm"] = _truncate(ton, 160)

        # Raw descendant text (not normalized) to expose NBSP and unusual whitespace.
        # Keep it short to avoid token blowups.
        tcr = meta.get("text_content_raw")
        if isinstance(tcr, str) and tcr:
            out["text_content_raw"] = tcr[:240]

        # Flattened variants (prefer these in prompts; easier for LLMs than nested dict access)
        for k in ("text_nodes_total", "text_nodes_non_ws", "text_nodes_first_ws_only"):
            if k in meta:
                out[k] = meta.get(k)

        # Style/script pollution flag — signals that XPath normalize-space(.) will include
        # text from <style>/<script> descendants, making exact text matching unreliable.
        if meta.get("has_style_script_pollution"):
            out["has_style_script_pollution"] = True

        # Frame URL (critical for frame switching in Playwright)
        frame_url = meta.get("frameUrl") or meta.get("frame_url")
        if frame_url:
            out["frameUrl"] = frame_url
        if text:
            out["text"] = _truncate(text)
        if inner and inner != text:
            out["innerText"] = _truncate(inner)

        # Role
        role = meta.get("role") or (meta.get("attrs", {}) or {}).get("role")
        if role:
            out["role"] = role

        # Attrs whitelist
        attrs = meta.get("attrs", {}) or {}
        # If src contains an embedded data URI (often base64 images), drop it from LLM context.
        # Those are huge, unstable, and not helpful for robust locators.
        try:
            src = attrs.get("src")
            if isinstance(src, str):
                s = src.strip().lower()
                if s.startswith("data:"):
                    # data:image/...,base64,... or other embedded payloads
                    attrs = dict(attrs)
                    attrs.pop("src", None)
        except Exception:
            attrs = dict(attrs)
            attrs.pop("src", None)
        except Exception:
            pass
        out["attrs"] = attrs

        # xpath intentionally excluded from LLM-facing context

        # Add style if present
        if "style" in meta:
            out["style"] = meta.get("style")
        # Add FormAttrs if present
        if "FormAttrs" in meta:
            fa = meta.get("FormAttrs")
            # Also strip embedded data-URI/base64 src from FormAttrs if present.
            try:
                if isinstance(fa, dict) and isinstance(fa.get("src"), str):
                    s = fa.get("src", "").strip().lower()
                    if s.startswith("data:"):
                        fa = dict(fa)
                        fa.pop("src", None)
            except Exception:
                pass
            out["FormAttrs"] = fa
        # Add visible if present
        if "visible" in meta:
            out["visible"] = meta.get("visible")
        # Add state if present
        if "state" in meta:
            out["state"] = meta.get("state")
        # Add isShadow if present
        if "isShadow" in meta:
            out["isShadow"] = meta.get("isShadow")

        # Explicitly remove unwanted fields if present
        for unwanted in [
            "text_nodes", "parent_xpath", "rect", "path", "local_id", "hierarchy", "FrameChain"
        ]:
            if unwanted in out:
                out.pop(unwanted, None)

        return out
```

**Key decisions:**
- `xpath` **intentionally excluded** from LLM context (forces LLM to build its own)
- `text_desc_norm` **intentionally excluded** from LLM context
- `text_content_raw` truncated to 240 chars
- Data URIs stripped from `src` and `FormAttrs.src`
- `has_style_script_pollution` flag preserved for pollution-aware XPath generation

### _ancestor_depth_map() — Tree Proximity Helper (lines ~1000–1013)

```python
    def _ancestor_depth_map(self, node_id: str) -> Dict[str, int]:
        """Return a map of ancestor_id → levels up (1 = parent) for node_id.
        Protect against cycles; stop at root.
        """
        depth_map: Dict[str, int] = {}
        depth = 0
        cur = self.kg.parent_of.get(node_id)
        visited = set()
        while cur and cur not in visited and depth < 50:
            visited.add(cur)
            depth += 1
            depth_map[cur] = depth
            cur = self.kg.parent_of.get(cur)
        return depth_map
```

### _resolve_anchor_nodes() — Anchor Resolution (lines ~1015–1135)

```python
    def _resolve_anchor_nodes(
        self,
        target_id: str,
        parsed_intent: Optional[Dict[str, Any]],
        already_seen: set,
    ) -> List[Dict[str, Any]]:
        """Search the KG for nodes whose text matches the parsed-intent anchor.

        The anchor (e.g. "Subscribe Access", "Request Access") is a section
        heading that scopes which identical elements the user means. Spatial
        sibling detection may miss it when the heading is far from the target.

        Strategy (enhanced with semantic edges):
        1. First check if the target is inside a semantic container whose
           label/text matches the anchor text — instant match via edges.
        2. Fall back to text-based search across all nodes.
        3. Pick the closest match in the DOM tree to the target.

        Returns a list of sibling-like dicts (usually 0-2 entries).
        """
        if not parsed_intent:
            return []
        anchor = parsed_intent.get("anchor") or {}
        anchor_text = (anchor.get("text") or "").strip()
        if not anchor_text:
            return []

        anchor_lower = anchor_text.lower()
        target_meta = self.kg.node_metadata.get(target_id, {})

        # Build ancestor set for the target (for tree-distance ranking)
        t_ancestors = self._ancestor_depth_map(target_id)

        candidates: List[tuple] = []  # (tree_distance, node_id, meta)

        # --- Strategy 1: Use semantic container edges ---
        # Check if target is inside a container whose label matches anchor text
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
                    # Container matches anchor — very strong signal, distance = 0
                    candidates.append((0, container_id, c_meta))
                    break

        # --- Strategy 2: Text-based search (original) ---
        for nid, meta in self.kg.node_metadata.items():
            if nid == target_id or nid in already_seen:
                continue
            # Skip if already found via container edges
            if any(c[1] == nid for c in candidates):
                continue

            text = (meta.get("text") or "").strip()
            own_norm = (meta.get("text_own_norm") or "").strip()
            attrs = meta.get("attrs", {}) or {}
            aria = (attrs.get("aria-label") or "").strip()

            matched = False
            for candidate_text in (text, own_norm, aria):
                if candidate_text and anchor_lower in candidate_text.lower():
                    tag = (meta.get("tag") or "").lower()
                    text_len = len(candidate_text)
                    if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "label", "legend", "span", "p", "strong", "b", "em"):
                        matched = True
                    elif text_len < 120:
                        matched = True
                    break

            if not matched:
                continue

            # Compute tree distance to target
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
            logger.debug("[KG] No anchor nodes found for text=%r", anchor_text)
            return []

        # Sort by tree distance (closest first), take top 2
        candidates.sort(key=lambda x: x[0])
        logger.info(
            "[KG] Anchor resolution for %r: found %d candidates, closest dist=%d (node=%s)",
            anchor_text, len(candidates), candidates[0][0], candidates[0][1],
        )

        results = []
        for dist, anc_id, anc_meta in candidates[:2]:
            sib_stability = self._compute_stability_info(anc_meta)
            sib_entry = {
                "node_id": anc_id,
                "metadata": self._slim_meta(anc_meta),
                "stability": sib_stability,
                "spatial_relation": self.spatial_relation(target_meta, anc_meta),
                "tree_relation": self._compute_tree_relation(target_id, anc_id),
                "usable_as_anchor": True,
                "anchor_match": True,  # Flag so LLM knows this is the section heading
            }
            if sib_stability.get("has_stable_attrs") or sib_stability.get("has_text"):
                sib_entry["locator_suggestions"] = self._compute_locator_suggestions(anc_meta, sib_stability)
            results.append(sib_entry)
            already_seen.add(anc_id)

        return results
```

**Key design:**
- **Strategy 1** (semantic edges): Check if target is inside a container whose label/text matches anchor → distance 0
- **Strategy 2** (text search): Fall back to global text search, prefer heading tags (h1-h6, label, legend)
- Sorted by **tree distance** (closest first), return top 2
- Each result includes: slimmed metadata, stability info, spatial_relation, tree_relation, locator_suggestions

### _resolve_label_nodes() — Label Resolution (lines ~1138–1256)

```python
    def _resolve_label_nodes(
        self,
        target_id: str,
        parsed_intent: Optional[Dict[str, Any]],
        already_seen: set,
    ) -> List[Dict[str, Any]]:
        """Search the KG for nodes whose text matches the parsed-intent label.

        Enhanced with semantic edges:
        1. First check for direct label_for / labeled_by edges in the KG.
        2. Fall back to text-based search across all nodes.
        3. Pick the closest match in the DOM tree to the target.

        Returns a list of sibling-like dicts (usually 0-2 entries).
        """
        if not parsed_intent:
            return []
        label_info = parsed_intent.get("label") or {}
        label_text = (label_info.get("text") or "").strip()
        if not label_text:
            return []

        label_lower = label_text.lower()
        target_meta = self.kg.node_metadata.get(target_id, {})

        # Build ancestor set for the target (for tree-distance ranking)
        t_ancestors = self._ancestor_depth_map(target_id)

        candidates: List[tuple] = []  # (tree_distance, node_id, meta)

        # --- Strategy 1: Use label-for edges ---
        # Check if there's a direct label-input association
        label_nid_from_edge = self.kg._find_label_for(target_id)
        if label_nid_from_edge and label_nid_from_edge not in already_seen:
            lab_meta = self.kg.node_metadata.get(label_nid_from_edge, {})
            lab_text = (lab_meta.get("text") or lab_meta.get("text_own_norm") or "").strip()
            if lab_text and label_lower in lab_text.lower():
                # Direct label-for match — highest confidence, distance = 0
                candidates.append((0, label_nid_from_edge, lab_meta))

        # Also check reverse: if the target is a label, find what it labels
        # This helps when the user searches from the label's perspective
        input_nid_from_edge = self.kg._find_labeled_input(target_id)
        if input_nid_from_edge and input_nid_from_edge not in already_seen:
            inp_meta = self.kg.node_metadata.get(input_nid_from_edge, {})
            candidates.append((0, input_nid_from_edge, inp_meta))

        # --- Strategy 2: Text-based search (original) ---
        for nid, meta in self.kg.node_metadata.items():
            if nid == target_id or nid in already_seen:
                continue
            # Skip if already found via edge
            if any(c[1] == nid for c in candidates):
                continue

            text = (meta.get("text") or "").strip()
            own_norm = (meta.get("text_own_norm") or "").strip()
            attrs = meta.get("attrs", {}) or {}
            aria = (attrs.get("aria-label") or "").strip()

            matched = False
            for candidate_text in (text, own_norm, aria):
                if candidate_text and label_lower in candidate_text.lower():
                    tag = (meta.get("tag") or "").lower()
                    text_len = len(candidate_text)
                    if tag in {
                        "label", "legend", "span", "p", "strong", "b", "em",
                        "h1", "h2", "h3", "h4", "h5", "h6",
                    }:
                        matched = True
                    elif text_len < 200:
                        matched = True
                    break

            if not matched:
                continue

            # Compute tree distance to target
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
            logger.debug("[KG] No label nodes found for text=%r", label_text)
            return []

        # Sort by tree distance (closest first), take top 2
        candidates.sort(key=lambda x: x[0])
        logger.info(
            "[KG] Label resolution for %r: found %d candidates, closest dist=%d (node=%s)",
            label_text, len(candidates), candidates[0][0], candidates[0][1],
        )

        results = []
        for dist, lab_id, lab_meta in candidates[:2]:
            sib_stability = self._compute_stability_info(lab_meta)
            sib_entry = {
                "node_id": lab_id,
                "metadata": self._slim_meta(lab_meta),
                "stability": sib_stability,
                "spatial_relation": self.spatial_relation(target_meta, lab_meta),
                "tree_relation": self._compute_tree_relation(target_id, lab_id),
                "usable_as_anchor": True,
                "label_match": True,  # Flag so LLM knows this is the label node
            }
            if sib_stability.get("has_stable_attrs") or sib_stability.get("has_text"):
                sib_entry["locator_suggestions"] = self._compute_locator_suggestions(lab_meta, sib_stability)
            results.append(sib_entry)
            already_seen.add(lab_id)

        return results
```

### Scoping Container Detection (line ~1259+, partially visible)

```python
    # Scoping container detection (dialog, tabpanel, menu, nav, form)
    _SCOPING_ROLES = frozenset({
        "dialog", "alertdialog",      # modals
        "tabpanel",                    # tab content areas
        "menu", "menubar",            # menus
```

**Cut off** — but the pattern is clear: identifies which ARIA roles serve as scoping containers for XPath generation.

---

## MISSING SECTIONS (updated after batch 2)

### Still not captured (low risk — inferrable from EdgeTypes):
1. `_build_label_edges()` — creates LABEL_FOR/LABELED_BY edges
2. `_build_table_structure_edges()` — creates table/grid structure edges
3. `_build_grouping_edges()` — creates GROUPED_BY/LEGEND_OF edges
4. `_build_tab_edges()` — creates TAB_FOR/TAB_OF edges
5. `embed_changed_nodes()` — embedding for changed nodes (visible signature only)

### Still not captured (medium risk — pattern visible but details missing):
6. `spatial_relation()` — computes spatial relationship between two nodes (called in results but method body not shown)
7. `_compute_tree_relation()` — computes tree relationship (common ancestor, levels up, etc.)
8. `_compute_locator_suggestions()` — generates locator suggestions from stability info
9. The main `traverse_for_context()` or equivalent method that builds the full prompt context with subtrees/node_chains
10. End of `_compute_stability_info()` — the `available` summary dict

### Visible but partially cut off:
11. Scoping container roles list (only first 4 visible)

---

## WHAT'S INFERRABLE vs. WHAT NEEDS GUESSING (updated)

| Component | Status | Risk Level |
|-----------|--------|------------|
| EdgeTypes constants | COMPLETE | None |
| KnowledgeGraph.__init__ | COMPLETE | None |
| Core methods (add_node, add_relation, get_edges_*) | COMPLETE | None |
| convert_to_graph + _make_node_id + traverse | COMPLETE | None |
| _build_semantic_edges dispatch | COMPLETE | None |
| _build_containment_edges | 90% | Low |
| _build_label/table/grouping/tab_edges | MISSING but inferrable | Low |
| _compute_stability_info | 90% | Low |
| compare_with, validate_graph, export_json | COMPLETE | None |
| **GraphTraversal.__init__ + _slim_meta** | **COMPLETE** | **None** |
| **_ancestor_depth_map** | **COMPLETE** | **None** |
| **_resolve_anchor_nodes** | **COMPLETE** | **None** |
| **_resolve_label_nodes** | **COMPLETE** | **None** |
| spatial_relation, _compute_tree_relation | Called but body not shown | Medium |
| _compute_locator_suggestions | Called but body not shown | Medium |
| Main context builder (subtrees/node_chains) | NOT CAPTURED | Medium-High |

---

## STATUS: ~90% CAPTURED (12 unique screenshots across 2 batches)
GraphTraversal anchor and label resolution are now solid.
Remaining gaps: the main context-building method, spatial_relation, tree_relation, and locator_suggestions.
These follow clear patterns from the captured code and can be reconstructed with reasonable confidence.
