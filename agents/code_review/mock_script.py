"""Scripted model turns for the offline demo/test (not an LLM). AST analysis, style checks, test execution and the
loop/gate logic are real; the first scripted fix is deliberately incomplete so the fix loop has to go round twice."""
from pathlib import Path

from common.scripted_llm import call

BUGGY = (Path(__file__).parent / "sample_buggy.py").read_text()
TESTS = ["assert averageScore([2, 4]) == 3", "assert averageScore([1, 3], [1, 3]) == 2.5", "assert averageScore([]) == 0", "assert find_max([3, 9, 2]) == 9",
         "assert find_max([-5, -2]) == -2", "assert find_max([]) is None"]
FIX1 = '''def averageScore(scores, weights=None):
    """Weighted mean of scores; unweighted when no weights are given."""
    if not scores:
        return 0
    weights = weights or [1] * len(scores)
    return sum(s * w for s, w in zip(scores, weights)) / sum(weights)


def find_max(items):
    """Largest item."""
    best = items[0]
    for x in items:
        if x > best:
            best = x
    return best
'''
FIX2 = FIX1.replace('    """Largest item."""\n    best = items[0]', '    """Largest item, or None for an empty sequence."""\n    if not items:\n        return None\n    best = items[0]')


def tests_summary(c):
    r = c.results("run_python_tests")[-1]
    fails = "; ".join(f"`{x['test']}` → {x['error']}" for x in r["results"] if not x["ok"])
    return f"{r['passed']} passed, {r['failed']} failed. Failures: {fails or 'none'}"


SCRIPT = {
    "code_analyzer": [call("analyze_code_structure", which="original"),
                      lambda c: "Two helpers: a weighted average and a max finder. Issues: " + "; ".join(f"line {i['line']} {i['kind']} — {i['detail']}" for i in c.last_tool["issues"])],
    "style_checker": [call("check_style", which="original"), lambda c: f"Style score {c.last_tool['score']}/100: " + "; ".join(f"{v['rule']} line {v['line']} {v['detail']}" for v in c.last_tool["violations"])],
    "test_runner": [call("run_python_tests", which="original", tests=TESTS), tests_summary],
    "feedback_synthesizer": ["Verdict: needs changes. Bugs: weighted average divides by the count instead of the sum of weights (line 6); empty list raises ZeroDivisionError (line 6); "
                             "find_max([]) returns 0 instead of None because a bare except swallows IndexError (line 16). Risks: mutable default argument (line 1), comparison to None with != (line 4). "
                             "Style: averageScore is not snake_case; both functions lack docstrings."],
    "code_fixer": [call("submit_fix", code=FIX1, explanation="Weights default to None; divide by the sum of weights; guard empty input; removed the bare except."), "Fix 1 submitted.",
                   call("submit_fix", code=FIX2, explanation="find_max returns None for an empty sequence."), "Fix 2 submitted."],
    "fix_tester": [[call("run_python_tests", which="fixed", tests=TESTS), call("check_style", which="fixed"), call("analyze_code_structure", which="fixed")], tests_summary] * 2,
    "fix_validator": ["Still failing: find_max([]) raises IndexError — it must return None for an empty sequence.", call("exit_loop")],
    "fix_reporter": ["Review: weighted average used the wrong denominator, empty inputs crashed or returned a misleading 0, and a bare except hid the error. "
                     "Fixed in two rounds — all 6 tests pass on the fix (3 failed originally). The public name averageScore was kept so callers do not break; renaming it to snake_case is a follow-up."],
}
