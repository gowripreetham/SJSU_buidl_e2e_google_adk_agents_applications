# End-to-end Google ADK agent applications — SJSU Special Topics, Assignment 3

Gowri Preetham Gunisetty · five agents on [Google ADK](https://google.github.io/adk-docs/) (`google-adk` 2.14), one repo.

| | Agent | ADK features shown | Folder | Video |
|---|---|---|---|---|
| a | **Lead-generation deep research** | `SequentialAgent` → `ParallelAgent` fan-out → `LoopAgent` critic/refine → ranked report; structured output; state templating | [`agents/lead_gen_research`](agents/lead_gen_research) | _add link_ |
| b | **Gemini CLI as a tool** in an ADK pipeline | function tool wrapping a subprocess; `before_tool_callback` budget; Cloud Run Dockerfile | [`agents/gemini_cli_agent`](agents/gemini_cli_agent) | _add link_ |
| c | **MCP bug assistant** | `McpToolset` over stdio to my own MCP server (SQLite tickets); MCP + local tools; guard callback | [`agents/bug_assistant`](agents/bug_assistant) | _add link_ |
| d | **Code review assistant** | review pipeline + bounded fix loop; tools read code from state; sandboxed test runs; gate callback | [`agents/code_review`](agents/code_review) | _add link_ |
| e | **E-commerce agent** | MCP store server (SQLite), identity injection, confirmation gate, audit trail, FastAPI + web UI | [`agents/ecommerce`](agents/ecommerce) | _add link_ |

Recording scripts: [`VIDEO_SCRIPTS.md`](VIDEO_SCRIPTS.md).

## Run

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env          # add your Gemini key

adk web agents                # ADK dev UI with all five agents — pick one in the dropdown

# or from the terminal (drop --mock to use Gemini)
python -m agents.lead_gen_research.demo --mock
python -m agents.gemini_cli_agent.demo --mock
python -m agents.bug_assistant.demo --mock
python -m agents.code_review.demo --mock
python -m agents.ecommerce.demo --mock
uvicorn agents.ecommerce.app:app --port 8000      # shopping UI at http://127.0.0.1:8000  (ECOM_MOCK=1 for offline)

python -m pytest tests -q     # 14 tests, offline
```

## How this was tested — read before grading

- `--mock` and the tests use **`common/scripted_llm.py`**: a subclass of ADK's `BaseLlm` that replays scripted tool calls
  and text. It is **not a language model**. It lets the real ADK runtime run offline: agent orchestration, tool calling,
  MCP sessions, state, callbacks, loops, subprocesses and databases are all exercised for real; only the model's choices are scripted.
- **No Gemini call was made while building this repo** (no API key in the build environment). Real-model runs are in the videos.
- Not exercised at all: Google Search grounding (`LEADGEN_SEARCH=google`), the real `gemini` binary (a stub stands in), the
  optional GitHub MCP server, and the Cloud Run Dockerfile.
- The lead-gen corpus, tickets and store catalogue are **synthetic** (invented companies and products).

## What each agent does

### a) Lead-generation deep research — `agents/lead_gen_research`
`icp_analyst` turns the request into a typed ideal-customer profile → three researchers run **in parallel** (market fit,
buying signals, tech stack) → an `evidence_critic` either calls `exit_loop` or lists gaps for `gap_filler` (max 2 rounds)
→ `lead_ranker` scores every candidate with a **deterministic rubric tool** (`score_lead`, 0–100) and saves a Markdown
report where every claim carries a source id. Sample: [`sample_output/lead_report.md`](agents/lead_gen_research/sample_output/lead_report.md).

### b) Gemini CLI as a tool — `agents/gemini_cli_agent`
`cli_operator` calls `prepare_repo` then `gemini_cli` (runs `gemini -p "<task>"` inside the repo); `report_writer`
answers from the CLI output only. The tool runs **without a shell** (the task is one argv element, so it cannot inject
commands), accepts only `https://github.com/owner/repo` URLs or an existing local directory, and has a timeout, an
output cap and a per-request call budget.

### c) MCP bug assistant — `agents/bug_assistant`
`tickets_mcp_server.py` is a real MCP server (stdio) with six tools over SQLite. The agent checks for duplicates before
filing, comments on the existing ticket when it finds one, and a `before_tool_callback` refuses to resolve/close a
ticket the user did not name.

### d) Code review assistant — `agents/code_review`
Review pipeline: AST analysis → style check → model-written tests **executed** in a subprocess → synthesis. Then a
`LoopAgent` (max 3) fixes, re-tests with the same tests, and exits only when they pass; a gate skips the loop for clean
code. In the sample run: 3 of 6 tests fail on the original, the first fix leaves 1 failing, the second passes all 6.

### e) E-commerce agent — `agents/ecommerce`
`store_mcp_server.py` exposes catalogue search (TF-IDF), cart, stores by distance with stock, delivery methods and orders.
The agent's `before_tool_callback` **overwrites `user_email` with the signed-in user** on every call and requires an
explicit confirmation in the user's message before `place_order` / `cancel_order`; state-changing calls go to an audit list.

## Differences from the reference codelabs

| Reference | Here | Why |
|---|---|---|
| AlloyDB + MCP Toolbox, vector search (e-commerce) | SQLite + own MCP server, TF-IDF search | runs anywhere with no cloud project; same agent ↔ MCP ↔ database shape |
| Postgres via MCP Toolbox, GitHub MCP (bug assistant) | SQLite via own MCP server; GitHub MCP optional | same reason |
| `gemini -p` via `shell=True` (Gemini CLI) | argv list, no shell, URL allow-list | a model-written string must not reach a shell |
| Google Search for lead research | synthetic corpus by default, Google Search by flag | reproducible offline demo |

## Limits

- Test and CLI subprocesses are isolated by temp dir, timeout and a stripped environment — not an OS sandbox.
- `prepare_repo` accepts any local directory; restrict it before deploying as a service.
- The shopping UI's sign-in is simulated (pick a demo user). Production needs a verified identity token.
- Sessions are in memory; a deployment would use a persistent ADK session service.

References studied: Google Cloud blog posts and codelabs linked in the assignment, `MagnIeeT/leadGenerationAgentADK`,
`derrickchwong/gemini-cli-on-adk`, `google/adk-samples` (software-bug-assistant), `ayoisio/adk-code-review-assistant`,
`mtoscano84/sports-agent-adk-mcp-alloydb`.
