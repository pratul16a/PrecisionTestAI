"""Smoke test: KG -> StructuredSearch -> GraphTraversal without browser/LLM."""
import sys, traceback
from web_selectors.KnowledgeGraph import KnowledgeGraph, KGNode
from web_selectors.StructuredSearch import StructuredSearchEngine, filter_relevant_candidates
from web_selectors.GraphTraversal import GraphTraversal

fake_tree = {
    "tag": "body", "xpath": "/body", "visible": True, "depth": 0,
    "text": "", "directText": "", "id": "", "class": "", "role": "",
    "ariaLabel": "", "placeholder": "", "dataTestId": "", "name": "", "type": "",
    "rect": {}, "children": [
        {"tag": "form", "xpath": "/body/form", "visible": True, "depth": 1,
         "text": "", "directText": "", "id": "searchForm", "class": "", "role": "",
         "ariaLabel": "", "placeholder": "", "dataTestId": "", "name": "", "type": "",
         "rect": {}, "children": [
            {"tag": "input", "xpath": "/body/form/input", "visible": True, "depth": 2,
             "text": "", "directText": "", "id": "q", "class": "", "role": "textbox",
             "ariaLabel": "Search", "placeholder": "Search", "dataTestId": "search-input",
             "name": "q", "type": "text", "rect": {}, "children": []},
            {"tag": "button", "xpath": "/body/form/button", "visible": True, "depth": 2,
             "text": "Search", "directText": "Search", "id": "btn", "class": "btn",
             "role": "button", "ariaLabel": "", "placeholder": "", "dataTestId": "",
             "name": "", "type": "submit", "rect": {}, "children": []},
         ]}
    ]
}

def main():
    try:
        kg = KnowledgeGraph()
        kg.load_parsed_structure(fake_tree)

        nodes = kg.get_all_nodes()
        assert all(isinstance(n, KGNode) for n in nodes)
        print(f"OK: {len(nodes)} nodes, types fine")

        # exercise every attribute GraphTraversal/StructuredSearch touches
        for n in nodes:
            _ = (n.id, n.element_id, n.tag, n.text, n.direct_text, n.role,
                 n.aria_label, n.placeholder, n.data_testid, n.xpath, n.visible,
                 n.rect, n.class_name, n.frame_url, n.frame_name,
                 n.sibling_ids, n.child_ids, n.parent_id)
        print("OK: all KGNode attributes readable")

        engine = StructuredSearchEngine(kg)
        intent = {"action": "click",
                  "target": {"text": "search", "element_hints": ["button", "input"]},
                  "label": None, "anchor": None, "keywords": ["search"]}
        cands = engine.search(intent, top_k=5)
        print(f"OK: structured search returned {len(cands)} candidates")

        # also heuristic
        h = engine.search_heuristic("search", top_k=5)
        print(f"OK: heuristic search returned {len(h)} candidates")

        cands = filter_relevant_candidates(cands, threshold=0.0)
        assert cands, "no candidates after filter"

        gt = GraphTraversal(kg)
        ctx = gt.build_subtree_context_locatable_v2(cands)
        print(f"OK: GraphTraversal produced context len={len(ctx)}")

        # ancestors for top candidate
        top_node = cands[0][0]
        ancs = kg.get_ancestors(top_node.id)
        for a in ancs:
            _ = (a.element_id, a.tag, a.role, a.aria_label, a.data_testid, a.text)
        print(f"OK: get_ancestors returned {len(ancs)} wrapped nodes")

        print("\nSMOKE PASSED")
        return 0
    except Exception as e:
        traceback.print_exc()
        print(f"\nSMOKE FAILED: {e}")
        return 1

sys.exit(main())
