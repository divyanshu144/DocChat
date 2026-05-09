import json
from app.agent.state import AgentState
from app.services.llm import chat_complete

_PROMPT = """\
You are a research planner. Decide which source types to search for the user's query.

Available sources:
- pdf: uploaded document files
- youtube: video transcripts
- web: scraped web pages

Respond ONLY with valid JSON matching this schema exactly:
{{"sources_to_use": ["pdf", "youtube", "web"], "rewritten_query": "..."}}

Rules:
- Include any source that could plausibly help answer the query
- If critic_feedback is provided, rewrite the query to address what was missing
- Otherwise rewritten_query should equal the original query
- sources_to_use must contain at least one value

Query: {query}
Critic feedback: {critic_feedback}
"""


async def planner_node(state: AgentState) -> dict:
    prompt = _PROMPT.format(
        query=state["query"],
        critic_feedback=state.get("critic_feedback") or "none",
    )
    response = await chat_complete([{"role": "user", "content": prompt}], max_tokens=200)

    try:
        data = json.loads(response)
        sources = [s for s in data.get("sources_to_use", []) if s in ("pdf", "youtube", "web")]
        rewritten = data.get("rewritten_query", state["query"])
    except (json.JSONDecodeError, KeyError, TypeError):
        sources = ["pdf", "youtube", "web"]
        rewritten = state["query"]

    if not sources:
        sources = ["pdf", "youtube", "web"]

    return {"sources_to_use": sources, "query": rewritten}
