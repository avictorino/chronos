"""Assembles the StateGraph. See spec/03-architecture-spec.md for the node
diagram. `MAX_EXPANSION_DEPTH`/counting-based limits are enforced upstream
(discover_* nodes already cap candidate lists to MAX_*_PER_CIVILIZATION), so
this module only wires nodes together.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.graph import nodes
from app.graph.state import IngestionState

# Default recursion_limit passed at invocation time (see ingestion_service.py).
# LangGraph's own default (25) is far too small once you account for the
# self-loops below — see spec/03-architecture-spec.md.
DEFAULT_RECURSION_LIMIT = 2000


def build_workflow(checkpointer=None):
    graph = StateGraph(IngestionState)

    graph.add_node("load_civilization", nodes.load_civilization)
    graph.add_node("extract_civilization_profile", nodes.extract_civilization_profile)
    graph.add_node("persist_civilization", nodes.persist_civilization)
    graph.add_node("discover_events", nodes.discover_events)
    graph.add_node("expand_events", nodes.expand_events)
    graph.add_node("discover_people", nodes.discover_people)
    graph.add_node("expand_people", nodes.expand_people)
    graph.add_node("discover_places", nodes.discover_places)
    graph.add_node("expand_places", nodes.expand_places)
    graph.add_node("extract_relationships", nodes.extract_relationships)
    graph.add_node("generate_claims", nodes.generate_claims)
    graph.add_node("entity_resolution", nodes.entity_resolution)
    graph.add_node("generate_chunks", nodes.generate_chunks)
    graph.add_node("generate_embeddings", nodes.generate_embeddings)
    graph.add_node("persist_graph", nodes.persist_graph)

    graph.add_edge(START, "load_civilization")
    graph.add_edge("load_civilization", "extract_civilization_profile")
    graph.add_edge("extract_civilization_profile", "persist_civilization")
    graph.add_edge("persist_civilization", "discover_events")
    graph.add_edge("discover_events", "expand_events")
    # expand_events / expand_people / expand_places / extract_relationships /
    # generate_claims route themselves dynamically via Command(goto=...)
    # (self-loop while pending items remain, otherwise on to the next stage)
    # — they intentionally have no static outgoing add_edge.
    graph.add_edge("discover_people", "expand_people")
    graph.add_edge("discover_places", "expand_places")
    graph.add_edge("entity_resolution", "generate_chunks")
    graph.add_edge("generate_chunks", "generate_embeddings")
    graph.add_edge("generate_embeddings", "persist_graph")
    graph.add_edge("persist_graph", END)

    return graph.compile(checkpointer=checkpointer)
