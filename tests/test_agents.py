"""Offline tests. The model is scripted (common/scripted_llm.py); ADK orchestration, tools, MCP servers, subprocesses,
databases and guards are real."""
import json
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.run import run  # noqa: E402
from common.scripted_llm import call, scripted  # noqa: E402

ctx = lambda **state: SimpleNamespace(state=dict(state))  # noqa: E731  (a stand-in ToolContext for calling tools directly)


# ---------------------------------------------------------------- a) lead generation
def test_lead_gen_pipeline_end_to_end():
    from agents.lead_gen_research.agent import build_agent
    from agents.lead_gen_research.mock_script import SCRIPT
    model = scripted(SCRIPT)
    r = run(build_agent(model=model), "Find logistics leads in North America")
    agents = [a for a, _ in model.log]
    assert agents[0] == "icp_analyst" and agents[-1] == "lead_ranker"
    assert agents.count("evidence_critic") == 2 and agents.count("gap_filler") == 2          # the loop went round, then exit_loop ended it
    assert set(agents[1:4]) <= {"market_scout", "signal_hunter", "stack_analyst"}            # fan-out ran before the critic
    s = r["state"]
    assert s["icp"]["industries"] == ["logistics"]
    assert s["scores"]["Northwind Freight"]["score"] == 100 and s["scores"]["Granite Peak Freight"]["tier"] == "C"
    assert s["scores"]["Cobalt Yard Logistics"]["score"] == 70                                 # right industry and size, wrong region
    report = Path(s["report_path"]).read_text()
    assert "corpus://northwind-freight#signal-" in report and "## Rejected" in report and "Granite Peak Freight" in report


def test_score_lead_rubric_is_deterministic():
    from agents.lead_gen_research.tools import score_lead, search_companies
    icp = {"industries": ["logistics"], "min_employees": 200, "max_employees": 2000, "regions": ["North America"], "buying_signals": ["hiring", "funding"], "tech_keywords": ["Snowflake"]}
    c = ctx(icp=icp)
    assert score_lead("X", "logistics", 500, "North America", ["hiring", "funding", "expansion"], ["Snowflake"], c)["score"] == 90
    assert score_lead("Y", "banking", 50, "Europe", [], [], c)["score"] == 0
    assert search_companies("zzzz-no-match") == [] and search_companies("logistics Snowflake")[0]["name"] in ("Northwind Freight", "Skylark Parcel")


# ---------------------------------------------------------------- b) Gemini CLI as a tool
@pytest.fixture
def stub_cli(monkeypatch):
    monkeypatch.setenv("GEMINI_CLI_BIN", str(ROOT / "agents/gemini_cli_agent/stub/gemini"))
    return str(ROOT / "agents/gemini_cli_agent/sample_repo")


def test_gemini_cli_pipeline(stub_cli):
    from agents.gemini_cli_agent.agent import build_agent
    from agents.gemini_cli_agent.mock_script import SCRIPT
    r = run(build_agent(model=scripted(SCRIPT)), "Explain the sample repo")
    assert [t[1] for t in r["tool_calls"]] == ["prepare_repo", "gemini_cli", "gemini_cli"]
    assert "class Inventory" in r["state"]["cli_findings"] and r["state"]["cli_calls"] == 2
    assert r["authors"][-1] == "report_writer"


def test_gemini_cli_tool_is_injection_safe_and_bounded(stub_cli, tmp_path, monkeypatch):
    from agents.gemini_cli_agent import tools as T
    marker = tmp_path / "pwned"
    c = ctx(repo_dir=stub_cli)
    out = T.gemini_cli(f'explain"; touch {marker}; echo "$(touch {marker})', c)
    assert out["exit_code"] == 0 and not marker.exists()                       # the task is one argv element, never a shell string
    assert "error" in T.gemini_cli("explain", ctx())                           # no repo prepared
    assert T.gemini_cli("fail-now", c)["exit_code"] == 3
    monkeypatch.setenv("GEMINI_CLI_TIMEOUT", "1")
    assert T.gemini_cli("sleep-forever", c) == {"error": "Gemini CLI timed out"}
    for bad in ("http://github.com/a/b", "https://evil.example/a/b", "https://github.com/a/b; rm -rf ~", "git@github.com:a/b.git", str(tmp_path / "missing")):
        assert "error" in T.prepare_repo(bad, ctx())


def test_gemini_cli_budget_guard(stub_cli):
    from agents.gemini_cli_agent.agent import MAX_CLI_CALLS, build_agent
    script = {"cli_operator": [call("prepare_repo", source=stub_cli)] + [call("gemini_cli", task=f"q{i}") for i in range(MAX_CLI_CALLS + 2)] + ["done"], "report_writer": ["ok"]}
    r = run(build_agent(model=scripted(script)), "go")
    assert r["state"]["cli_calls"] == MAX_CLI_CALLS
    assert sum("budget" in str(res) for _, res in r["tool_results"]) == 2


# ---------------------------------------------------------------- c) MCP bug assistant
def test_bug_assistant_over_mcp(tmp_path):
    from agents.bug_assistant.agent import build_agent
    from agents.bug_assistant.mock_script import SCRIPT, TURNS
    dbp = str(tmp_path / "t.db")
    r = run(build_agent(model=scripted(SCRIPT), db_path=dbp), TURNS)
    assert "Created ticket #8" in r["replies"][0] and "existing ticket #1" in r["replies"][1]
    assert "#1" in r["replies"][2] and "#5" in r["replies"][2] and "#6" not in r["replies"][2]      # #6 is auth but resolved
    assert "Refused" in r["replies"][3] and "resolved" in r["replies"][4]
    con = sqlite3.connect(dbp)
    assert con.execute("SELECT count(*) FROM tickets").fetchone()[0] == 8
    assert con.execute("SELECT status FROM tickets WHERE id = 2").fetchone()[0] == "open"            # the guard stopped the unrequested close
    assert con.execute("SELECT status FROM tickets WHERE id = 4").fetchone()[0] == "resolved"
    assert con.execute("SELECT count(*) FROM comments WHERE ticket_id = 1").fetchone()[0] == 1


def test_ticket_server_validation(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKETS_DB", str(tmp_path / "v.db"))
    import importlib
    import agents.bug_assistant.tickets_mcp_server as S
    S = importlib.reload(S)
    assert "error" in S.create_ticket("Valid title here", "long enough description", priority="URGENT")
    assert "error" in S.update_ticket_status(1, "deleted") and "error" in S.get_ticket(999)
    assert S.search_tickets("x'; DROP TABLE tickets;--") == [] and len(S.search_tickets()) == 7     # parameterised: the table survives
    assert S.find_similar_tickets("login 500 after password reset")[0]["id"] == 1


# ---------------------------------------------------------------- d) code review
def test_code_review_finds_bugs_and_verifies_fix():
    from agents.code_review.agent import build_agent
    from agents.code_review.mock_script import BUGGY, SCRIPT
    model = scripted(SCRIPT)
    s = run(build_agent(model=model), f"Review:\n```python\n{BUGGY}```")["state"]
    assert (s["tests_original"]["passed"], s["tests_original"]["failed"]) == (3, 3)
    assert {i["kind"] for i in s["structure_original"]["issues"]} == {"mutable-default", "bare-except", "none-comparison"}
    assert s["fix_attempts"] == 2 and s["tests_fixed"]["failed"] == 0 and s["style_fixed"]["score"] > s["style_original"]["score"]
    assert [a for a, _ in model.log].count("fix_validator") == 2


def test_code_review_skips_fix_loop_for_clean_code():
    from agents.code_review.agent import build_agent
    clean = 'def add(a, b):\n    """Sum of a and b."""\n    return a + b\n'
    script = {"code_analyzer": [call("analyze_code_structure", which="original"), "fine"], "style_checker": [call("check_style", which="original"), "fine"],
              "test_runner": [call("run_python_tests", which="original", tests=["assert add(2, 3) == 5", "assert add(-1, 1) == 0"]), "2 passed"],
              "feedback_synthesizer": ["Verdict: approve."], "fix_reporter": ["Approved, no changes."]}
    model = scripted(script)
    r = run(build_agent(model=model), f"```python\n{clean}```")
    assert "code_fixer" not in [a for a, _ in model.log] and r["state"].get("fixed_code") is None and r["replies"][0] == "Approved, no changes."


def test_code_review_tools_and_input_guard():
    from agents.code_review import tools as T
    from agents.code_review.agent import build_agent
    c = ctx(code="while True:\n    pass\n")
    assert "timed out" in T.run_python_tests("original", ["assert True"], c)["error"]
    assert T.run_python_tests("original", ["assert True"], ctx(code="def f(:\n"))["load_error"].startswith("SyntaxError")
    assert "syntax_error" in T.analyze_code_structure("original", ctx(code="def f(:\n"))
    assert "error" in T.submit_fix("def f(:", "x", ctx())
    secret = T.run_python_tests("original", ["import os; assert 'GEMINI_API_KEY' not in os.environ and 'HOME' not in os.environ"], ctx(code="x = 1\n"))
    assert secret["passed"] == 1                                               # the test subprocess does not inherit the environment
    r = run(build_agent(model=scripted({})), "x" * 30_000)
    assert "up to" in r["replies"][0]                                          # oversize input never reaches a model


# ---------------------------------------------------------------- e) e-commerce
def test_ecommerce_identity_confirmation_and_order(tmp_path):
    from agents.ecommerce.agent import build_agent
    from agents.ecommerce.mock_script import SCRIPT, TURNS
    dbp = str(tmp_path / "s.db")
    r = run(build_agent(model=scripted(SCRIPT), db_path=dbp), TURNS, state={"user_email": "alex@example.com", "user_name": "Alex"})
    assert "Trailblazer GTX" in r["replies"][0] and "Sprint Shorts" not in r["replies"][0]
    assert "Shall I confirm" in r["replies"][3] and "Order #1 is confirmed" in r["replies"][4] and "$151.99" in r["replies"][4]
    con = sqlite3.connect(dbp)
    assert con.execute("SELECT user_email, total, status FROM orders").fetchall() == [("alex@example.com", 151.99, "confirmed")]   # not someone-else@…
    assert con.execute("SELECT count(*) FROM cart").fetchone()[0] == 0
    assert [a["tool"] for a in r["state"]["audit"]] == ["add_to_cart", "place_order"]                                              # the blocked attempt is not audited as done


def test_ecommerce_refuses_when_not_signed_in(tmp_path):
    from agents.ecommerce.agent import build_agent
    script = {"shop_assistant": [call("show_cart", user_email="alex@example.com"), lambda c: str(c.last_tool)]}
    r = run(build_agent(model=scripted(script), db_path=str(tmp_path / "s.db")), "show my cart")
    assert "Nobody is signed in" in r["replies"][0]


def test_store_server_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_DB", str(tmp_path / "r.db"))
    import importlib
    import agents.ecommerce.store_mcp_server as S
    S = importlib.reload(S)
    assert S.search_products("yoga mat")[0]["name"] == "Flex Yoga Mat 5mm" and S.search_products("shoes", max_price=120)[0]["name"] == "Cloudstride 3"
    assert "error" in S.add_to_cart("alex@example.com", "Cloudstride 3", "99", "Black") and "error" in S.add_to_cart("ghost@example.com", "Cloudstride 3", "40", "Black")
    assert "error" in S.place_order("alex@example.com", "Palo Alto", "Express Delivery")                  # empty cart
    S.add_to_cart("alex@example.com", "Cloudstride 3", "40", "Black", 2)
    o = S.place_order("alex@example.com", "Palo Alto", "Store Pickup")
    assert o["total"] == 238.0
    assert "error" in S.cancel_order("sam@example.com", o["order_id"])                                    # someone else's order
    assert S.cancel_order("alex@example.com", o["order_id"])["status"] == "cancelled" and "error" in S.cancel_order("alex@example.com", o["order_id"])
    assert S.find_nearby_stores("alex@example.com")[0]["store"] == "Downtown San Jose"


def test_ecommerce_http_api(tmp_path, monkeypatch):
    monkeypatch.setenv("ECOM_MOCK", "1"); monkeypatch.setenv("STORE_DB", str(tmp_path / "api.db"))
    from fastapi.testclient import TestClient
    import agents.ecommerce.app as A
    A._runner, A._sessions = None, {}
    with TestClient(A.app) as c:
        assert "Sports store assistant" in c.get("/").text and len(c.get("/api/users").json()) == 2
        assert c.post("/api/chat", json={"user": "mallory@example.com", "message": "hi"}).status_code == 401
        d = c.post("/api/chat", json={"user": "alex@example.com", "message": "waterproof trail shoes under 150"}).json()
        assert "Trailblazer GTX" in d["reply"] and d["tools"][0]["name"] == "search_products"
