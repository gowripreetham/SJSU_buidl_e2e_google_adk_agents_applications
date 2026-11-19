"""Tiny helpers to run an ADK agent from a script or a test and collect what happened."""
from __future__ import annotations
import asyncio
import os

from google.adk.runners import InMemoryRunner
from google.genai import types

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")


async def arun(agent, messages: list[str] | str, state: dict | None = None, verbose: bool = False, user_id: str = "user") -> dict:
    """Send one or more user messages in a single session. Returns final texts, tool calls, state and all events."""
    runner = InMemoryRunner(agent=agent, app_name="app")
    session = await runner.session_service.create_session(app_name="app", user_id=user_id, state=state or {})
    out = {"replies": [], "tool_calls": [], "tool_results": [], "authors": []}
    for msg in [messages] if isinstance(messages, str) else messages:
        if verbose:
            print(f"\n👤 {msg}")
        last = ""
        async for ev in runner.run_async(user_id=user_id, session_id=session.id, new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.function_call:
                    out["tool_calls"].append((ev.author, p.function_call.name, dict(p.function_call.args or {})))
                    if verbose:
                        print(f"  ⚙ [{ev.author}] {p.function_call.name}({str(dict(p.function_call.args or {}))[:110]})")
                elif p.function_response:
                    out["tool_results"].append((p.function_response.name, p.function_response.response))
                    if verbose:
                        print(f"    ↳ {str(p.function_response.response)[:130]}")
                elif p.text and not getattr(p, "thought", False):
                    last = p.text
                    out["authors"].append(ev.author)
                    if verbose:
                        print(f"  🤖 [{ev.author}] {p.text[:600]}")
        out["replies"].append(last)
    s = await runner.session_service.get_session(app_name="app", user_id=user_id, session_id=session.id)
    out["state"] = dict(s.state)
    await runner.close()
    return out


def run(agent, messages, **kw) -> dict:
    return asyncio.run(arun(agent, messages, **kw))
