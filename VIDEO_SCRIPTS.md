# Video scripts — Assignment 3 (one video per agent, ≈5 min each)

**[SCREEN]** = what to show; plain text = what to say. Before recording: `.env` with your Gemini key, `pip install -r requirements.txt`,
`npm i -g @google/gemini-cli` (video b). Run each command once beforehand. Paste the five links into `README.md`.
Show each agent twice: in the terminal (`python -m agents.<name>.demo`, **without** `--mock`) and in `adk web agents` to see the event trace.

## a) Lead-generation deep research
- **0:00** [README diagram] "A deep-research agent for B2B lead generation on Google ADK. It plans, researches in parallel, criticises its own evidence, then ranks leads."
- **0:25** [`agent.py`, top docstring then `build_agent`] "The root is a SequentialAgent. Step one, `icp_analyst`, has an `output_schema` — a Pydantic ICP — written to state under `icp`. Every later instruction pulls it in with `{icp}`."
- **1:10** [ParallelAgent block] "Three researchers run concurrently, each writing its own `output_key`. That's the fan-out."
- **1:35** [LoopAgent block] "Deep research means checking yourself. The critic either calls `exit_loop` or lists missing facts; the gap filler researches only those. Max two rounds."
- **2:05** [`tools.py`: `search_companies`, `score_lead`, `save_report`] "Tools: search over a synthetic corpus — or Google Search with one flag — and `score_lead`, a deterministic rubric. The model never invents a score."
- **2:45** [RUN `python -m agents.lead_gen_research.demo`] narrate: ICP → three researchers → critic → gap → scoring → report. [Open `out/lead_report.md`] "Every claim has a source id; rejected companies are listed with the reason."
- **4:00** [RUN `LEADGEN_SEARCH=google adk web agents`, pick lead_gen_research, show the Events tab] "Same pipeline on live Google Search."
- **4:40** [RUN `pytest tests -q -k lead`] "Tests use a scripted model so the orchestration is checked offline."

## b) Gemini CLI as a tool
- **0:00** "Here the ADK agent's tool is another agent: the Gemini CLI, run as a subprocess."
- **0:20** [`tools.py`: `gemini_cli`] "It runs `gemini -p task` inside the repo. Three safety choices: no shell — the task is a single argv element; a GitHub-URL allow-list for cloning; timeout and output cap."
- **1:20** [`agent.py`] "`cli_operator` owns the tool and a `before_tool_callback` budget. `report_writer` has no tools and answers only from `{cli_findings}`."
- **2:00** [RUN `gemini --version`; then `python -m agents.gemini_cli_agent.demo "Explain https://github.com/<a small repo> and draft a test plan"`] narrate prepare_repo → CLI calls → report.
- **3:30** [`tests/test_agents.py::test_gemini_cli_tool_is_injection_safe_and_bounded`, RUN it] "This test passes a task containing `; touch file` and `$(…)` and proves nothing executes."
- **4:10** [`Dockerfile`] "For Cloud Run, the image installs Node, the CLI and ADK's API server. I haven't deployed it in this repo."

## c) MCP bug assistant
- **0:00** "A bug-triage assistant whose tools come from an MCP server."
- **0:20** [`tickets_mcp_server.py`] "A real MCP server over stdio: six tools on SQLite, parameterised SQL, validated status and priority."
- **1:10** [`agent.py`: `McpToolset`, `confirm_closing`] "`McpToolset` launches the server and exposes its tools next to a normal Python tool. The guard refuses to close a ticket the user didn't name."
- **1:50** [RUN `python -m agents.bug_assistant.demo "PDF invoices render blank in Safari 18" "Login returns 500 right after I reset my password" "What auth bugs are open?" "Clean up the old tickets" "Mark ticket 4 as resolved"`] narrate: new ticket; duplicate detected → comment; search; refusal; allowed update.
- **3:40** [`sqlite3 agents/bug_assistant/tickets.db "select id,title,status from tickets"`] "The database agrees with the conversation."
- **4:10** [adk web, Events tab showing MCP tool calls] · [RUN `pytest -q -k "bug or ticket"`]

## d) Code review assistant
- **0:00** "A code reviewer that doesn't just comment — it runs tests and verifies its own fix."
- **0:20** [`agent.py` docstring] walk the two stages: review pipeline, fix loop.
- **0:50** [`tools.py`] "`analyze_code_structure` uses the AST; `check_style` is a PEP 8 subset; `run_python_tests` executes the model's asserts in a temp dir with a timeout and no inherited environment. Tools read the code from session state, so the model can't mis-copy it."
- **1:50** [`agent.py`: `capture_submission`, `skip_if_clean`, LoopAgent] "Callbacks: one captures and size-limits the submission, one skips the fix loop for clean code. The loop is capped at three."
- **2:30** [show `sample_buggy.py`; RUN `python -m agents.code_review.demo`] narrate failing tests → review → fix → re-test → exit_loop → final report with before/after.
- **4:20** [RUN `pytest -q -k code_review`]

## e) E-commerce agent
- **0:00** "A shopping agent: ADK agent, MCP tool server, database, web UI."
- **0:20** [`store_mcp_server.py`] "Ten tools over SQLite — search, details, cart, stores by distance with stock, delivery, orders. This stands in for AlloyDB plus MCP Toolbox in the codelab."
- **1:10** [`agent.py`: `enforce_identity`, `audit`] "Three things live in code, not in the prompt: the user's email is overwritten from the session on every call; orders need an explicit confirmation; state changes are audited."
- **2:00** [RUN `uvicorn agents.ecommerce.app:app --port 8000`, open the UI] search → add to cart → nearest store and delivery → "order it" (blocked, asks to confirm) → "yes, confirm" → "show my orders". Switch user to Sam: empty cart, no orders.
- **4:00** [`tests/test_agents.py::test_ecommerce_identity_confirmation_and_order`] "The test has the scripted model pass someone else's email; the order still lands on the signed-in user."
- **4:30** "Limits: sign-in is simulated here; production needs a verified ID token and a persistent session service."
