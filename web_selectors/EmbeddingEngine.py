"""
EmbeddingEngine.py — Heuristic + intent-aware fallback search.

No ML embeddings — this is a fallback for when StructuredSearch returns nothing.
Uses Levenshtein + Jaccard + TF-IDF-ish scoring over the KG's text fields.

Two entry points:
    search_heuristic(query_text, top_k)       — raw query text match
    search_with_intent(parsed_intent, top_k)  — uses target/label/keywords from intent
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .KnowledgeGraph import KnowledgeGraph
from .StructuredSearch import NodeMatchCriteria, StructuredSearchEngine
from .word_similarity import combined_similarity, jaccard_similarity

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """Heuristic fallback engine — text-similarity scoring over the KG."""

    def __init__(self, kg: KnowledgeGraph, embedding_cache: Optional[str] = None):
        self.kg = kg
        # embedding_cache param kept for compatibility with V2 callsites; unused here.

    def search_heuristic(
        self,
        query_text: str,
        top_k: int = 10,
        prefer_visible: bool = True,
    ) -> List[Dict[str, Any]]:
        """Score every KG node by fuzzy text similarity to query_text."""
        q = (query_text or "").strip().lower()
        if not q:
            return []

        ss = StructuredSearchEngine(self.kg)
        out: List[Dict[str, Any]] = []
        for nid in self.kg.nodes:
            meta = self.kg.node_metadata.get(nid, {})
            if not meta:
                continue
            if prefer_visible and not ss._is_visible(meta):
                continue
            node_text = self._concat_node_text(meta).lower()
            if not node_text:
                continue
            # Blend: Levenshtein(token best) + Jaccard(word sets)
            sim1 = combined_similarity(q, node_text[:500])
            sim2 = jaccard_similarity(set(q.split()), set(node_text.split()))
            score = 3.0 * sim1 + 2.0 * sim2
            if score > 0.2:
                out.append({"node_id": nid, "score": score, "metadata": meta})
        out.sort(key=lambda x: x["score"], reverse=True)
        return out[:top_k]

    def search_with_intent(
        self,
        parsed_intent: Dict[str, Any],
        top_k: int = 10,
        prefer_visible: bool = True,
    ) -> List[Dict[str, Any]]:
        """Intent-aware heuristic: treat target.text + label.text + keywords as a single
        pool of search terms and score nodes by best-matching term."""
        if not parsed_intent:
            return []
        terms: List[str] = []
        t = parsed_intent.get("target") or {}
        for k in ("text", "placeholder"):
            v = (t.get(k) or "").strip()
            if v:
                terms.append(v)
        label = parsed_intent.get("label") or {}
        if isinstance(label, dict):
            lt = (label.get("text") or "").strip()
            if lt:
                terms.append(lt)
        kws = parsed_intent.get("keywords") or []
        if isinstance(kws, list):
            for kw in kws:
                if isinstance(kw, str) and kw.strip():
                    terms.append(kw.strip())

        if not terms:
            return []

        all_results: Dict[str, Dict[str, Any]] = {}
        for term in terms:
            for r in self.search_heuristic(term, top_k=top_k, prefer_visible=prefer_visible):
                nid = r["node_id"]
                if nid not in all_results or r["score"] > all_results[nid]["score"]:
                    all_results[nid] = r
        merged = sorted(all_results.values(), key=lambda x: x["score"], reverse=True)
        return merged[:top_k]

    @staticmethod
    def _concat_node_text(meta: Dict[str, Any]) -> str:
        attrs = meta.get("attrs", {}) or {}
        parts = [
            meta.get("text", ""),
            meta.get("innerText", ""),
            meta.get("text_own_norm", ""),
            meta.get("text_content_raw", ""),
            attrs.get("aria-label", ""),
            attrs.get("placeholder", ""),
            attrs.get("title", ""),
            attrs.get("data-testid", ""),
            attrs.get("name", ""),
        ]
        return " ".join(str(p) for p in parts if p)
