"""
scraping_by_knowledge_graph.py - Intent + Locator LLM
Combines DOM scraping with LLM-based intent extraction.
Step B: DOM Scraping → Step C: LLM Call #3 Intent Extraction
"""
import json
import logging
from .DOMSemanticParser import DOMSemanticParser
from .KnowledgeGraph import KnowledgeGraph
from client.llm_api import call_llm

logger = logging.getLogger(__name__)

ENHANCED_INTENT_PROMPT_TEMPLATE = """Parse the user's UI automation query into structured JSON:
{{
    action: click|type|select|hover|...,
    target: {{text, placeholder, element_hints, properties}},
    label: {{text, relation: below|above|next_to|for}},
    anchor: {{scope_type: section|tab|panel, text, relation}},
    keywords: [...]
}}

label = 'which specific element?' (adjacent text)
anchor = 'in which region?' (broader container)

Query: '{query}'

Return ONLY valid JSON. No markdown fences, no explanation."""


async def run_scraping(page, query: str) -> tuple[KnowledgeGraph, dict]:
    """
    Run full scraping pipeline:
    B1. DOMSemanticParser.run_full_sequence(page)
    B2. KnowledgeGraph.load_parsed_structure(tree)
    C.  LLM Call #3 - Intent Extraction
    """
    # Step B: DOM Scraping
    parser = DOMSemanticParser(page)
    tree = await parser.run_full_sequence()

    # B2: Build knowledge graph
    kg = KnowledgeGraph()
    kg.load_parsed_structure(tree)

    # Step C: LLM Call #3 - Intent Extraction
    prompt = ENHANCED_INTENT_PROMPT_TEMPLATE.replace("{query}", query)
    response = call_llm(prompt)

    try:
        # Clean response
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
        structured_intent = json.loads(clean)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse intent JSON: {response[:200]}")
        structured_intent = {
            "action": "click",
            "target": {"text": query},
            "keywords": query.split(),
        }

    logger.info(f"Intent extracted: {json.dumps(structured_intent)[:200]}")
    return kg, structured_intent
