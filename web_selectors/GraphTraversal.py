"""
GraphTraversal.py - Context Building (no LLM)
For each candidate: ancestor chain, sibling relations, spatial layout,
stability metadata, locator suggestions, scoping containers, frame details.
Token-trimmed to 50K tokens.
"""
import json
import logging
from .KnowledgeGraph import KnowledgeGraph, KGNode

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 200000  # ~50K tokens


class GraphTraversal:
    """Build rich subtree context for LLM locator generation."""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    def build_subtree_context_locatable_v2(self, candidates: list[tuple[KGNode, float]]) -> str:
        """
        For each candidate, build rich context including:
        - Ancestor chain
        - Sibling relations
        - Spatial layout (bounding rect)
        - Stability metadata (data-testid, role, aria-label)
        - Locator suggestions
        - Scoping containers
        - Frame details
        Token-trimmed to ~50K tokens.
        """
        context_parts = []
        total_chars = 0

        for node, score in candidates:
            if total_chars >= MAX_CONTEXT_CHARS:
                break

            part = self._build_node_context(node, score)
            part_json = json.dumps(part, indent=2)

            if total_chars + len(part_json) > MAX_CONTEXT_CHARS:
                break

            context_parts.append(part)
            total_chars += len(part_json)

        return json.dumps(context_parts, indent=2)

    def _build_node_context(self, node: KGNode, score: float) -> dict:
        """Build rich context for a single candidate node."""
        # Ancestor chain
        ancestors = self.kg.get_ancestors(node.id)
        ancestor_chain = [
            {
                "tag": a.tag,
                "role": a.role,
                "id": a.element_id,
                "class": a.class_name[:100],
                "aria_label": a.aria_label,
                "data_testid": a.data_testid,
            }
            for a in ancestors[:5]  # limit depth
        ]

        # Sibling info
        siblings = []
        for sid in node.sibling_ids[:5]:
            sib = self.kg.get_node(sid)
            if sib:
                siblings.append({
                    "tag": sib.tag,
                    "text": sib.direct_text[:50],
                    "role": sib.role,
                })

        # Locator suggestions
        suggestions = self._suggest_locators(node)

        # Scoping container
        scope = self._find_scoping_container(node)

        return {
            "candidate": {
                "tag": node.tag,
                "text": node.direct_text[:200],
                "full_text": node.text[:200],
                "role": node.role,
                "aria_label": node.aria_label,
                "data_testid": node.data_testid,
                "placeholder": node.placeholder,
                "id": node.element_id,
                "class": node.class_name[:200],
                "xpath": node.xpath,
                "visible": node.visible,
                "rect": node.rect,
            },
            "score": round(score, 3),
            "ancestor_chain": ancestor_chain,
            "siblings": siblings,
            "locator_suggestions": suggestions,
            "scoping_container": scope,
            "frame_url": node.frame_url,
            "frame_name": node.frame_name,
        }

    def _suggest_locators(self, node: KGNode) -> list[str]:
        """Generate locator suggestions in priority order."""
        suggestions = []

        # Priority: data-testid > aria-* > role > id > text() > position
        if node.data_testid:
            suggestions.append(f"//*[@data-testid='{node.data_testid}']")
        if node.aria_label:
            suggestions.append(f"//*[@aria-label='{node.aria_label}']")
        if node.role and node.direct_text:
            suggestions.append(f"//*[@role='{node.role}' and contains(.,'{node.direct_text[:50]}')]")
        if node.element_id:
            suggestions.append(f"//*[@id='{node.element_id}']")
        if node.direct_text:
            suggestions.append(f"//*[text()='{node.direct_text[:50]}']")

        return suggestions

    def _find_scoping_container(self, node: KGNode) -> dict | None:
        """Find the nearest meaningful scoping container (dialog, tab panel, section, etc.)."""
        scoping_roles = {"dialog", "tabpanel", "region", "navigation", "main", "form", "grid", "menu"}
        scoping_tags = {"dialog", "section", "nav", "form", "table", "main", "aside"}

        for ancestor in self.kg.get_ancestors(node.id):
            if ancestor.role in scoping_roles or ancestor.tag in scoping_tags:
                return {
                    "tag": ancestor.tag,
                    "role": ancestor.role,
                    "id": ancestor.element_id,
                    "aria_label": ancestor.aria_label,
                    "data_testid": ancestor.data_testid,
                }
        return None
