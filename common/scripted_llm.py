"""ScriptedLlm — a stand-in for Gemini used ONLY by the offline tests and `--mock` demos.

It is NOT a language model. It subclasses ADK's BaseLlm and replays a fixed script per agent, so the real ADK machinery
(agents, tool calling, MCP toolsets, state, callbacks, loops) can be exercised without an API key.

A script maps an agent name to a list of steps. A step is one of
    call("tool", arg=...)             -> the model "asks" for a tool call        (several: [call(...), call(...)])
    "some text"                       -> the model answers in text
    lambda ctx: <either of the above> -> computed from what the agent has seen (ctx.last_tool, ctx.tools, ctx.text, ctx.state_text)
Each agent advances through its own list one model call at a time; the last step repeats if the list runs out.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from google.adk.models import BaseLlm, LlmResponse
from google.genai import types


def call(_name: str, **args) -> types.Part:
    return types.Part(function_call=types.FunctionCall(name=_name, args=args))


def _plain(r):
    """Unwrap ADK's {"result": x} and MCP's {"content": [...], "structuredContent": ...} envelopes to the tool's own value."""
    if isinstance(r, dict) and "isError" in r and "content" in r:
        if r.get("structuredContent") is not None:
            r = r["structuredContent"]
        else:
            text = "".join(c.get("text", "") for c in r["content"] if isinstance(c, dict))
            try:
                r = json.loads(text)
            except ValueError:
                r = text
    return r["result"] if isinstance(r, dict) and set(r) == {"result"} else r


@dataclass
class Ctx:
    agent: str
    system: str
    text: str                      # all text the agent has seen so far in this request (user + model + tool results)
    user: str                      # the latest plain-text user message
    tools: list[dict] = field(default_factory=list)   # every tool result so far: {"name":…, "response":…}

    @property
    def last_tool(self) -> Any:
        return self.tools[-1]["response"] if self.tools else None

    def results(self, name: str) -> list[Any]:
        return [t["response"] for t in self.tools if t["name"] == name]


class ScriptedLlm(BaseLlm):
    model: str = "scripted-mock"
    script: dict[str, list] = {}
    counters: dict[str, int] = {}
    log: list[tuple[str, str]] = []

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["scripted-mock"]

    def _ctx(self, req) -> Ctx:
        system = str(req.config.system_instruction or "") if req.config else ""
        agent = next((n for n in sorted(self.script, key=len, reverse=True) if f'"{n}"' in system or f"name is {n}" in system or f"`{n}`" in system), "")
        texts, tools, user = [], [], ""
        for c in req.contents or []:
            for p in c.parts or []:
                if p.text:
                    texts.append(p.text)
                    if c.role == "user":
                        user = p.text
                if p.function_response:
                    r = p.function_response.response
                    r = _plain(r)
                    tools.append({"name": p.function_response.name, "response": r})
                    texts.append(json.dumps(r, default=str))
        return Ctx(agent, system, "\n".join(texts), user, tools)

    async def generate_content_async(self, llm_request, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        ctx = self._ctx(llm_request)
        steps = self.script.get(ctx.agent)
        if not steps:
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"(scripted mock: no script for agent '{ctx.agent}')")]))
            return
        n = self.counters.get(ctx.agent, 0)
        self.counters[ctx.agent] = n + 1
        i = min(n, len(steps) - 1)
        step = steps[i]
        if callable(step):
            step = step(ctx)
        parts = step if isinstance(step, list) else [step]
        parts = [types.Part(text=p) if isinstance(p, str) else p for p in parts]
        self.log.append((ctx.agent, parts[0].function_call.name if parts[0].function_call else "text"))
        yield LlmResponse(content=types.Content(role="model", parts=parts))


def scripted(script: dict[str, list]) -> ScriptedLlm:
    return ScriptedLlm(script=script, counters={}, log=[])
