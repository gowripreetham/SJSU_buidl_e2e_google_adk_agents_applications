"""python -m agents.ecommerce.demo [--mock] ["message" …]"""
import sys
import tempfile

from common.run import run
from .agent import build_agent

USER = {"user_email": "alex@example.com", "user_name": "Alex"}
if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--mock" in sys.argv:
        from common.scripted_llm import scripted
        from .mock_script import SCRIPT, TURNS
        print("[mock] scripted model — MCP server, database, identity guard and confirmation gate are real\n")
        r = run(build_agent(model=scripted(SCRIPT), db_path=tempfile.mktemp(suffix=".db")), TURNS, state=USER, verbose=True)
        print("\naudit:", r["state"].get("audit"))
    else:
        run(build_agent(), args or ["I need waterproof shoes for trail running."], state=USER, verbose=True)
