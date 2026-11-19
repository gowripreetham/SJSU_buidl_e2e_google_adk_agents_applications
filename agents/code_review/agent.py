"""Code-review assistant on Google ADK.

    code_review_assistant (SequentialAgent)
      review_pipeline (SequentialAgent)
        code_analyzer        tool analyze_code_structure        → state["structure_original"], output "analysis"
        style_checker        tool check_style                   → state["style_original"],     output "style"
        test_runner          writes tests, tool run_python_tests → state["tests_original"],    output "test_report"
        feedback_synthesizer no tools — prioritised review from the three reports               output "review"
      fix_loop (LoopAgent, max 3 rounds) — skipped by the gate when the review found nothing to fix
        code_fixer           tool submit_fix                    → state["fixed_code"]
        fix_tester           tool run_python_tests on the fix (same tests) + check_style
        fix_validator        calls exit_loop when all tests pass, otherwise says what still fails
      fix_reporter           final message: review, the fix, before/after numbers

Production touches: the submission is captured into state by a before_agent_callback (size-limited, code-fence aware),
tools read code from state instead of trusting the model to re-type it, tests run in a subprocess sandbox, the loop is
bounded, and a gate callback skips the fix loop when there is nothing to fix.
"""
from __future__ import annotations
import os
import re

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import exit_loop
from google.genai import types

from . import tools as T

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")


def capture_submission(callback_context: CallbackContext):
    """before_agent_callback on the root: pull the code out of the user's message into state; refuse oversize or empty input."""
    text = " ".join(p.text or "" for p in (callback_context.user_content.parts if callback_context.user_content else []))
    m = re.search(r"```(?:python|py)?\n(.*?)```", text, re.S)
    code = (m.group(1) if m else text).strip()
    if not code or len(code) > T.MAX_CODE:
        return types.Content(role="model", parts=[types.Part(text=f"Please paste Python code to review (up to {T.MAX_CODE} characters).")])
    for k in ("fixed_code", "fix_attempts", "fix_notes", "tests_fixed", "style_fixed"):
        callback_context.state[k] = None
    callback_context.state["code"] = code
    return None


def skip_if_clean(callback_context: CallbackContext):
    """before_agent_callback on the fix loop: returning content skips the agent."""
    s = callback_context.state
    tests, structure, style = s.get("tests_original") or {}, s.get("structure_original") or {}, s.get("style_original") or {}
    if not tests.get("failed") and not structure.get("issues") and not structure.get("syntax_error") and not style.get("violations"):
        return types.Content(role="model", parts=[types.Part(text="No fixes needed.")])
    return None


def build_agent(model=None) -> SequentialAgent:
    m = model or MODEL
    analyzer = LlmAgent(name="code_analyzer", model=m, tools=[T.analyze_code_structure], output_key="analysis",
                        instruction="Call analyze_code_structure with which='original'. Then describe what the code does and list every issue the tool reported, with line numbers. Do not invent issues.")
    style = LlmAgent(name="style_checker", model=m, tools=[T.check_style], output_key="style",
                     instruction="Call check_style with which='original'. Report the score and each violation with its rule id and line.")
    tester = LlmAgent(name="test_runner", model=m, tools=[T.run_python_tests], output_key="test_report",
                      instruction="The code under review:\n```python\n{code}\n```\nWrite 5-10 assert-style tests covering normal cases, edge cases (empty input, zero, None) and error cases, "
                                  "based on what the code is evidently meant to do. Call run_python_tests with which='original'. Report passed/failed and what each failure reveals.")
    synth = LlmAgent(name="feedback_synthesizer", model=m, output_key="review",
                     instruction="Analysis: {analysis}\nStyle: {style}\nTests: {test_report}\nWrite the review: 1) verdict in one line, 2) bugs (from failing tests) — most severe first, "
                                 "3) risks, 4) style. Each item cites a line. Only include what the reports support.")
    fixer = LlmAgent(name="code_fixer", model=m, tools=[T.submit_fix],
                     instruction="Original code:\n```python\n{code}\n```\nReview: {review}\nLatest fix test result: {tests_fixed?}\nProduce the complete corrected file and call submit_fix. "
                                 "Fix every bug and reported issue; keep the public function names and behaviour that the tests expect.")
    fix_tester = LlmAgent(name="fix_tester", model=m, tools=[T.run_python_tests, T.check_style, T.analyze_code_structure],
                          instruction="Re-run the same tests on the fix: call run_python_tests with which='fixed' and tests={test_cases}. Then call check_style and analyze_code_structure with which='fixed'. Report the numbers.")
    validator = LlmAgent(name="fix_validator", model=m, tools=[exit_loop],
                         instruction="Fixed-code test result: {tests_fixed?}\nIf failed is 0 and there is no load_error, call exit_loop. Otherwise state exactly which tests still fail and why.")
    reporter = LlmAgent(name="fix_reporter", model=m,
                        instruction="Review: {review}\nFixed code: {fixed_code?}\nFix notes: {fix_notes?}\nTests before: {tests_original?}\nTests after: {tests_fixed?}\nStyle before: {style_original?}\nStyle after: {style_fixed?}\n"
                                    "Give the user the review, then — if a fix exists — the fixed code in a python block, what changed, and before/after numbers. If tests still fail after the fix, say so plainly.")
    return SequentialAgent(name="code_review_assistant", description="Reviews Python code, tests it, and proposes a verified fix.", before_agent_callback=capture_submission, sub_agents=[
        SequentialAgent(name="review_pipeline", sub_agents=[analyzer, style, tester, synth]),
        LoopAgent(name="fix_loop", max_iterations=3, before_agent_callback=skip_if_clean, sub_agents=[fixer, fix_tester, validator]),
        reporter,
    ])


root_agent = build_agent()
