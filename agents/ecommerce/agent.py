"""E-commerce shopping agent on Google ADK + MCP.

    shop_assistant (LlmAgent)  ──McpToolset (stdio)──►  store_mcp_server.py  ──►  SQLite
Production concerns handled in code rather than in the prompt:
  · identity      a before_tool_callback overwrites `user_email` on every tool call with the signed-in user from session
                  state, and refuses user-scoped tools when nobody is signed in — the model cannot act for another user
  · confirmation  place_order and cancel_order only run in a turn where the user's message contains an explicit yes/confirm
  · audit         an after_tool_callback appends every state-changing call to state["audit"]
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")
SERVER = Path(__file__).parent / "store_mcp_server.py"
USER_SCOPED = {"add_to_cart", "show_cart", "find_nearby_stores", "place_order", "list_orders", "cancel_order"}
NEEDS_CONFIRMATION = {"place_order", "cancel_order"}
CONFIRM = re.compile(r"\b(yes|confirm|confirmed|go ahead|place it|place the order|do it|cancel order)\b", re.I)

INSTRUCTION = """You are the shopping assistant of a sports store. The signed-in customer is {user_name?}.
- Find products with search_products; show name, brand, price. Use get_product_details before quoting sizes or colours.
- Before add_to_cart you need product, size and colour — ask for whatever is missing.
- Before place_order: show the cart, the store and the delivery method with its cost, state the total, and ask the customer to confirm. Call place_order only after they confirm.
- Prices, stock, totals and order status come from tools only. If a tool returns an error, explain it and offer the alternatives it lists.
- You never need the customer's email; the system supplies it."""


def enforce_identity(tool, args, tool_context):
    email = tool_context.state.get("user_email")
    if tool.name in USER_SCOPED:
        if not email:
            return {"error": "Nobody is signed in. Ask the customer to sign in first."}
        args["user_email"] = email                      # whatever the model put there is discarded
    if tool.name in NEEDS_CONFIRMATION:
        said = " ".join(p.text or "" for p in (tool_context.user_content.parts if tool_context.user_content else []))
        if not CONFIRM.search(said):
            return {"error": f"{tool.name} needs the customer's explicit confirmation in their latest message. Summarise and ask them to confirm."}
    return None


def audit(tool, args, tool_context, tool_response):
    failed = isinstance(tool_response, dict) and (tool_response.get("isError") or "error" in tool_response or '"error"' in str(tool_response.get("content", "")))
    if tool.name in {"add_to_cart", "place_order", "cancel_order"} and not failed:
        tool_context.state["audit"] = [*(tool_context.state.get("audit") or []), {"tool": tool.name, "args": {k: v for k, v in args.items() if k != "user_email"}}]
    return None


def build_agent(model=None, db_path: str | None = None) -> LlmAgent:
    env = {**os.environ, **({"STORE_DB": db_path} if db_path else {})}
    store = McpToolset(connection_params=StdioConnectionParams(server_params=StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env), timeout=30))
    return LlmAgent(name="shop_assistant", model=model or MODEL, instruction=INSTRUCTION, tools=[store], before_tool_callback=enforce_identity, after_tool_callback=audit,
                    description="Helps customers find sports products, manage a cart and place orders.")


root_agent = build_agent()
