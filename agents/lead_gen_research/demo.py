"""python -m agents.lead_gen_research.demo [--mock] ["your request"]"""
import sys

from common.run import run
from .agent import build_agent

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ask = args[0] if args else "We sell shipment-visibility and ETA-prediction analytics to mid-size logistics companies in North America. Find me leads."
    if "--mock" in sys.argv:
        from common.scripted_llm import scripted
        from .mock_script import SCRIPT
        print("[mock] scripted model — tool results, scores and the report are real\n")
        agent = build_agent(model=scripted(SCRIPT))
    else:
        agent = build_agent(search="google" if "--google" in sys.argv else "local")
    r = run(agent, ask, verbose=True)
    print("\nreport:", r["state"].get("report_path"))
