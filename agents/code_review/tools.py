"""Deterministic tools for the code-review assistant. The LLM reasons; these tools measure.

  analyze_code_structure   AST facts: functions, args, docstrings, complexity, risky constructs
  check_style              a small PEP 8 subset implemented here (no external linter needed)
  run_python_tests         runs model-written asserts against the code in a throw-away subprocess
All three read the submission from session state (the model never has to re-type the code), and store results in state.
"""
from __future__ import annotations
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from google.adk.tools import ToolContext

MAX_CODE = 20_000


def _code(ctx: ToolContext, which: str) -> str | None:
    return ctx.state.get("fixed_code" if which == "fixed" else "code")


def analyze_code_structure(which: str, tool_context: ToolContext) -> dict:
    """Parse the submitted Python code and report its structure and risky constructs.

    Args:
        which: "original" for the user's submission or "fixed" for the latest fix.
    """
    code = _code(tool_context, which)
    if not code:
        return {"error": "no code in session"}
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return {"syntax_error": f"line {e.lineno}: {e.msg}"}
    functions, issues = [], []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            branches = sum(isinstance(n, (ast.If, ast.For, ast.While, ast.Try, ast.BoolOp, ast.ExceptHandler)) for n in ast.walk(node))
            functions.append({"name": node.name, "line": node.lineno, "args": [a.arg for a in node.args.args], "has_docstring": ast.get_docstring(node) is not None,
                              "complexity": 1 + branches, "lines": (node.end_lineno or node.lineno) - node.lineno + 1})
            for d in node.args.defaults:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    issues.append({"line": node.lineno, "kind": "mutable-default", "detail": f"{node.name}() has a mutable default argument"})
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append({"line": node.lineno, "kind": "bare-except", "detail": "bare `except:` hides every error"})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
            issues.append({"line": node.lineno, "kind": "dangerous-call", "detail": f"{node.func.id}() on dynamic input"})
        if isinstance(node, ast.Compare) and any(isinstance(o, (ast.Eq, ast.NotEq)) for o in node.ops) and any(isinstance(c, ast.Constant) and c.value is None for c in node.comparators):
            issues.append({"line": node.lineno, "kind": "none-comparison", "detail": "compare to None with `is` / `is not`"})
    result = {"functions": functions, "classes": [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)], "issues": issues, "lines": len(code.splitlines())}
    tool_context.state[f"structure_{which}"] = result
    return result


def check_style(which: str, tool_context: ToolContext) -> dict:
    """Check the code against a PEP 8 subset: line length (>100), naming, missing docstrings, trailing whitespace, tabs, comparisons to True/False.

    Args:
        which: "original" or "fixed".
    """
    code = _code(tool_context, which)
    if not code:
        return {"error": "no code in session"}
    v = []
    for i, line in enumerate(code.splitlines(), 1):
        if len(line) > 100:
            v.append({"line": i, "rule": "E501", "detail": f"line is {len(line)} characters"})
        if line.rstrip() != line:
            v.append({"line": i, "rule": "W291", "detail": "trailing whitespace"})
        if "\t" in line:
            v.append({"line": i, "rule": "W191", "detail": "tab used for indentation"})
        if re.search(r"[=!]=\s*(True|False)\b", line):
            v.append({"line": i, "rule": "E712", "detail": "comparison to True/False"})
    try:
        for node in ast.walk(ast.parse(code)):
            if isinstance(node, ast.FunctionDef):
                if not re.fullmatch(r"_{0,2}[a-z][a-z0-9_]*_{0,2}", node.name):
                    v.append({"line": node.lineno, "rule": "N802", "detail": f"function name '{node.name}' should be snake_case"})
                if ast.get_docstring(node) is None and not node.name.startswith("_"):
                    v.append({"line": node.lineno, "rule": "D103", "detail": f"public function '{node.name}' has no docstring"})
            if isinstance(node, ast.ClassDef) and not re.fullmatch(r"[A-Z][A-Za-z0-9]*", node.name):
                v.append({"line": node.lineno, "rule": "N801", "detail": f"class name '{node.name}' should be CapWords"})
    except SyntaxError:
        pass
    result = {"violations": sorted(v, key=lambda x: x["line"]), "score": max(0, 100 - 5 * len(v))}
    tool_context.state[f"style_{which}"] = result
    return result


def run_python_tests(which: str, tests: list[str], tool_context: ToolContext) -> dict:
    """Run assert-style tests against the code in an isolated subprocess (temp dir, 10 s timeout, no inherited environment).

    Args:
        which: "original" or "fixed".
        tests: Python statements, one test each, e.g. "assert add(2, 3) == 5". Names defined by the code are in scope.
    Returns:
        {"passed": n, "failed": n, "results": [{"test": …, "ok": bool, "error": …}]}
    """
    code = _code(tool_context, which)
    if not code:
        return {"error": "no code in session"}
    if len(tests) > 30:
        return {"error": "at most 30 tests"}
    harness = ("import json\nns = {}\nresults = []\ntry:\n    exec(compile(open('submission.py').read(), 'submission.py', 'exec'), ns)\nexcept BaseException as e:\n"
               "    print(json.dumps({'load_error': f'{type(e).__name__}: {e}'})); raise SystemExit\n"
               "for t in json.load(open('tests.json')):\n    try:\n        exec(t, dict(ns)); results.append({'test': t, 'ok': True})\n"
               "    except BaseException as e:\n        results.append({'test': t, 'ok': False, 'error': f'{type(e).__name__}: {e}'[:200]})\nprint(json.dumps({'results': results}))\n")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "submission.py").write_text(code)
        Path(d, "tests.json").write_text(json.dumps(tests))
        Path(d, "harness.py").write_text(harness)
        try:
            r = subprocess.run([sys.executable, "-I", "harness.py"], cwd=d, capture_output=True, text=True, timeout=10, env={"PATH": os.environ.get("PATH", "")})
        except subprocess.TimeoutExpired:
            return {"error": "tests timed out after 10 s (possible infinite loop)"}
    try:
        data = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": f"test harness crashed: {r.stderr.strip()[-300:]}"}
    if "load_error" in data:
        result = {"passed": 0, "failed": len(tests), "load_error": data["load_error"], "results": []}
    else:
        result = {"passed": sum(x["ok"] for x in data["results"]), "failed": sum(not x["ok"] for x in data["results"]), "results": data["results"]}
    tool_context.state[f"tests_{which}"] = result
    tool_context.state["test_cases"] = tests
    return result


def submit_fix(code: str, explanation: str, tool_context: ToolContext) -> dict:
    """Submit a corrected version of the code. It will be re-analysed and re-tested by the next agents.

    Args:
        code: the complete fixed source file.
        explanation: one or two sentences on what changed.
    """
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"error": f"fix does not parse — line {e.lineno}: {e.msg}"}
    tool_context.state["fixed_code"] = code
    tool_context.state["fix_attempts"] = (tool_context.state.get("fix_attempts") or 0) + 1
    tool_context.state["fix_notes"] = [*(tool_context.state.get("fix_notes") or []), explanation]
    return {"accepted": True, "attempt": tool_context.state["fix_attempts"]}
