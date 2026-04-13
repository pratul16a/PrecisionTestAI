"""
StructuredSearch.py - Graph Search (no LLM)
Two-phase scoring: text/tag/role/visibility match, then anchor proximity re-ranking.

EmbeddingEngine.py - Heuristic Search fallback
Levenshtein + Jaccard + cosine TF-IDF (no actual embeddings model).
"""
import logging
from .KnowledgeGraph import KnowledgeGraph, KGNode
from .word_similarity import combined_similarity, jaccard_similarity, levenshtein_similarity

logger = logging.getLogger(__name__)


class StructuredSearchEngine:
    """Score and rank KG nodes against a structured intent query."""

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    def search(self, structured_query: dict, top_k: int = 10) -> list[tuple[KGNode, float]]:
        """
        Two-phase search:
          Phase 1: Score every KG node (text match + tag/role + visibility)
          Phase 2: Anchor proximity re-ranking
        """
        target = structured_query.get("target") or {}
        target_text = target.get("text", "") or ""
        element_hints = target.get("element_hints", []) or []
        anchor = structured_query.get("anchor") or {}
        anchor_scope = anchor.get("scope_type", "") or ""
        anchor_text = anchor.get("text", "") or ""
        keywords = structured_query.get("keywords", []) or []

        candidates = []

        # Phase 1: Score all nodes
        for node in self.kg.get_all_nodes():
            score = self._score_node(node, target_text, element_hints, keywords)
            if score > 0.1:
                candidates.append((node, score))

        # Sort by score descending
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Phase 2: Anchor proximity re-ranking
        if anchor_text or anchor_scope:
            candidates = self._rerank_by_anchor(candidates, anchor_text, anchor_scope)

        return candidates[:top_k]

    def _score_node(self, node: KGNode, target_text: str, hints: list, keywords: list) -> float:
        """Score a single node against the target."""
        score = 0.0

        if not node.visible:
            return 0.0

        # Text match (check direct_text, aria_label, placeholder, text)
        searchable = [
            node.direct_text,
            node.aria_label,
            node.placeholder,
            node.data_testid,
            node.text[:100],
        ]

        best_text_score = 0.0
        for field in searchable:
            if field:
                sim = combined_similarity(target_text.lower(), field.lower())
                best_text_score = max(best_text_score, sim)

        score += best_text_score * 5.0  # Heaviest weight on text match

        # Tag/role match with hints
        tag_role = f"{node.tag} {node.role}".lower()
        for hint in hints:
            if hint.lower() in tag_role:
                score += 2.0

        # Keyword match
        node_text_all = f"{node.text} {node.aria_label} {node.placeholder} {node.class_name}".lower()
        for kw in keywords:
            if kw.lower() in node_text_all:
                score += 1.0

        # Bonus for interactive elements
        interactive_tags = {"button", "a", "input", "select", "textarea", "label"}
        interactive_roles = {"button", "link", "tab", "menuitem", "option", "checkbox", "radio", "textbox"}
        if node.tag in interactive_tags or node.role in interactive_roles:
            score += 1.0

        return score

    def _rerank_by_anchor(self, candidates: list[tuple[KGNode, float]],
                          anchor_text: str, anchor_scope: str) -> list[tuple[KGNode, float]]:
        """Re-rank by proximity to an anchor element (e.g., within a specific tab/panel)."""
        if not anchor_text and not anchor_scope:
            return candidates

        reranked = []
        for node, score in candidates:
            bonus = 0.0
            # Check if any ancestor matches the anchor
            ancestors = self.kg.get_ancestors(node.id)
            for anc in ancestors:
                anc_text = f"{anc.text} {anc.role} {anc.aria_label}".lower()
                if anchor_text and anchor_text.lower() in anc_text:
                    bonus += 2.0
                    break
                if anchor_scope and anchor_scope.lower() in f"{anc.role} {anc.tag}".lower():
                    bonus += 1.5
                    break
            reranked.append((node, score + bonus))

        reranked.sort(key=lambda x: x[1], reverse=True)
        return reranked

    def search_heuristic(self, query_text: str, top_k: int = 10) -> list:
        """Delegate to EmbeddingEngine's heuristic search."""
        return EmbeddingEngine(self.kg).search_heuristic(query_text, top_k=top_k)


class EmbeddingEngine:
    """
    Heuristic fallback search using Levenshtein + Jaccard + TF-IDF.
    No actual embedding model — cosine on term-frequency vectors.
    """

    def __init__(self, kg: KnowledgeGraph):
        self.kg = kg

    def search_heuristic(self, query_text: str, top_k: int = 10) -> list[tuple[KGNode, float]]:
        """Fallback heuristic search when structured search returns poor results."""
        candidates = []

        for node in self.kg.get_all_nodes():
            if not node.visible:
                continue

            node_text = f"{node.direct_text} {node.aria_label} {node.placeholder} {node.data_testid}".strip()
            if not node_text:
                continue

            score = combined_similarity(query_text.lower(), node_text.lower())
            if score > 0.2:
                candidates.append((node, score))

        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[:top_k]


def filter_relevant_candidates(candidates: list[tuple[KGNode, float]],
                                threshold: float = 0.3) -> list[tuple[KGNode, float]]:
    """Prune candidates by threshold + keyword overlap."""
    return [(node, score) for node, score in candidates if score >= threshold]
