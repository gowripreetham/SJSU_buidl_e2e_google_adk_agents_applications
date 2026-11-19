"""Deep-research agent for lead generation, built with Google ADK.

    lead_gen_pipeline  (SequentialAgent)
      1. icp_analyst        LlmAgent, structured output → state["icp"]           what does a good lead look like?
      2. research_fanout    ParallelAgent                                          three researchers work at the same time
           market_scout       → state["candidates"]       who fits the profile?
           signal_hunter      → state["signals"]          who is showing buying intent right now?
           stack_analyst      → state["stack_notes"]      whose technology fits?
      3. quality_loop       LoopAgent (max 2 rounds)                               deep research = check your own evidence
           evidence_critic    calls exit_loop when every claim has a source; otherwise lists the gaps
           gap_filler         researches exactly those gaps
      4. lead_ranker        scores every candidate with the deterministic score_lead tool, writes and saves the report
"""
from __future__ import annotations
import os

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import exit_loop, google_search
from pydantic import BaseModel, Field

from . import tools as T

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")


class ICP(BaseModel):
    """Ideal customer profile extracted from the user's request."""
    product: str = Field(description="what the user sells")
    industries: list[str] = Field(description="target industries, lower case")
    min_employees: int = 0
    max_employees: int = 1_000_000
    regions: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(description="subset of: hiring, funding, tech_change, expansion, leadership, compliance")
    tech_keywords: list[str] = Field(default_factory=list)


RULES = "Every factual claim must carry the source id returned by the tool, in square brackets. If a tool returns nothing, say so — never invent companies, numbers or sources."


def build_agent(model=None, search: str = "local") -> SequentialAgent:
    """search="local" uses the bundled synthetic corpus; search="google" uses Google Search grounding (needs a Gemini key)."""
    m = model or MODEL
    research_tools = [google_search] if search == "google" else [T.search_companies, T.get_company_profile, T.find_signals]

    icp_analyst = LlmAgent(name="icp_analyst", model=m, output_schema=ICP, output_key="icp",
                           instruction="Turn the user's request into an ideal customer profile. Infer sensible defaults for anything not stated. Output JSON only.")
    scout = LlmAgent(name="market_scout", model=m, tools=research_tools, output_key="candidates",
                     instruction=f"ICP: {{icp}}\nFind up to 6 companies matching the ICP's industries, size and regions. List name, industry, HQ, head count. {RULES}")
    hunter = LlmAgent(name="signal_hunter", model=m, tools=research_tools, output_key="signals",
                      instruction=f"ICP: {{icp}}\nFind companies showing the ICP's buying signals in the last six months. For each: the signal type, date and one-line evidence. {RULES}")
    stack = LlmAgent(name="stack_analyst", model=m, tools=research_tools, output_key="stack_notes",
                     instruction=f"ICP: {{icp}}\nFind companies whose technology stack overlaps the ICP's tech keywords and note who typically owns the buying decision. {RULES}")
    critic = LlmAgent(name="evidence_critic", model=m, tools=[exit_loop], output_key="gaps",
                      instruction="Review the research.\nCandidates: {candidates}\nSignals: {signals}\nStack: {stack_notes}\nGap research so far: {gap_notes?}\n"
                                  "If every shortlisted company has head count, region, at least one sourced signal and a tech stack, call exit_loop. "
                                  "Otherwise list the specific missing facts, one per line, and nothing else.")
    filler = LlmAgent(name="gap_filler", model=m, tools=research_tools, output_key="gap_notes",
                      instruction=f"Research exactly these gaps and nothing else: {{gaps}}\n{RULES}")
    ranker = LlmAgent(name="lead_ranker", model=m, tools=[T.get_company_profile, T.find_signals, T.score_lead, T.save_report],
                      instruction="ICP: {icp}\nCandidates: {candidates}\nSignals: {signals}\nStack: {stack_notes}\nGap research: {gap_notes?}\n"
                                  "For every company mentioned, call score_lead with the facts gathered (look up anything missing first). Then write a Markdown report: "
                                  "a ranked table (company, score, tier, why now), and for each tier-A or tier-B lead a short brief with the evidence and its source ids, "
                                  "who to contact (role, not a person) and a one-sentence opening angle tied to the signal. List companies you rejected and why. "
                                  "Call save_report with the report, then reply with the ranked table.")
    return SequentialAgent(name="lead_gen_pipeline", description="Deep research for B2B lead generation.", sub_agents=[
        icp_analyst,
        ParallelAgent(name="research_fanout", sub_agents=[scout, hunter, stack]),
        LoopAgent(name="quality_loop", max_iterations=2, sub_agents=[critic, filler]),
        ranker,
    ])


root_agent = build_agent(search=os.environ.get("LEADGEN_SEARCH", "local"))
