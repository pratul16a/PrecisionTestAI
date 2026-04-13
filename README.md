# PrecisionTest AI — Local Edition

NL → Browser Automation → BDD Test Generation

A natural language prompt like *"Launch browser, click JPMorgan Chase, verify No Documents Available"*
flows through **4 LLM calls** across **8 phases**, producing automated browser actions and a BDD `.feature` file.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Set your Anthropic API key
export ANTHROPIC_API_KEY="sk-ant-..."

# 3. Run the UI
python app.py
# Open http://localhost:1113

# OR run from CLI
python skill_agent.py "Launch browser, navigate to https://example.com, verify Example Domain is visible" --json
```

## Architecture (8 Phases)

```
User Prompt
    │
    ▼
Phase 1: UI & Backend
    conversation_ui.html → app.py (FastAPI) → orchestrator.py
    │
    ▼
Phase 2: Config & App Detection
    config_utils.py — detect app from URL, build run config
    │
    ▼
Phase 3: 🔴 LLM Call #1 — Tool Decomposition (Claude)
    prompt_utils.py → llm_api.call_llm()
    Input: User prompt + 12 tool schemas
    Output: JSON array of {tool, args}
    │
    ▼
Phase 4: Sequential Tool Execution Loop
    orchestrator.py → playwright_handlers_local.py
    FOR EACH tool_call → execute → capture status/screenshot
    │
    ├─── For click/type/assert actions ──┐
    │                                     ▼
    │                         Phase 5: Element Locator Pipeline
    │                         web_selectors/web_selectors.py
    │                           Step A: Cache Lookup (fuzzy match)
    │                           Step B: DOM Scraping (DOMSemanticParser)
    │                           Step C: 🔴 LLM #3 — Intent Extraction
    │                           Step D: Graph Search (StructuredSearch)
    │                           Step E: Context Building (GraphTraversal)
    │                           Step F: 🔴 LLM #4 — Locator Generation
    │                           Step G: Validate & Highlight
    │                           Step H: Manual Fallback (click-capture)
    │                                     │
    ├─────────────────────────────────────┘
    ▼
Phase 6: Action Execution
    playwright_handlers_local.py — click/fill/assert via Playwright
    │
    ▼
Phase 7: 🔴 LLM Call #2 — BDD Feature File Generation (Claude)
    llm_api.generate_feature_file_from_feature_steps()
    │
    ▼
Phase 8: Reports & Artifacts
    report_generator.py
    ├── scenario_steps_status.json
    ├── scenario_steps_status.html (visual report)
    └── {app}_test.feature (Gherkin BDD)
```

## Key Files

| Role | File | Key Functions |
|------|------|---------------|
| UI | templates/conversation_ui.html | Chat interface, POSTs prompt |
| FastAPI Backend | app.py | /run_playwright_codegen endpoint |
| Orchestrator | orchestrator.py | run_playwright_pipeline() |
| Tool Handlers | playwright_handlers_local.py | launch_browser(), click(), assert_element_visible() |
| Prompt Builder | client/prompt_utils.py | build_tool_prompt() |
| LLM Caller | client/llm_api.py | call_llm(), format_llm_response(), generate_feature_file() |
| Config/Detection | client/config_utils.py | extract_app_name_from_query(), build_config() |
| BDD Parser | client/bdd_parser.py | extract_gherkin_block() |
| Locator Engine | web_selectors/web_selectors.py | get_selector() |
| DOM Scraper | web_selectors/DOMSemanticParser.py | run_full_sequence() — JS DOM walker |
| Knowledge Graph | web_selectors/KnowledgeGraph.py | convert_to_graph() |
| Graph Search | web_selectors/StructuredSearch.py | search() — two-phase scoring |
| Heuristic Search | web_selectors/StructuredSearch.py | EmbeddingEngine.search_heuristic() |
| Context Builder | web_selectors/GraphTraversal.py | build_subtree_context_locatable_v2() |
| Fuzzy Match | web_selectors/word_similarity.py | combined_similarity() |
| Manual Fallback | web_selectors/missing_locator_handler.py | Injects click-capture modal |
| Report Generator | report_generator.py | HTML + JSON reports |
| Skill Agent | skill_agent.py | run_test() — single entry point for Copilot |

## Differences from Work Version

| Aspect | Work (JPMC) | Local |
|--------|-------------|-------|
| LLM #1, #2 | JPMC LLMSuite | Claude (Anthropic API) |
| LLM #3, #4 | Azure OpenAI GPT-4.1 | Claude (Anthropic API) |
| Browser Infra | Selenium Grid (Selenoid+VNC) → CDP → Playwright | Direct Playwright |
| MCP Server | FastMCP via stdio | Not needed (direct function calls) |
| Locator Cache | S3 + local JSON | Local JSON only |

## Copilot / Skill Agent Usage

```python
from skill_agent import run_test

# Async
result = await run_test("Navigate to app, search 902128, verify results")

# Sync
result = run_test_sync("Navigate to app, search 902128, verify results")

# Result contains: status, passed, failed, feature_file, html_report
```

## Environment Variables

- `ANTHROPIC_API_KEY` — Required. Your Anthropic API key.
- `PLAYWRIGHT_HEADLESS` — Set to "1" for headless mode.
