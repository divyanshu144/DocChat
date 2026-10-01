import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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

Judge in two steps, in order.

STEP 1 — defects that nothing excuses. The answer is "poor" if it:
  - contradicts itself, or asserts something and then its opposite;
  - is too vague to be useful, or has had its specifics replaced by placeholders;
  - answers a different question than the one asked.
If any of these apply, stop and return "poor". No amount of honesty or disclosure
rescues an answer that is self-contradictory, empty, or off-topic.

STEP 2 — only if the answer passes step 1, judge MISSING INFORMATION by whether the
gap is DISCLOSED:
  - "good": it answers as far as it honestly can. Stating that the provided context
    does not contain the information is GOOD — declining to answer from missing
    sources is correct behaviour, not a defect. This still holds when the answer
    resolves part of the query and says plainly that the rest is unavailable.
  - "poor": it drops part of the query WITHOUT SAYING SO, leaving the reader unable
    to tell what is missing.

feedback: if "poor", one sentence explaining what's wrong.
"""


def _context_from(state: AgentState) -> str:
    """Flatten the retrieved chunks the answer was drawn from."""
    return "\n\n".join(
        chunk.get("text", "") for chunk in state.get("retrieved_chunks") or []
    )


def _open_rejection(state: AgentState, reason: str) -> dict:
    """Capture the rejected half of a training example.

    Not written yet. A rejected draft on its own is half a training example — useful
    for neither supervised fine-tuning (which wants the preferred output) nor
    preference training (which wants both sides). The replacement is produced by the
    next pass, so this rides along on the state until that pass can complete it.
    """
    return {
        # Correlates the pair with everything else this turn produced. Without it a
        # mined record cannot be joined back to the conversation it came from.
        "rejection_id": str(uuid4()),
        "conversation_id": state.get("conversation_id", ""),
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "query": state.get("original_query", state["query"]),
        "context": _context_from(state),
        "rejected_answer": state["answer"],
        "rejected_reason": reason,
    }


def _write_pair(state: AgentState, accepted_verdict: str) -> None:
    """Append one complete (rejected, accepted) pair to the JSONL sink.

    Called only where the final answer is known, so every line written is a usable
    training example. A rejection whose replacement never materialised — the graph
    ended early, or was compiled without the retry edge — is deliberately dropped
    rather than written as a half record that has to be filtered out later.

    Off the critical path by construction. No configured path is a no-op, and every
    failure is swallowed: this data is worth keeping, never worth failing a request for.
    """
    path = settings.critic_rejection_log.strip()
    pending = state.get("pending_rejection")
    if not path or not pending:
        return

    try:
        record = {
            **pending,
            "accepted_answer": state["answer"],
            "accepted_verdict": accepted_verdict,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
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
        # Retry budget spent. Whatever this pass produced is what the user gets, which
        # makes it the accepted half — recorded as accepted by exhaustion, not by
        # approval, because no second verdict was ever taken.
        _write_pair(state, accepted_verdict="accepted_by_iteration_cap")
        return {
            "needs_replan": False,
            "iteration": iteration,
            "critic_feedback": "",
            "pending_rejection": None,
        }

    prompt = CRITIC_PROMPT.format(query=state.get("original_query", state["query"]), answer=state["answer"])
    response = await chat_complete(
        [{"role": "user", "content": prompt}],
        max_tokens=150,
        # A verdict is a label, not prose. Pinned so the same draft scores the same way
        # twice — the benchmark cannot attribute a change to anything otherwise.
        temperature=settings.classification_temperature,
    )

    try:
        data = json.loads(response)
        quality = data.get("quality", "good")
        feedback = data.get("feedback", "")
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
        logger.warning("critic_json_parse_failed; accepting without a verdict", exc_info=True)
        quality = "good"
        feedback = ""

    needs_replan = quality == "poor"
    return {
        "needs_replan": needs_replan,
        "critic_feedback": feedback if needs_replan else "",
        "iteration": iteration,
        "pending_rejection": _open_rejection(state, feedback) if needs_replan else None,
    }
