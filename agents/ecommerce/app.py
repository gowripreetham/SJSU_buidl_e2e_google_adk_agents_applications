"""FastAPI backend + single-page chat UI for the shopping agent.

    uvicorn agents.ecommerce.app:app --port 8000        # then open http://127.0.0.1:8000
    ECOM_MOCK=1 uvicorn agents.ecommerce.app:app …      # scripted model for an offline UI demo (replays demo.py's conversation)

Sign-in is SIMULATED: the page lets you pick one of two demo customers. In production the email must come from a
verified identity token (e.g. Google Sign-In ID token checked server-side), never from the request body.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from google.adk.runners import InMemoryRunner  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents.ecommerce.agent import build_agent  # noqa: E402

DEMO_USERS = {"alex@example.com": "Alex", "sam@example.com": "Sam"}
app = FastAPI(title="Sports store agent")
_runner: InMemoryRunner | None = None
_sessions: dict[str, str] = {}


def runner() -> InMemoryRunner:
    global _runner
    if _runner is None:
        model = None
        if os.environ.get("ECOM_MOCK") == "1":
            from common.scripted_llm import scripted
            from agents.ecommerce.mock_script import SCRIPT
            model = scripted(SCRIPT)
        _runner = InMemoryRunner(agent=build_agent(model=model, db_path=os.environ.get("STORE_DB")), app_name="shop")
    return _runner


class ChatIn(BaseModel):
    user: str
    message: str = Field(min_length=1, max_length=2000)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "web/index.html")


@app.get("/api/users")
def users():
    return [{"email": e, "name": n} for e, n in DEMO_USERS.items()]


@app.post("/api/chat")
async def chat(body: ChatIn):
    if body.user not in DEMO_USERS:
        raise HTTPException(401, "unknown user")
    r = runner()
    if body.user not in _sessions:
        s = await r.session_service.create_session(app_name="shop", user_id=body.user, state={"user_email": body.user, "user_name": DEMO_USERS[body.user]})
        _sessions[body.user] = s.id
    reply, tools = "", []
    async for ev in r.run_async(user_id=body.user, session_id=_sessions[body.user], new_message=types.Content(role="user", parts=[types.Part(text=body.message)])):
        for p in (ev.content.parts if ev.content and ev.content.parts else []):
            if p.function_call:
                tools.append({"name": p.function_call.name, "args": {k: v for k, v in dict(p.function_call.args or {}).items() if k != "user_email"}})
            elif p.function_response and isinstance(p.function_response.response, dict) and "error" in p.function_response.response:
                tools.append({"name": p.function_response.name, "blocked": p.function_response.response["error"]})
            elif p.text:
                reply = p.text
    return {"reply": reply, "tools": tools}
