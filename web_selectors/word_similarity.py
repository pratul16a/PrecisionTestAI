"""
word_similarity.py — Fuzzy Match

Similarity scoring for cache lookup using Levenshtein, Jaccard, and basic TF-IDF.
"""
import re
import math
from collections import Counter


def levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """Normalized Levenshtein similarity (0 to 1)."""
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - levenshtein_distance(s1, s2) / max_len


def jaccard_similarity(s1: str, s2: str) -> float:
    """Jaccard similarity on word-level tokens."""
    tokens1 = set(_tokenize(s1))
    tokens2 = set(_tokenize(s2))
    if not tokens1 and not tokens2:
        return 1.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union) if union else 0.0


def tfidf_cosine_similarity(s1: str, s2: str) -> float:
    """Simple TF-IDF cosine similarity between two strings."""
    tokens1 = _tokenize(s1)
    tokens2 = _tokenize(s2)

    tf1 = Counter(tokens1)
    tf2 = Counter(tokens2)

    all_terms = set(tf1.keys()) | set(tf2.keys())
    if not all_terms:
        return 0.0

    # Simple IDF: treat both strings as "documents"
    doc_count = {}
    for term in all_terms:
        doc_count[term] = (1 if term in tf1 else 0) + (1 if term in tf2 else 0)

    vec1, vec2 = [], []
    for term in all_terms:
        idf = math.log(2.0 / doc_count[term]) + 1
        vec1.append(tf1.get(term, 0) * idf)
        vec2.append(tf2.get(term, 0) * idf)

    dot = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = math.sqrt(sum(a * a for a in vec1))
    mag2 = math.sqrt(sum(b * b for b in vec2))

    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


def combined_similarity(s1: str, s2: str, weights: tuple = (0.4, 0.3, 0.3)) -> float:
    """Weighted combination of all three similarity metrics."""
    lev = levenshtein_similarity(s1.lower(), s2.lower())
    jac = jaccard_similarity(s1.lower(), s2.lower())
    tfidf = tfidf_cosine_similarity(s1.lower(), s2.lower())
    return weights[0] * lev + weights[1] * jac + weights[2] * tfidf


def _tokenize(text: str) -> list[str]:
    """Simple word tokenizer."""
    return re.findall(r"\w+", text.lower())
