"""Gemini CLI as an ADK tool.

The model decides WHAT to ask; this module decides HOW the CLI is run, and it is deliberately strict:
  · no shell — the task goes to the CLI as one argv element, so quotes / `;` / `$(…)` in a task cannot inject commands
  · repositories are cloned only from https://github.com/<owner>/<repo> URLs, shallow, into a private work directory
  · a timeout, an output cap, and the exit code reported back to the model as data
Set GEMINI_CLI_BIN to point at the binary (default: `gemini` on PATH; the tests use stub/gemini).
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from google.adk.tools import ToolContext

WORK = Path(os.environ.get("GEMINI_CLI_WORKDIR", Path(tempfile.gettempdir()) / "adk-gemini-cli"))
GITHUB = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(\.git)?/?$")
MAX_OUTPUT = 12_000


def _bin() -> str | None:
    b = os.environ.get("GEMINI_CLI_BIN", "gemini")
    return b if os.path.isfile(b) and os.access(b, os.X_OK) else shutil.which(b)


def prepare_repo(source: str, tool_context: ToolContext) -> dict:
    """Make a codebase available for analysis. Call this once before gemini_cli.

    Args:
        source: an https://github.com/owner/repo URL, or the path of a local directory.
    Returns:
        {"repo_dir": …, "files": n} or {"error": …}.
    """
    m = GITHUB.match(source.strip())
    if m:
        dest = WORK / f"{m.group(1)}__{m.group(2)}"
        if not dest.exists():
            WORK.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["git", "clone", "--depth", "1", "--", source.strip(), str(dest)], capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                return {"error": f"git clone failed: {r.stderr.strip()[-400:]}"}
    else:
        dest = Path(source).expanduser().resolve()
        if source.strip().startswith(("http:", "https:", "git@", "ssh:")) or not dest.is_dir():
            return {"error": "source must be an https://github.com/owner/repo URL or an existing local directory"}
    tool_context.state["repo_dir"] = str(dest)
    return {"repo_dir": str(dest), "files": sum(1 for p in dest.rglob("*") if p.is_file() and ".git" not in p.parts)}


def gemini_cli(task: str, tool_context: ToolContext) -> dict:
    """Run the Gemini CLI non-interactively inside the prepared repository and return what it printed.

    Use it for work that needs the whole codebase: explain the architecture, find where something is implemented,
    draft a test plan, review a module. Ask one focused question per call.

    Args:
        task: the instruction for the Gemini CLI, in plain language.
    Returns:
        {"exit_code": int, "output": str} or {"error": str}.
    """
    repo = tool_context.state.get("repo_dir")
    if not repo or not Path(repo).is_dir():
        return {"error": "no repository prepared — call prepare_repo first"}
    binary = _bin()
    if not binary:
        return {"error": "Gemini CLI not found. Install it (npm i -g @google/gemini-cli) or set GEMINI_CLI_BIN."}
    if not task.strip() or len(task) > 4000:
        return {"error": "task must be 1–4000 characters"}
    try:
        r = subprocess.run([binary, "-p", task], cwd=repo, capture_output=True, text=True, timeout=int(os.environ.get("GEMINI_CLI_TIMEOUT", "600")))
    except subprocess.TimeoutExpired:
        return {"error": "Gemini CLI timed out"}
    out = r.stdout if r.returncode == 0 else (r.stdout + "\n" + r.stderr)
    if len(out) > MAX_OUTPUT:
        out = out[:MAX_OUTPUT] + f"\n… [truncated {len(out) - MAX_OUTPUT} characters]"
    calls = tool_context.state.get("cli_calls", 0) + 1
    tool_context.state["cli_calls"] = calls
    return {"exit_code": r.returncode, "output": out.strip()}
