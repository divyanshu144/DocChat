import json
from app.agent.state import AgentState
from app.services.llm import chat_complete

_PROMPT = """\
You are a quality critic. Evaluate whether the answer adequately addresses the query.

Query: {query}
Answer: {answer}

Respond ONLY with valid JSON:
{{"quality": "good" | "poor", "feedback": "..."}}

- "good": answer is grounded in context and addresses the full query
- "poor": answer is missing key information, vague, or doesn't address the query
- feedback: if "poor", one sentence explaining what's missing
"""


async def critic_node(state: AgentState) -> dict:
    iteration = state.get("iteration", 0) + 1

    if iteration >= 2:
        return {"needs_replan": False, "iteration": iteration, "critic_feedback": ""}

    prompt = _PROMPT.format(query=state["query"], answer=state["answer"])
    response = await chat_complete([{"role": "user", "content": prompt}], max_tokens=150)

    try:
        data = json.loads(response)
        quality = data.get("quality", "good")
        feedback = data.get("feedback", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        quality = "good"
        feedback = ""

    needs_replan = quality == "poor"
    return {
        "needs_replan": needs_replan,
        "critic_feedback": feedback if needs_replan else "",
        "iteration": iteration,
    }
