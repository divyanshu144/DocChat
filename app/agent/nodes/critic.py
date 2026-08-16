import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.agent.state import AgentState
from app.core.config import settings
from app.services.llm import chat_complete

logger = logging.getLogger(__name__)

CRITIC_PROMPT = """\
You are a quality critic. Evaluate whether the answer adequately addresses the query.

Query: {query}
Answer: {answer}

Respond ONLY with valid JSON:
{{"quality": "good" | "poor", "feedback": "..."}}

- "good": answer is grounded in context and addresses the full query
- "poor": answer is missing key information, vague, or doesn't address the query
- feedback: if "poor", one sentence explaining what's missing
"""


def _context_from(state: AgentState) -> str:
    """Flatten the retrieved chunks the answer was drawn from."""
    return "\n\n".join(
        chunk.get("text", "") for chunk in state.get("retrieved_chunks") or []
    )


def _record_rejection(state: AgentState, verdict: str, reason: str) -> None:
    """Append one rejected answer to the JSONL sink, if a path is configured.

    This is the only point at which a rejected draft is observable: on replan the
    graph re-runs the synthesizer and overwrites `state["answer"]`, so nothing
    downstream — including the saved message — ever sees it again.

    Off the critical path by construction. No configured path is a no-op, and every
    failure is swallowed: a rejected draft is training data worth keeping, never a
    reason to fail the user's request.
    """
    path = settings.critic_rejection_log.strip()
    if not path:
        return

    try:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": state["query"],
            "answer": state["answer"],
            "context": _context_from(state),
            "verdict": verdict,
            "reason": reason,
        }
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        logger.debug("critic_rejection_log_failed", exc_info=True)


async def critic_node(state: AgentState) -> dict:
    iteration = state.get("iteration", 0) + 1

    if iteration >= 2:
        return {"needs_replan": False, "iteration": iteration, "critic_feedback": ""}

    prompt = CRITIC_PROMPT.format(query=state["query"], answer=state["answer"])
    response = await chat_complete([{"role": "user", "content": prompt}], max_tokens=150)

    try:
        data = json.loads(response)
        quality = data.get("quality", "good")
        feedback = data.get("feedback", "")
    except (json.JSONDecodeError, KeyError, TypeError):
        quality = "good"
        feedback = ""

    needs_replan = quality == "poor"
    if needs_replan:
        _record_rejection(state, verdict=quality, reason=feedback)

    return {
        "needs_replan": needs_replan,
        "critic_feedback": feedback if needs_replan else "",
        "iteration": iteration,
    }
