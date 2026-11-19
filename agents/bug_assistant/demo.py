"""python -m agents.bug_assistant.demo [--mock] ["message" …]"""
import sys
import tempfile

from common.run import run
from .agent import build_agent

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--mock" in sys.argv:
        from common.scripted_llm import scripted
        from .mock_script import SCRIPT, TURNS
        print("[mock] scripted model — the MCP server, database and guard are real\n")
        run(build_agent(model=scripted(SCRIPT), db_path=tempfile.mktemp(suffix=".db")), TURNS, verbose=True)
    else:
        run(build_agent(), args or ["What auth bugs are open?"], verbose=True)
