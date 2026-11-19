"""Tools for the lead-generation research agent.

Offline mode searches a bundled SYNTHETIC corpus (data/companies.json — invented companies, clearly not real data), so the
whole pipeline is reproducible without a key. With search="google" the researchers use ADK's built-in google_search instead;
score_lead and save_report are the same in both modes.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

from google.adk.tools import ToolContext

HERE = Path(__file__).parent
COMPANIES = json.loads((HERE / "data/companies.json").read_text())
OUT = HERE / "out"


def _find(name: str) -> dict | None:
    key = name.strip().lower()
    return next((c for c in COMPANIES if c["name"].lower() == key or c["slug"] == key or key in c["name"].lower()), None)


def search_companies(query: str, max_results: int = 5) -> list[dict]:
    """Search the company corpus. Matches words in the query against industry, location, tech stack and news signals.

    Args:
        query: keywords, e.g. "logistics hiring data engineers Snowflake".
        max_results: how many companies to return.
    Returns:
        A ranked list of {name, industry, hq, employees, why_matched, source}.
    """
    words = set(re.findall(r"[a-z0-9]+", query.lower())) - {"the", "and", "of", "in", "for", "a", "with", "companies", "company"}
    hits = []
    for c in COMPANIES:
        blob = " ".join([c["name"], c["industry"], c["hq"], c["region"], c["funding_stage"], *c["tech_stack"], *(s["type"] + " " + s["text"] for s in c["signals"])]).lower()
        blob_words = set(re.findall(r"[a-z0-9]+", blob))             # whole-word match: "no" must not match "Northwind"
        matched = sorted(words & blob_words)
        if matched:
            hits.append((len(matched), {"name": c["name"], "industry": c["industry"], "hq": c["hq"], "employees": c["employees"], "why_matched": matched, "source": f"corpus://{c['slug']}"}))
    return [h for _, h in sorted(hits, key=lambda x: -x[0])[:max_results]]


def get_company_profile(name: str) -> dict:
    """Get the full profile of one company: size, region, funding stage, tech stack and the roles that usually buy.

    Args:
        name: company name.
    """
    c = _find(name)
    return {k: c[k] for k in ("name", "industry", "hq", "region", "employees", "funding_stage", "tech_stack", "decision_roles")} | {"source": f"corpus://{c['slug']}"} if c else {"error": f"no company named '{name}'"}


def find_signals(name: str, signal_type: str = "") -> list[dict]:
    """List recent buying signals for a company (hiring, funding, tech_change, expansion, leadership, compliance), each with a date and a source id.

    Args:
        name: company name.
        signal_type: optional filter, e.g. "hiring".
    """
    c = _find(name)
    return [s for s in c["signals"] if not signal_type or s["type"] == signal_type] if c else []


def score_lead(company: str, industry: str, employees: int, region: str, signal_types: list[str], tech_stack: list[str], tool_context: ToolContext) -> dict:
    """Score a lead from 0 to 100 against the ideal customer profile stored in session state. Deterministic rubric — always use this, never invent a score.

    Args:
        company: company name.
        industry: the company's industry.
        employees: head count.
        region: e.g. "North America".
        signal_types: types of buying signals found, e.g. ["hiring", "funding"].
        tech_stack: technologies the company uses.
    """
    icp = tool_context.state.get("icp") or {}
    if isinstance(icp, str):
        icp = json.loads(icp)
    points, why = 0, []
    if any(k.lower() in industry.lower() for k in icp.get("industries", [])):
        points += 30; why.append("industry fits (+30)")
    if icp.get("min_employees", 0) <= employees <= icp.get("max_employees", 10**9):
        points += 20; why.append("size in range (+20)")
    if not icp.get("regions") or any(r.lower() in region.lower() for r in icp["regions"]):
        points += 10; why.append("region fits (+10)")
    hit = sorted(set(signal_types) & set(icp.get("buying_signals", [])))
    if hit:
        points += min(30, 10 * len(hit)); why.append(f"signals {hit} (+{min(30, 10 * len(hit))})")
    tech = sorted({t.lower() for t in tech_stack} & {t.lower() for t in icp.get("tech_keywords", [])})
    if tech:
        points += 10; why.append(f"stack overlap {tech} (+10)")
    result = {"company": company, "score": points, "tier": "A" if points >= 80 else "B" if points >= 60 else "C", "reasons": why}
    tool_context.state["scores"] = {**tool_context.state.get("scores", {}), company: result}
    return result


def save_report(markdown: str, tool_context: ToolContext) -> dict:
    """Save the final lead report (Markdown) to disk.

    Args:
        markdown: the complete report.
    """
    OUT.mkdir(exist_ok=True)
    path = OUT / "lead_report.md"
    path.write_text(markdown)
    tool_context.state["report_path"] = str(path)
    return {"saved": str(path), "characters": len(markdown)}
