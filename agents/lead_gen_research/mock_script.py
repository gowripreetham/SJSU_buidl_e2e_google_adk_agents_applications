"""Scripted model turns for the offline demo/test of the lead-gen pipeline (see common/scripted_llm.py — not an LLM).
Only the *wording* is scripted; every company fact, signal, score and the saved report come from the real tools."""
import json

from common.scripted_llm import call

ICP = {"product": "shipment-visibility and ETA-prediction analytics", "industries": ["logistics"], "min_employees": 200, "max_employees": 2000,
       "regions": ["North America"], "buying_signals": ["hiring", "tech_change", "funding"], "tech_keywords": ["Snowflake", "Python", "Airflow"]}
SHORTLIST = ["Northwind Freight", "Skylark Parcel", "Tidewater Cold Chain", "Cobalt Yard Logistics", "Granite Peak Freight"]


def listing(c):
    return "\n".join(f"- {r['name']} — {r['industry']}, {r['hq']}, {r['employees']} employees [{r['source']}]" for r in c.last_tool) or "No companies found."


def signals_text(c):
    rows = [f"- {n}: {s['type']} ({s['date']}) — {s['text']} [{s['source']}]" for n, res in zip(SHORTLIST, c.results("find_signals")) for s in res]
    return "\n".join(rows) or "No signals found."


def stack_text(c):
    return "\n".join(f"- {p['name']}: {', '.join(p['tech_stack'])}; buyers: {', '.join(p['decision_roles'])} [{p['source']}]" for p in c.results("get_company_profile") if "name" in p)


def score_calls(c):
    profiles = {p["name"]: p for p in c.results("get_company_profile") if "name" in p}
    sigs = dict(zip(SHORTLIST, c.results("find_signals")))
    return [call("score_lead", company=n, industry=p["industry"], employees=p["employees"], region=p["region"],
                 signal_types=sorted({s["type"] for s in sigs.get(n, [])}), tech_stack=p["tech_stack"]) for n, p in profiles.items()]


def report(c):
    scores = sorted(c.results("score_lead"), key=lambda s: -s["score"])
    sigs = dict(zip(SHORTLIST, c.results("find_signals")))
    profiles = {p["name"]: p for p in c.results("get_company_profile") if "name" in p}
    md = ["# Lead report — shipment-visibility analytics", "", "| # | Company | Score | Tier | Why now |", "|---|---|---|---|---|"]
    for i, s in enumerate(scores, 1):
        top = sigs[s["company"]][0] if sigs.get(s["company"]) else None
        md.append(f"| {i} | {s['company']} | {s['score']} | {s['tier']} | {top['text'] + ' [' + top['source'] + ']' if top else '—'} |")
    for s in scores:
        if s["tier"] in "AB":
            p = profiles[s["company"]]
            md += ["", f"## {s['company']} — {s['score']} ({s['tier']})", f"- Fit: {'; '.join(s['reasons'])}", f"- Contact role: {p['decision_roles'][0]}",
                   *[f"- Evidence: {x['text']} ({x['date']}) [{x['source']}]" for x in sigs[s['company']]],
                   f"- Opening angle: reference “{sigs[s['company']][0]['text'].lower()}” and offer an ETA-accuracy benchmark."]
    md += ["", "## Rejected", *[f"- {s['company']}: score {s['score']} — {'; '.join(s['reasons']) or 'no ICP criteria met'}" for s in scores if s["tier"] == "C"]]
    return call("save_report", markdown="\n".join(md))


def table(c):
    scores = sorted(c.results("score_lead"), key=lambda s: -s["score"])
    return "Ranked leads:\n" + "\n".join(f"{i}. {s['company']} — {s['score']} (tier {s['tier']})" for i, s in enumerate(scores, 1)) + f"\nReport saved to {c.results('save_report')[-1]['saved']}"


SCRIPT = {
    "icp_analyst": [json.dumps(ICP)],
    "market_scout": [call("search_companies", query="logistics North America freight parcel", max_results=6), listing],
    "signal_hunter": [[call("find_signals", name=n) for n in SHORTLIST], signals_text],
    "stack_analyst": [[call("get_company_profile", name=n) for n in SHORTLIST], stack_text],
    "evidence_critic": ["Missing head count and region check for: Cobalt Yard Logistics (is it in North America?)", call("exit_loop")],
    "gap_filler": [call("get_company_profile", name="Cobalt Yard Logistics"),
                   lambda c: f"Cobalt Yard Logistics: {c.last_tool['employees']} employees, HQ {c.last_tool['hq']}, region {c.last_tool['region']} [{c.last_tool['source']}] — outside the ICP's region."],
    "lead_ranker": [[call("get_company_profile", name=n) for n in SHORTLIST] + [call("find_signals", name=n) for n in SHORTLIST], score_calls, report, table],
}
