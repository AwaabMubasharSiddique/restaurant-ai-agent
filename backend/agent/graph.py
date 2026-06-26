"""Assemble the LangGraph state machine.

Topology:

        START
          |
    classify_intent
          |   (conditional edge: route_intent)
   .------+------------------------------------------.
   v      v        v          v          v           v
 handle_  handle_  handle_    handle_    handle_     handle_
reservation menu_  order      hours_     complaint   other
   |      question   |        location     |           |
   '------+------+----+----------+---------+-----------'
          v
     persist_log   (log to Supabase + append AI reply to memory)
          |
         END

State flows as a dict (agent/state.py). The checkpointer (agent/memory.py) keyed
by thread_id == session_id gives each conversation its own persistent history.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from agent import nodes
from agent.memory import get_checkpointer
from agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    # Nodes
    graph.add_node("classify_intent", nodes.classify_intent)
    graph.add_node("handle_reservation", nodes.handle_reservation)
    graph.add_node("handle_menu_question", nodes.handle_menu_question)
    graph.add_node("handle_order", nodes.handle_order)
    graph.add_node("handle_hours_location", nodes.handle_hours_location)
    graph.add_node("handle_complaint", nodes.handle_complaint)
    graph.add_node("handle_greeting", nodes.handle_greeting)
    graph.add_node("handle_other", nodes.handle_other)
    graph.add_node("persist_log", nodes.persist_log)

    # Entry -> classifier
    graph.add_edge(START, "classify_intent")

    # Classifier -> exactly one handler, chosen at runtime by route_intent.
    graph.add_conditional_edges(
        "classify_intent",
        nodes.route_intent,
        nodes.HANDLER_NODES,  # the possible destinations
    )

    # Every handler -> logging -> END
    for handler in nodes.HANDLER_NODES:
        graph.add_edge(handler, "persist_log")
    graph.add_edge("persist_log", END)

    return graph.compile(checkpointer=get_checkpointer())


# Compiled once at import; reused for every request.
compiled_graph = build_graph()


def run_agent(message: str, session_id: str) -> dict:
    """Run one user message through the graph for a given conversation/session."""
    config = {"configurable": {"thread_id": session_id}}
    return compiled_graph.invoke(
        {
            "messages": [HumanMessage(content=message)],
            "user_message": message,
            "session_id": session_id,
        },
        config=config,
    )
