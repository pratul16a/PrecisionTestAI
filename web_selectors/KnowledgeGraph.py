"""
KnowledgeGraph.py — Knowledge Graph

Converts parsed DOM tree into a NetworkX graph with:
- Parent-child edges
- Sibling edges with spatial metadata
- Node attributes for search and context building
"""
import networkx as nx
from typing import Optional

class KGNode:
    """Attribute-access wrapper around a node's attribute dict."""
    __slots__ = ("id", "element_id", "tag", "text", "direct_text", "role", "aria_label",
                 "placeholder", "data_testid", "name", "type", "xpath",
                 "visible", "rect", "depth", "class_name", "frame_url", "frame_name",
                 "sibling_ids", "child_ids", "parent_id")

    def __init__(self, node_id: str, attrs: dict):
        self.id = node_id
        self.element_id = attrs.get("id", "") or ""
        self.tag = attrs.get("tag", "") or ""
        self.text = attrs.get("text", "") or ""
        self.direct_text = attrs.get("directText", "") or ""
        self.role = attrs.get("role", "") or ""
        self.aria_label = attrs.get("ariaLabel", "") or ""
        self.placeholder = attrs.get("placeholder", "") or ""
        self.data_testid = attrs.get("dataTestId", "") or ""
        self.name = attrs.get("name", "") or ""
        self.type = attrs.get("type", "") or ""
        self.xpath = attrs.get("xpath", "") or ""
        self.visible = bool(attrs.get("visible", False))
        self.rect = attrs.get("rect", {}) or {}
        self.depth = attrs.get("depth", 0)
        self.class_name = attrs.get("class", "") or ""
        self.frame_url = attrs.get("frame_url", "") or ""
        self.frame_name = attrs.get("frame_name", "") or ""
        self.sibling_ids = []
        self.child_ids = []
        self.parent_id = None


class KnowledgeGraph:
    """DOM tree → searchable graph with spatial relationships."""

    def __init__(self):
        self.graph = nx.DiGraph()
        self.node_index = {}  # xpath → node_id
        self._counter = 0

    def load_parsed_structure(self, tree: dict):
        """Load a parsed DOM tree and convert to graph."""
        self.graph = nx.DiGraph()
        self.node_index = {}
        self._counter = 0
        self.convert_to_graph(tree)

    def convert_to_graph(self, node: dict, parent_id: Optional[str] = None):
        """
        Recursively convert DOM tree to graph.
        Creates parent-child + sibling edges with spatial metadata.
        """
        if not node or "tag" not in node:
            return None

        node_id = f"n_{self._counter}"
        self._counter += 1

        # Store node attributes
        attrs = {
            "tag": node.get("tag", ""),
            "text": node.get("text", ""),
            "directText": node.get("directText", ""),
            "id": node.get("id", ""),
            "class": node.get("class", ""),
            "role": node.get("role", ""),
            "ariaLabel": node.get("ariaLabel", ""),
            "placeholder": node.get("placeholder", ""),
            "dataTestId": node.get("dataTestId", ""),
            "name": node.get("name", ""),
            "type": node.get("type", ""),
            "xpath": node.get("xpath", ""),
            "visible": node.get("visible", False),
            "rect": node.get("rect", {}),
            "depth": node.get("depth", 0),
        }

        self.graph.add_node(node_id, **attrs)
        xpath = node.get("xpath", "")
        if xpath:
            self.node_index[xpath] = node_id

        # Parent-child edge
        if parent_id:
            self.graph.add_edge(parent_id, node_id, relation="parent-child")

        # Process children and add sibling edges
        child_ids = []
        for child in node.get("children", []):
            child_id = self.convert_to_graph(child, parent_id=node_id)
            if child_id:
                child_ids.append(child_id)

        # Sibling edges with spatial metadata
        for i in range(len(child_ids) - 1):
            self.graph.add_edge(child_ids[i], child_ids[i + 1], relation="sibling-next")
            self.graph.add_edge(child_ids[i + 1], child_ids[i], relation="sibling-prev")

        # Handle iframes
        for iframe_data in node.get("_iframes", []):
            iframe_tree = iframe_data.get("tree", {})
            if iframe_tree:
                self.convert_to_graph(iframe_tree, parent_id=node_id)

        return node_id

    def get_node(self, node_id: str):
        """Get node by ID as a KGNode (attribute access)."""
        if node_id in self.graph:
            return self._wrap(node_id, dict(self.graph.nodes[node_id]))
        return None

    def get_siblings(self, node_id: str) -> list[dict]:
        """Get sibling nodes."""
        siblings = []
        for src, dst, data in self.graph.edges(node_id, data=True):
            if "sibling" in data.get("relation", ""):
                siblings.append(self.get_node(dst))
        for src, dst, data in self.graph.in_edges(node_id, data=True):
            if "sibling" in data.get("relation", ""):
                siblings.append(self.get_node(src))
        return siblings

    def get_children(self, node_id: str) -> list[dict]:
        """Get direct children of a node."""
        children = []
        for src, dst, data in self.graph.edges(node_id, data=True):
            if data.get("relation") == "parent-child":
                children.append({"id": dst, **self.get_node(dst)})
        return children

    def all_nodes(self) -> list[tuple[str, dict]]:
        """Get all nodes with their attributes."""
        return [(nid, dict(attrs)) for nid, attrs in self.graph.nodes(data=True)]

    def _wrap(self, nid: str, attrs: dict) -> "KGNode":
        n = KGNode(nid, attrs)
        # parent
        for src, _, data in self.graph.in_edges(nid, data=True):
            if data.get("relation") == "parent-child":
                n.parent_id = src
                break
        # children
        n.child_ids = [
            dst for _, dst, data in self.graph.edges(nid, data=True)
            if data.get("relation") == "parent-child"
        ]
        # siblings (forward + reverse)
        sibs = []
        for _, dst, data in self.graph.edges(nid, data=True):
            if "sibling" in data.get("relation", ""):
                sibs.append(dst)
        for src, _, data in self.graph.in_edges(nid, data=True):
            if "sibling" in data.get("relation", ""):
                sibs.append(src)
        n.sibling_ids = sibs
        return n

    def get_all_nodes(self) -> list:
        """Get all nodes wrapped as KGNode objects (attribute access)."""
        return [self._wrap(nid, dict(attrs)) for nid, attrs in self.graph.nodes(data=True)]

    def get_ancestors(self, node_id: str, max_depth: int = 10) -> list:  # type: ignore[override]
        """Get ancestor chain for a node as KGNode objects."""
        ancestors = []
        current = node_id
        for _ in range(max_depth):
            parents = [
                src for src, dst, data in self.graph.in_edges(current, data=True)
                if data.get("relation") == "parent-child"
            ]
            if not parents:
                break
            current = parents[0]
            ancestors.append(self._wrap(current, dict(self.graph.nodes[current])))
        return ancestors
