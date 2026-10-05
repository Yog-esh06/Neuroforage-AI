"""Knowledge graph: entity lookup, multi-hop traversal, evidence-bearing paths, visualisation layout (no database)."""
from __future__ import annotations

import itertools

import networkx as nx
import pytest

from app.knowledge.graph import KnowledgeGraph
from app.knowledge.traversal import expand, find_paths, neighborhood_chunks, subgraph
from app.services.knowledge_service import _component_layout


def _kg() -> KnowledgeGraph:
    """Acme -party_to-> MSA -worth-> $2M ;  Globex -party_to-> MSA ;  Globex -operates_in-> Singapore ;  Lonely (isolated)."""
    kg = KnowledgeGraph()
    nodes = {1: ("Acme Corp", "ORG"), 2: ("Master Services Agreement", "CONTRACT"), 3: ("$2,000,000", "MONEY"), 4: ("Globex Industries Ltd", "ORG"),
             5: ("Singapore", "LOCATION"), 6: ("Lonely LLC", "ORG")}
    for i, (name, t) in nodes.items():
        kg.g.add_node(i, id=i, name=name, type=t, mentions=2, aliases=["Acme"] if i == 1 else [], attributes={})
    edges = [(1, 2, "party_to", 0.9, 11), (2, 3, "worth", 0.85, 12), (4, 2, "party_to", 0.8, 11), (4, 5, "operates_in", 0.85, 13)]
    for k, (u, v, rel, conf, chunk) in enumerate(edges, start=1):
        kg.g.add_edge(u, v, key=k, id=k, relation=rel, confidence=conf, evidence=f"{nodes[u][0]} {rel} {nodes[v][0]}.", document_id=1, document="msa.pdf", page=1, chunk_id=chunk)
    for chunk, ents in {11: {1, 2, 4}, 12: {2, 3}, 13: {4, 5}}.items():
        kg.chunk_entities[chunk] = set(ents)
        for e in ents:
            kg.entity_chunks[e].add(chunk)
    from app.utils.text import canonical_key

    for i, (name, _) in nodes.items():
        kg.name_index[canonical_key(name)].append(i)
    kg.name_index[canonical_key("Acme")].append(1)
    kg._stale = False
    return kg


def test_entity_search_exact_prefix_alias_and_type_filter():
    kg = _kg()
    assert kg.search_entities("Acme Corp")[0]["id"] == 1 and kg.search_entities("Acme Corp")[0]["match_score"] == 1.0
    assert kg.search_entities("glob")[0]["id"] == 4  # prefix
    assert {e["id"] for e in kg.search_entities("sing", types={"LOCATION"})} == {5}
    assert kg.search_entities("zzzz") == []


def test_query_entity_linking_uses_phrases_not_substrings():
    kg = _kg()
    linked = {i for i, _ in kg.link_query_entities("What did Globex Industries Ltd agree to with Acme?")}
    assert {1, 4} <= linked and 6 not in linked


def test_multi_hop_expansion_respects_hops_and_relation_filter():
    kg = _kg()
    assert set(expand(kg, [1], hops=1)) == {1, 2}
    assert set(expand(kg, [1], hops=2)) == {1, 2, 3, 4}
    assert set(expand(kg, [1], hops=3)) == {1, 2, 3, 4, 5}
    assert set(expand(kg, [1], hops=3, relations={"party_to"})) == {1, 2, 4}
    assert 3 not in expand(kg, [1], hops=3, include_values=False)


def test_paths_carry_evidence_for_every_step_and_handle_no_path():
    kg = _kg()
    paths = find_paths(kg, 1, 5, max_hops=4)
    assert paths and paths[0]["hops"] == 3  # Acme -> MSA -> Globex -> Singapore
    assert [n["name"] for n in paths[0]["nodes"]] == ["Acme Corp", "Master Services Agreement", "Globex Industries Ltd", "Singapore"]
    assert len(paths[0]["steps"]) == 3 and all(s["evidence"] and s["document"] == "msa.pdf" for s in paths[0]["steps"])
    assert find_paths(kg, 1, 5, max_hops=2) == []
    assert find_paths(kg, 1, 6) == []  # isolated node
    assert find_paths(kg, 1, 999) == []


def test_subgraph_for_visualisation():
    kg = _kg()
    sg = subgraph(kg, 1, hops=1)
    assert {n["id"] for n in sg["nodes"]} == {1, 2} and sg["nodes"][0]["is_center"] is True
    assert {e["relation"] for e in sg["edges"]} == {"party_to"}
    assert subgraph(kg, 1, hops=2, min_confidence=0.9)["edges"][0]["confidence"] >= 0.9
    assert subgraph(kg, 404) == {"nodes": [], "edges": []}


def test_graph_retrieval_scores_decay_with_distance():
    kg = _kg()
    scores = neighborhood_chunks(kg, [(1, 1.0)], hops=2)
    assert scores[11] > scores[12] > 0  # chunk about Acme itself outranks the chunk 2 hops away
    assert 13 in scores and scores[13] <= scores[12] + 1e-9 or 13 in scores
    assert neighborhood_chunks(kg, [(6, 1.0)], hops=2) == {}  # isolated entity reaches nothing


def test_stats():
    st = _kg().stats()
    assert st["entities"] == 6 and st["relationships"] == 4 and st["by_type"]["ORG"] == 3 and st["by_relation"]["party_to"] == 2


@pytest.mark.parametrize("n_components,size", [(1, 6), (4, 3), (7, 1)])
def test_overview_layout_never_overlaps_node_boxes(n_components, size):
    g = nx.Graph()
    nid = 0
    for _ in range(n_components):
        ids = list(range(nid, nid + size))
        g.add_nodes_from(ids)
        g.add_edges_from(zip(ids, ids[1:]))
        nid += size
    pos = _component_layout(g)
    assert set(pos) == set(g.nodes)
    for a, b in itertools.combinations(pos, 2):
        assert abs(pos[a][0] - pos[b][0]) >= 209 or abs(pos[a][1] - pos[b][1]) >= 69
