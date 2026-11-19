"""python -m agents.gemini_cli_agent.demo [--mock] ["request naming a repo"]"""
import os
import sys
from pathlib import Path

from common.run import run
from .agent import build_agent

if __name__ == "__main__":
    here = Path(__file__).parent
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ask = args[0] if args else f"Explain the codebase at {here / 'sample_repo'} and draft a test plan."
    if "--mock" in sys.argv:
        from common.scripted_llm import scripted
        from .mock_script import SCRIPT
        os.environ["GEMINI_CLI_BIN"] = str(here / "stub/gemini")
        print("[mock] scripted model + stub gemini binary — the subprocess call is real\n")
        agent = build_agent(model=scripted(SCRIPT))
    else:
        agent = build_agent()
    run(agent, ask, verbose=True)
