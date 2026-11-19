"""python -m agents.code_review.demo [--mock] [file.py]"""
import sys
from pathlib import Path

from common.run import run
from .agent import build_agent

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    code = Path(args[0] if args else Path(__file__).parent / "sample_buggy.py").read_text()
    if "--mock" in sys.argv:
        from common.scripted_llm import scripted
        from .mock_script import SCRIPT
        print("[mock] scripted model — analysis, style check, test execution and the fix loop are real\n")
        agent = build_agent(model=scripted(SCRIPT))
    else:
        agent = build_agent()
    r = run(agent, f"Please review this:\n```python\n{code}```", verbose=True)
    s = r["state"]
    print(f"\ntests before: {s['tests_original']['passed']} passed / {s['tests_original']['failed']} failed · after: {(s.get('tests_fixed') or {}).get('passed')} passed / {(s.get('tests_fixed') or {}).get('failed')} failed · fix attempts: {s.get('fix_attempts')}")
