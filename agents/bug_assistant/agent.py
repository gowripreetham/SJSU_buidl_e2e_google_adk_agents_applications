"""Software bug assistant: an ADK agent whose tools come from MCP servers.

    bug_assistant (LlmAgent)
      tools
        McpToolset → tickets_mcp_server.py over stdio     search / get / find_similar / create / update_status / add_comment
        McpToolset → GitHub's remote MCP server           (optional: BUG_ASSISTANT_GITHUB_MCP=1 + GITHUB_TOKEN; read-only filter)
        get_current_date                                  a plain function tool, to show MCP and local tools side by side
      before_tool_callback: closing or resolving a ticket requires the user's confirmation recorded in session state
"""
from __future__ import annotations
import os
import sys
from datetime import date
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams, StreamableHTTPConnectionParams
from mcp import StdioServerParameters

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")
SERVER = Path(__file__).parent / "tickets_mcp_server.py"

INSTRUCTION = """You are a bug-triage assistant for a software team. Today is {today?}.
- When a user reports a bug: call find_similar_tickets first. If a ticket with similarity >= 0.25 exists, show it and add the new details as a comment instead of creating a duplicate.
- Otherwise create a ticket: a specific title, a description with steps / expected / actual, a component, and a priority (P0 outage, P1 major feature broken, P2 degraded, P3 cosmetic). Say why you chose the priority.
- When asked about existing bugs, use search_tickets / get_ticket and answer from the results only. Quote ticket ids as #<id>.
- Never mark a ticket resolved or closed unless the user explicitly asks for that ticket.
- If a tool returns an error, tell the user what failed."""


def get_current_date() -> dict:
    """Today's date (UTC), for timestamps in comments."""
    return {"today": date.today().isoformat()}


def confirm_closing(tool, args, tool_context):
    """before_tool_callback — a guard in code, not in the prompt: resolving/closing needs the ticket id to appear in the user's last message."""
    if tool.name == "update_ticket_status" and args.get("status") in ("resolved", "closed"):
        said = " ".join(p.text or "" for p in (tool_context.user_content.parts if tool_context.user_content else []))
        if str(args.get("ticket_id")) not in said:
            return {"error": f"Refused: the user did not name ticket {args.get('ticket_id')} in their request. Ask them to confirm."}
    return None


def build_agent(model=None, db_path: str | None = None) -> LlmAgent:
    env = {**os.environ, **({"TICKETS_DB": db_path} if db_path else {})}
    toolsets = [McpToolset(connection_params=StdioConnectionParams(server_params=StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env), timeout=30))]
    if os.environ.get("BUG_ASSISTANT_GITHUB_MCP") == "1" and os.environ.get("GITHUB_TOKEN"):   # optional second MCP server (read-only tools); not exercised by the tests
        toolsets.append(McpToolset(connection_params=StreamableHTTPConnectionParams(url="https://api.githubcopilot.com/mcp/", headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"}),
                                   tool_filter=["search_issues", "get_issue", "list_issues"]))
    return LlmAgent(name="bug_assistant", model=model or MODEL, instruction=INSTRUCTION, tools=[*toolsets, get_current_date], before_tool_callback=confirm_closing,
                    description="Triage, search and update software bug tickets through MCP tools.")


root_agent = build_agent()
