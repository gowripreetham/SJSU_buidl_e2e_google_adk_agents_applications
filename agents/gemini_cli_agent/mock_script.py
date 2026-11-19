"""Scripted model turns for the offline demo/test (not an LLM). The CLI subprocess really runs (the stub binary)."""
from pathlib import Path

from common.scripted_llm import call

REPO = str(Path(__file__).parent / "sample_repo")
SCRIPT = {
    "cli_operator": [call("prepare_repo", source=REPO), call("gemini_cli", task="Explain the structure of this codebase and list its classes and functions."),
                     call("gemini_cli", task="Which behaviours have no tests? Draft a test plan."),
                     lambda c: "CLI findings:\n" + "\n---\n".join(r.get("output", r.get("error", "")) for r in c.results("gemini_cli"))],
    "report_writer": [lambda c: "Summary (from the Gemini CLI output): the repo has one module, inventory.py, with class Inventory (add, remove, total) and no test files.\n"
                                "Test plan: add() accumulates quantities; remove() raises ValueError on insufficient stock; total() sums all items."],
}
