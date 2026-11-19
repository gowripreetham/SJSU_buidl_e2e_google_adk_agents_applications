"""An ADK pipeline that uses the Gemini CLI as a tool.

    codebase_pipeline (SequentialAgent)
      1. cli_operator   LlmAgent with tools prepare_repo + gemini_cli — breaks the request into focused CLI questions
                        (a before_tool_callback caps how many CLI runs one request may spend)
      2. report_writer  LlmAgent, no tools — turns the raw CLI output in state into the answer for the user
"""
from __future__ import annotations
import os

from google.adk.agents import LlmAgent, SequentialAgent

from . import tools as T

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")
MAX_CLI_CALLS = int(os.environ.get("MAX_CLI_CALLS", "4"))


def budget_guard(tool, args, tool_context):
    """before_tool_callback: returning a dict skips the tool and hands this dict to the model instead."""
    if tool.name == "gemini_cli" and tool_context.state.get("cli_calls", 0) >= MAX_CLI_CALLS:
        return {"error": f"CLI budget of {MAX_CLI_CALLS} calls spent — answer with what you have."}
    return None


def build_agent(model=None) -> SequentialAgent:
    m = model or MODEL
    operator = LlmAgent(name="cli_operator", model=m, tools=[T.prepare_repo, T.gemini_cli], before_tool_callback=budget_guard, output_key="cli_findings",
                        instruction="You investigate codebases with the Gemini CLI. First call prepare_repo with the repository the user named. "
                                    "Then call gemini_cli with focused questions (at most a few). If a call returns an error or a non-zero exit_code, "
                                    "say so plainly. Finish by restating the raw findings — do not add facts the CLI did not report.")
    writer = LlmAgent(name="report_writer", model=m,
                      instruction="Findings from the Gemini CLI: {cli_findings}\nWrite the answer to the user's request from these findings only: "
                                  "a short summary, then specifics with file names. If the findings contain an error, report it and stop.")
    return SequentialAgent(name="codebase_pipeline", description="Answers questions about a codebase by driving the Gemini CLI.", sub_agents=[operator, writer])


root_agent = build_agent()
