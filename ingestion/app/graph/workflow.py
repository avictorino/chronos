"""Assembles the StateGraph. See spec/03-architecture-spec.md for the node
diagram. `max_expansion_depth`/`max_*_per_civilization` limits are enforced in
graph/nodes.py (`_enqueue_mentions`/`_route_after_stage`), so this module only
wires nodes together.
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
    # discover_people / discover_places / expand_events / expand_people /
    # expand_places / extract_relationships / generate_claims all route
    # themselves dynamically via Command(goto=...) — expand_*/extract_*/
    # generate_claims self-loop while their own pending list has items;
    # discover_people/discover_places and the "queue drained" branch of every
    # expand_* node instead call `_route_after_stage`, which is what lets a
    # person/place discovered mid-pipeline recursively re-queue new events —
    # looping back across stage boundaries, not just within one node. None of
    # them have a static outgoing add_edge.
    graph.add_edge("entity_resolution", "generate_chunks")
    graph.add_edge("generate_chunks", "generate_embeddings")
    graph.add_edge("generate_embeddings", "persist_graph")
    graph.add_edge("persist_graph", END)

    return graph.compile(checkpointer=checkpointer)
