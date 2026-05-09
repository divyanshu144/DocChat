import os
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes.planner import planner_node
from app.agent.nodes.retriever import retriever_node
from app.agent.nodes.synthesizer import synthesizer_node
from app.agent.nodes.critic import critic_node
from app.core.config import settings


def _route_critic(state: AgentState) -> str:
    if state.get("needs_replan") and state.get("iteration", 0) < 2:
        return "planner"
    return END


def _configure_langsmith() -> None:
    if settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project


def build_graph():
    _configure_langsmith()

    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("retriever", retriever_node)
    g.add_node("synthesizer", synthesizer_node)
    g.add_node("critic", critic_node)

    g.set_entry_point("planner")
    g.add_edge("planner", "retriever")
    g.add_edge("retriever", "synthesizer")
    g.add_edge("synthesizer", "critic")
    g.add_conditional_edges("critic", _route_critic, {"planner": "planner", END: END})

    return g.compile()


agent_graph = build_graph()
