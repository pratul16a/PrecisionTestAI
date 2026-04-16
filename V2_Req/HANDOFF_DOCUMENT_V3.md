# PRECISIONTEST AI — V3 HANDOFF DOCUMENT
# Complete Replication Spec + Hardening Roadmap
# Feed this ENTIRE document as context to Claude Code

---

## PART 0: WHAT IS THIS

An agentic test automation platform that converts natural language prompts into
executable browser tests. A prompt like "check feedback for client 902128" flows
through 4 LLM calls across 8 phases, producing automated browser actions, element
locators, BDD .feature files, and visual reports.

**Core principle:** AI authors test artifacts. JS Framework executes them. Zero AI in execution.

**Deployment mode for home replication:** LOCAL SDK (direct Playwright, no Selenium Grid).

---

## PART 1: ARCHITECTURE — 8 PHASES

```
USER TYPES PROMPT IN BROWSER
"Launch a browser and navigate to '...'. Click JPMorgan Chase (Default)..."
    │
    ▼
PHASE 1 — UI & Backend
  conversation_ui.html → app.py (FastAPI) → run_playwrightmethod()
  POST {prompt} → http://localhost:1113/run_playwright_codegen
    │
    ▼
PHASE 2 — Config & MCP Server Boot
  playwright_custom_mcp_client.py :: run()
  config_utils.extract_app_name_from_query(prompt) → "ICE" / "RDP" / etc.
  config_utils.build_config("ICE", run_id) → 20+ paths
  Spawn MCP Server: StdioServerParameters("playwright_custom_mcp_server.py")
  playwright_custom_mcp_server.py: FastMCP("element-locate-server")
  playwright_handlers.registerTools(mcp) → registers 20+ tools
    │
    ▼
PHASE 3 — 🔴 LLM CALL #1: TOOL DECOMPOSITION
  prompt_utils.build_tool_prompt(prompt, tools) builds system prompt
  + 20+ tool schemas (name, description, inputSchema)
  Rules: field_name → exact name, field_type → element type,
         field_description → VERBATIM text, split compound → atomic, add close_browser
  llm_api.call_llm(prompt) → LLM endpoint
  OUTPUT: JSON array of [{tool, args}, ...]
  Example: launch_browser → click → navigate_to_url → enter_text → click → click →
           assert_element_visible × 2 → close_browser
    │
    ▼
PHASE 4 — SEQUENTIAL TOOL EXECUTION LOOP
  llm_api.llm_tool_call(session, tool_list, config)
  FOR EACH tool_call in tool_list:
    ├ Inject run_id, seal_id, project_name, component_name
    ├ session.call_tool(name, arguments) → MCP Server via stdio
    ├ parse_tool_response() → {status, featurestep, screenshot}
    ├ IF status == "failed" → STOP execution
    └ Append featurestep to feature_steps[]
    │
    ▼ (for each click/type/assert tool)

PHASE 5 — ELEMENT LOCATOR PIPELINE (the smart part)
  web_selectors.py :: get_selector()

  STEP A: Cache Lookup (no LLM)
    get_selector_from_json_file(field_name, field_type, page_url)
    → Load per-page JSON file
    → Try exact name match
    → Try fuzzy similarity via word_similarity.py (Levenshtein/Jaccard)
    → If found & valid → RETURN immediately
    │ MISS
    ▼
  STEP B: DOM Scraping
    scraping_by_knowledge_graph.py :: run_scraping()
    B1. DOMSemanticParser.run_full_sequence(page)
        → Injects JS DOM walker into every frame
        → Extracts ALL elements: tag, text, id, class, role,
          aria-*, data-*, placeholder, computed styles, visibility,
          bounding rect, XPath, parent chain, shadow DOM
        → Handles iframes recursively, scrolls for lazy content
        → Returns parsed DOM tree (up to 200K nodes)
    B2. KnowledgeGraph.load_parsed_structure(tree)
        KnowledgeGraph.convert_to_graph()
        → 29 semantic edge types (containment, label, table, grouping, tabs)
        → Parent-child + sibling edges with spatial metadata
    │
    ▼
  STEP C: 🔴 LLM CALL #3 — INTENT EXTRACTION
    Prompt: ENHANCED_INTENT_PROMPT_TEMPLATE
    "Parse the user's UI automation query into structured JSON:
      { action, target: {text, placeholder, element_hints, properties},
        label: {text, relation},
        anchor: {scope_type, text, relation},
        keywords: [...] }"
    label = 'which specific element?' (adjacent text)
    anchor = 'in which region?' (broader container)
    → Azure OpenAI GPT-4.1 returns structured intent JSON
    │
    ▼
  STEP D: Graph Search (no LLM)
    StructuredSearchEngine.search(structured_query, top_k=10)
      Phase 1: Score every KG node (text match + tag/role + visibility)
      Phase 2: Anchor proximity re-ranking
    Fallback: EmbeddingEngine.search_heuristic() — Levenshtein +
              Jaccard + cosine TF-IDF (no actual embeddings model)
    _filter_relevant_candidates() — prune by threshold + keyword overlap
    │ top 10 candidate nodes
    ▼
  STEP E: Context Building (no LLM)
    GraphTraversal.build_subtree_context_locatable_v2(candidates)
    → For each candidate: ancestor chain, sibling relations,
      spatial layout, stability metadata, locator suggestions,
      scoping containers, frame details
    → Token-trimmed to 50K tokens
    │ rich context JSON
    ▼
  STEP F: 🔴 LLM CALL #4 — LOCATOR GENERATION
    Prompt: assistant_instructions.txt (~940 lines) with:
    "You are a QA assistant. Generate a robust XPath locator.
     FORBIDDEN PATTERNS: No JSS/MUI/Emotion/styled-component classes, No CSS-module hashes
     PRIORITY ORDER: data-testid > aria-* > role > id > text() > position
     RULES: Use ancestor scoping for ambiguous matches
            Handle grid/dialog/tab/menu patterns
            text() for direct text, . for descendant text
            Verify match_count = 1
     CONTEXT: __CONTEXT__ (replaced with subtree JSON)
     QUERY: __USER_QUERY__ (replaced with field_description)"
    OUTPUT: {xpath, frame_url, frame_name, confidence, reasoning, match_count}
    → Azure OpenAI GPT-4.1 returns XPath locator
    │
    ▼
  STEP G: Validate & Highlight
    1. Check xpath against forbidden patterns (5 regex patterns)
    2. Auto-fix pollution: normalize-space(.)='X' → contains(., 'X')
    3. _highlight_element_on_page() → injects JS to scroll + flash
    4. If match_count == 0 → 🔴 LLM CALL #4b (RETRY with error)
    5. Save locator to JSON cache for future reuse
    → Return {xpath, frame_url, frame_name, confidence}
    │
    ▼
  STEP H (last resort): Manual Fallback
    missing_locator_handler.py → injects modal dialog in browser
    → user clicks target element → captures XPath from click event
    │
    ▼
← Returns validated xpath back to PHASE 4 tool handler

PHASE 6 — ACTION EXECUTION
  playwright_handlers_updated.py :: (inside each tool function)
  1. Resolve correct frame (main page or iframe by frame_url/frame_name)
  2. Create Playwright Locator from XPath
  3. Execute: .click() / .fill() / .is_visible() / etc.
  4. Take base64 screenshot after action
  5. Return {status:"success", featurestep:"When I click on '...'",
            screenshot:"base64...", arguments:{...}}
    │
    ▼
PHASE 7 — 🔴 LLM CALL #2: BDD FEATURE FILE GENERATION
  llm_api.generate_feature_file_from_feature_steps()
  Collected feature_steps from all tools →
  LLM generates Gherkin .feature with Scenario Outline + Examples
  → bdd_parser.py :: extract_gherkin_block() writes to FEATURE_FILE_PATH
    │
    ▼
PHASE 8 — REPORTS & ARTIFACTS
  1. scenario_steps_status.json — pass/fail per step with screenshots
  2. scenario_steps_status.html — visual report with green/red dots
  3. .feature file — Gherkin BDD
  4. Artifacts optionally uploaded to S3
  5. Response returned to conversation_ui.html → displayed to user
```

---

## PART 2: KEY FILES REFERENCE

| Role | File | Key Functions |
|------|------|---------------|
| UI | conversation_ui.html | processUserMessage() — POSTs prompt |
| FastAPI Backend | app.py | /run_playwright_codegen endpoint |
| Orchestrator | playwright_custom_mcp_client.py | run(), run_playwrightmethod() |
| MCP Server | playwright_custom_mcp_server.py | FastMCP(), registerTools() |
| Tool Handlers | playwright_handlers_updated.py | BrowserSession, launch_browser(), click(), 40+ tools |
| Prompt Builder | client/prompt_utils.py | build_tool_prompt() |
| LLM Caller | client/llm_api.py | call_llm(), format_llm_response(), llm_tool_call() |
| Config/App Detection | client/config_utils.py | extract_app_name_from_query(), build_config() |
| BDD Parser | client/bdd_parser.py | extract_gherkin_block(), extract_cucumber_files() |
| Locator Engine | web_selectors/web_selectors.py | get_selector(), get_selector_from_json_file() |
| DOM Scraper | web_selectors/DOMSemanticParser.py | run_full_sequence() — JS DOM walker |
| Knowledge Graph | web_selectors/KnowledgeGraph.py | convert_to_graph(), build_subtree_context_locatable_v2() |
| Intent + Locator LLM | web_selectors/scraping_by_knowledge_graph.py | run_scraping(), ENHANCED_INTENT_PROMPT_TEMPLATE |
| Graph Search | web_selectors/StructuredSearch.py | search() — two-phase scoring |
| Heuristic Search | web_selectors/EmbeddingEngine.py | search_heuristic() — Levenshtein/Jaccard/TF-IDF |
| Fuzzy Match | web_selectors/word_similarity.py | Similarity scoring for cache lookup |
| Locator Mega-Prompt | web_selectors/assistant_instructions.txt | ~940-line XPath generation rules |
| Manual Fallback | web_selectors/missing_locator_handler.py | Injects click-capture modal |

---

## PART 3: 4 LLM CALLS SUMMARY

| # | Purpose | Endpoint | Prompt Source | Input | Output |
|---|---------|----------|--------------|-------|--------|
| #1 | Tool Decomposition | LLM endpoint | prompt_utils.build_tool_prompt() | User's NL prompt + 20+ tool schemas | JSON array of {tool, arguments} |
| #2 | BDD Generation | LLM endpoint | Inline in llm_api.py | Collected feature steps | Gherkin .feature file |
| #3 | Intent Extraction | LLM endpoint | ENHANCED_INTENT_PROMPT_TEMPLATE | Field name + type + action | Structured intent JSON (target, label, anchor, keywords) |
| #4 | Locator Generation | LLM endpoint | assistant_instructions.txt (~940 lines) + DOM context | DOM subtree JSON + user query | {xpath, frame_url, confidence, reasoning} |
| #4b | Locator Retry | LLM endpoint | Same + error feedback | Same + "0 matches found, try again" | Corrected xpath |

---

## PART 4: CAPTURED CODE — WHAT'S READY FOR REPLICATION

### 4.1 assistant_instructions.txt (100% — ~940 lines)
Full content captured in Session 1. See HANDOFF_DOCUMENT_V2.md section 4.1 for complete 34-section breakdown.

### 4.2 DOMSemanticParser.py (100% — ~600 lines)
Full class captured in Session 2. All 15 JS helper functions, walk() node output schema,
full Python class with fetch_raw_dom, frame ID management, 5-tier iframe pairing heuristics,
ownerIframe merge, complete output structure.

### 4.3 scraping_by_knowledge_graph.py (100% — ~1,237 lines)
See CAPTURE_scraping_by_knowledge_graph.md for complete transcription.
10 helper functions + main orchestration function covering the entire pipeline from
DOM parse to XPath return.

### 4.4 playwright_handlers_updated.py (100% — ~4,425 lines)
Full file captured in Session 1. 40+ tool handlers, BrowserSession dataclass,
hybrid Selenium→Playwright launch, sanitize_selector(), frame resolution.

### 4.5 KnowledgeGraph.py (~90% — ~2,241 lines)
See CAPTURE_KnowledgeGraph.md for complete transcription.
**Fully captured:** EdgeTypes (29 types), KnowledgeGraph class (all data structures),
convert_to_graph() with _make_node_id + traverse, _build_semantic_edges dispatch,
_build_containment_edges (BFS), _compute_stability_info (text_source, _looks_random,
_class_looks_random, dynamic ID patterns), compare_with, validate_graph, export_json,
GraphTraversal._slim_meta, _ancestor_depth_map, _resolve_anchor_nodes, _resolve_label_nodes.
**Inferrable gaps:** _build_label_edges, _build_table_structure_edges, _build_grouping_edges,
_build_tab_edges (patterns clear from EdgeTypes), build_subtree_context_locatable_v2
(name confirmed, output schema known from consumers), spatial_relation, _compute_tree_relation.

### 4.6 StructuredSearch.py (~90% — ~1,100 lines)
See CAPTURE_StructuredSearch.md for complete transcription.
**Fully captured:** NodeMatchCriteria + StructuredQuery dataclasses, 4 mapping tables
(_ACTION_PROPERTY_MAP, _ELEMENT_HINT_EXPANSION, _ANCHOR_SCOPE_EXPANSION, _RELATION_TO_SPATIAL),
IntentQueryBuilder.build() (full query construction), ENHANCED_INTENT_PROMPT_TEMPLATE (full
with 10 examples), StructuredSearchEngine.search() (strategy dispatch), _score_node() (full
TEXT-FIRST scoring with exact point values), _find_nearby_by_criteria (BFS from anchor/label),
_build_ancestor_set, _node_tree_distance, _compute_proximity_bonus, _keyword_fallback, _is_visible.
**Inferrable gaps:** _score_all_nodes (iterates all nodes, calls _score_node),
_phase1_container_scoped_search, _phase1_grid_column_search, _phase2_anchor_proximity.

---

## PART 5: SCORING FORMULA REFERENCE

```
TEXT TIER — primary signal (max ~28)
  equals.text exact match:           +20.0
  contains.text substring match:     +4.0–8.0  (scaled by coverage)
  contains.text word-level overlap:  +1.5–4.0
  Exact placeholder match:           +15.0
  Partial placeholder match:         +6.0
  No text relevance penalty:         -4.0

ELEMENT TIER — secondary tie-breaker (max ~5)
  tag hints match:                   +2.0
  tag hints mismatch + text match:   0.0  (no penalty)
  tag_hints mismatch + no text:      -2.0
  role hints match:                  +1.0
  isClickable / isInput property:    +0.5
  Interactive element bonus:         +1.0
  Non-interactive penalty:           -1.5  (only when text_matched=False)

ACCESSORY SIGNALS (max ~4)
  aria-label / placeholder:          +2.0 (exact), +1.0 (partial)
  data-testid:                       +3.5 (exact), +1.5 (partial)
  Icon-specific attrs:               +3.0 (exact), +1.5 (partial)
  id match:                          +2.5 (exact), +1.2 (partial)
  Visibility bonus:                  +0.5

RELEVANCE FILTER thresholds:
  min_abs_score:     1.0 (primary), 0.5 (supplemental fallback)
  min_relative_pct:  0.10 (primary), 0.05 (supplemental fallback)
  max_candidates:    5
  Tag mismatch penalty: score * 0.08 (~92% penalty, unless TEXT-FIRST match)

PROXIMITY BONUS:
  Direct ancestor:     max(0.0, 15.0 - depth * 1.5)
  Sibling:             max(0.0, 12.0 - depth * 2.0) - sibling_distance * 0.8 - headers * 5.0
  Ancestor text match: max(0.0, 12.0 - depth * 1.5)
```

---

## PART 6: EDGE TYPES REFERENCE

```
STRUCTURAL:        parent_of, child_of
CONTAINMENT (15):  contained_in_{form,dialog,table,grid,nav,section,fieldset,
                   menu,toolbar,tabpanel,listbox,header,footer,aside,main}
LABEL (4):         label_for, labeled_by, aria_labelledby, aria_describedby
TABLE (5):         header_of, row_of, cell_of_row, cell_of_column, caption_of
GROUPING (2):      grouped_by, legend_of
TABS (2):          tab_for, tab_of
```

---

## PART 7: DYNAMIC ID REJECTION PATTERNS

```python
# IDs matching these → rejected as dynamic, NOT used in locators
r"[a-f0-9]{16,}"           # hex hash
r"[a-z]+-[a-f0-9]{6,}$"    # prefix-hash
r"^\d+$"                    # pure numbers
r"^[a-z0-9]+$"             # React internal IDs
r"^:r\d+:$"                # React colon format
r"ember\d+$"               # Ember
r"text-gen\d+$"            # ExtJS
r"[a-z]+-\d{4,}$"          # prefix + many digits
r"jpmui-\d+.*"             # JPMU framework auto IDs
r"^jpmui-.*"               # JPMU numeric variant
r"label-salt-\d+$"         # Salt Design System sequential label IDs
r"HelperText-salt-\d+$"    # Salt Design System sequential helper IDs
r"salt-\d+$"               # Salt Design System sequential name/group IDs
```

---

## PART 8: FORBIDDEN XPATH PATTERNS

```python
_FORBIDDEN_XPATH_PATTERNS = [
    (r'\bjss\d+\b',                          'JSS class'),
    (r'\bMui[A-Z][a-zA-Z]*-[\w]+\b',        'MUI class'),
    (r'\bsc-[a-zA-Z]{6,}\b',                'styled-components class'),
    (r'\bcss-[a-z0-9]{6,}\b',               'Emotion class'),
    (r'\b[a-zA-Z]+_[a-zA-Z]+_[a-zA-Z0-9]{5}\b', 'CSS module class'),
]
```

---

## PART 9: REPLICATION PRIORITY ORDER

```
PHASE 1 — Core Pipeline (get a prompt → tool list → execution working)
  ├ app.py (FastAPI)
  ├ playwright_custom_mcp_client.py (orchestrator)
  ├ playwright_custom_mcp_server.py (MCP server)
  ├ playwright_handlers_local.py (tool handlers — local Playwright mode)
  ├ prompt_utils.py (tool prompt builder)
  ├ llm_api.py (LLM caller — swap to Anthropic/OpenAI)
  └ config_utils.py (paths, app detection)

PHASE 2 — Locator Engine (the brain)
  ├ web_selectors.py (get_selector with cache)
  ├ DOMSemanticParser.py (DOM scraping)
  ├ KnowledgeGraph.py (graph building)
  ├ StructuredSearch.py (scoring engine)
  ├ scraping_by_knowledge_graph.py (orchestrator)
  ├ assistant_instructions.txt (LLM prompt)
  └ word_similarity.py (cache fuzzy match)

PHASE 3 — Output & Reports
  ├ bdd_parser.py (feature file extraction)
  ├ report_generator.py (JSON + HTML reports)
  └ conversation_ui.html (frontend)

PHASE 4 — Hardening (test against real apps)
  ├ Fix failures found on local apps
  ├ Add EmbeddingEngine.py fallback
  ├ Add missing_locator_handler.py manual fallback
  └ Tune scoring weights if needed
```

---

## PART 10: HARDENING ROADMAP (post-replication)

### 10.1 Known Weak Points to Fix

**AG Grid / Virtual Scrolling**
Problem: Only visible rows are in the DOM. Target row might not exist yet.
Solution: Detect AG Grid (look for role="grid" + col-id attributes), inject JS to
scroll the grid API (`gridApi.ensureIndexVisible(row)`) before DOM parse.
The grid column search strategy in StructuredSearch already handles col-id matching.

**Shadow DOM**
Problem: Elements inside shadow roots are invisible to normal DOM traversal.
Current handling: DOMSemanticParser already traverses open shadow roots (via
`element.shadowRoot.querySelectorAll('*')`).
What to harden: For CSS selectors in shadow DOM, generate Playwright piercing
selectors (`>>`) instead of XPath. XPath cannot cross shadow boundaries.

**Ambiguous Elements (multiple matches)**
Problem: XPath matches 3 elements, which one is correct?
Solution: Already partially handled (visibility-first, match_count validation).
Harden by: Adding bounding rect filtering (pick the one closest to viewport center
or closest to the anchor element spatially), adding `[not(ancestor::*[@hidden])]`
to exclude hidden subtrees.

**Dropdowns / Combobox**
Problem: Two-phase interaction — click trigger opens dropdown, then click option
in a separate DOM subtree (often portal-mounted at body root).
Solution: Implement `select_from_dropdown` tool handler:
  1. Click the trigger element (role="combobox" or class-based)
  2. Wait for listbox/menu to appear
  3. Click the option in the NEW DOM state
The tool decomposition LLM should produce two separate tool calls for this.

**Content Loading / Lazy Tabs**
Problem: Tab content doesn't exist in DOM until the tab is clicked.
Solution: DOMSemanticParser should detect empty tabpanels (role="tabpanel" with
no meaningful children) and flag them. The scraping orchestrator should click tabs
to force content load before DOM parse for the element locator step.

**Iframes**
Problem: Cross-origin iframes can't be accessed. Same-origin iframes need
frame switching in Playwright.
Current handling: DOMSemanticParser has 5-tier iframe pairing heuristics.
What to harden: Ensure Playwright's `frame.locator(xpath)` is called on
the correct frame using frame_url/frame_name from the locator output.

### 10.2 New Features to Add

**Vision Fallback**
When locator confidence is "low" or match_count is 0 after retry,
take a screenshot and send it to a vision-capable LLM (GPT-4V or Claude)
with the user query. Use the LLM to identify the element visually and
provide coordinates for Playwright's `page.click(x, y)`.

**Self-Healing**
When a cached locator fails (match_count=0 on a subsequent run):
  1. Re-scrape the DOM
  2. Build a new KG
  3. Find the element using the original cached metadata (text, tag, attrs)
     as search criteria against the new KG
  4. Generate a new locator
  5. Update the cache
  Run proactively on deploy (scrape all cached pages, validate all locators)
  or reactively with --heal flag.

**Persistent App Map (KG Distiller)**
After each successful run, distill the raw KG (200K nodes) down to a
compact app map (50-100 entries per page) containing:
  - Interactive elements with stable locators
  - Container hierarchy (forms, dialogs, tabs)
  - Navigation paths between pages
Persist as JSON. Use in future runs to skip DOM scraping for known pages
(if page hasn't changed).

**RAG Wiring**
Connect the 4-layer RAG system to the pipeline:
  Layer 3: Glossary (YAML dict) — "feedback" → Client Feedback tab
  Layer 2: Workflows (YAML files) — tag [client, feedback] → client_feedback_check
  Layer 1: App map (JSON) — page context, AG Grid flags, shadow DOM flags
  Layer 4: ChromaDB embeddings (fallback)
When RAG resolves a prompt → skip LLM Call #1 → feed structured steps directly.

**Record Mode**
Before prompt hardening: implement a recording mode that captures user
browser interactions and:
  1. Seeds the locator cache with every element interacted with
  2. Generates YAML workflow files for Layer 2 RAG
  3. Builds initial app map for Layer 1 RAG

---

## PART 11: LLM PROVIDER SETUP FOR HOME

Replace JPMC LLMSuite / Azure OpenAI GPT-4.1 with:

```python
# Option A: Anthropic (recommended — you're already using Claude)
import anthropic
client = anthropic.Anthropic(api_key="...")

def call_llm(system_prompt: str, user_query: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-20250514",  # Fast + capable for tool decomp & intent
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_query}]
    )
    return response.content[0].text

# For locator generation (LLM Call #4), use Opus for highest accuracy:
def call_llm_locator(system_prompt: str, user_query: str) -> str:
    response = client.messages.create(
        model="claude-opus-4-20250514",
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_query}]
    )
    return response.content[0].text

# Option B: OpenAI
from openai import OpenAI
client = OpenAI(api_key="...")

def call_llm(system_prompt: str, user_query: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_query}
        ]
    )
    return response.choices[0].message.content
```

---

## PART 12: FILE STRUCTURE FOR HOME PROJECT

```
precisiontestai/
├── src/
│   ├── app.py                          ← FastAPI backend
│   ├── conversation_ui.html            ← Browser UI
│   ├── config_utils.py                 ← App detection + path config
│   ├── prompt_utils.py                 ← Tool prompt builder (LLM #1)
│   ├── llm_api.py                      ← LLM wrapper (swap provider here)
│   ├── bdd_parser.py                   ← Gherkin extraction
│   ├── report_generator.py             ← JSON + HTML reports
│   ├── playwright_mcp_client.py        ← Orchestrator
│   ├── playwright_mcp_server.py        ← MCP Server
│   ├── playwright_handlers.py          ← Tool handlers (40+)
│   └── web_selectors/
│       ├── __init__.py
│       ├── web_selectors.py            ← get_selector() cache + pipeline entry
│       ├── DOMSemanticParser.py         ← DOM scraping (15 JS helpers)
│       ├── KnowledgeGraph.py            ← Graph building (29 edge types)
│       ├── StructuredSearch.py          ← Two-phase scoring engine
│       ├── scraping_by_knowledge_graph.py ← Pipeline orchestrator
│       ├── EmbeddingEngine.py           ← Fallback search (Levenshtein/Jaccard)
│       ├── word_similarity.py           ← Cache fuzzy matching
│       ├── missing_locator_handler.py   ← Manual click-capture fallback
│       └── assistant_instructions.txt   ← LLM #4 prompt (~940 lines)
├── sample_app/
│   └── ICE_ClientPortal.jsx            ← Test target app
├── .precisiontest/
│   ├── locator_cache/                  ← Per-page XPath cache
│   ├── workflows/                      ← Layer 2 RAG
│   ├── glossary/                       ← Layer 3 RAG
│   └── artifacts/                      ← Test run outputs
├── requirements.txt
└── README.md
```

---

## PART 13: REFERENCE DOCUMENTS

The following capture documents contain line-by-line code transcriptions.
Feed these to Claude Code when implementing each specific file:

1. **HANDOFF_DOCUMENT_V2.md** — Original V2 handoff with assistant_instructions.txt
   breakdown, playwright_handlers_updated.py patterns, DOMSemanticParser.py complete
   capture, and architecture overview.

2. **CAPTURE_scraping_by_knowledge_graph.md** — Complete 1,237-line orchestrator with
   all 10 helper functions + main pipeline function.

3. **CAPTURE_KnowledgeGraph.md** — EdgeTypes, KnowledgeGraph class, convert_to_graph,
   GraphTraversal with _slim_meta, anchor/label resolution.

4. **CAPTURE_StructuredSearch.md** — Data models, IntentQueryBuilder, scoring formula,
   ENHANCED_INTENT_PROMPT_TEMPLATE, search strategies, _score_node with exact point values.

---

## HOW TO USE THIS DOCUMENT WITH CLAUDE CODE

1. Start a new Claude Code session
2. Feed this entire V3 handoff document as initial context
3. Say: "Build Phase 1 — get the core pipeline working with direct Playwright"
4. Claude Code builds the outer shell (app.py, config, MCP, handlers)
5. Say: "Build Phase 2 — implement the locator engine"
6. Feed the specific CAPTURE document for the file being built
7. Claude Code implements from the captured code
8. Test against ICE_ClientPortal.jsx
9. Fix failures → iterate
10. Test against real apps on local machine
11. Harden based on Part 10 roadmap
