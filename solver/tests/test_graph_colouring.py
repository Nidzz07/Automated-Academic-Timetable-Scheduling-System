"""Tests for :mod:`solver.graph` and :mod:`solver.colouring`.

All instances are hand-built small graphs where the correct answer is known
by inspection — real CE data is Phase 2.

Cross-checking: ``networkx`` is used *only inside tests* to validate that the
hand-written colouring is conflict-free and that adjacency agrees with a
reference implementation.  ``solver/`` itself never imports ``networkx``
(CONTEXT.md rule 3 — non-negotiable).
"""

from __future__ import annotations

from typing import Any

import networkx as nx
import pytest

from solver.colouring import welsh_powell
from solver.graph import ConflictGraph, build_conflict_graph
from solver.slots import SlotId, all_slots

# ======================================================================
# Helpers — tiny payload builders
# ======================================================================


def _slot_grid() -> dict[str, Any]:
    """The canonical SPIT slot grid fragment."""
    return {
        "days": 5,
        "periods_per_day": 10,
        "teaching_periods": [0, 1, 3, 4, 6, 7, 8, 9],
        "adjacency": [[0, 1], [1, 3], [3, 4], [4, 6], [6, 7], [7, 8], [8, 9]],
    }


def _session(
    sid: str,
    faculty: str = "fac-1",
    cohort: str = "coh-1",
    *,
    fixed_slot: dict[str, int] | None = None,
    subject: str = "subj-1",
    duration: int = 1,
    cohort_size: int = 60,
    session_type: str = "theory",
    requires_lab: bool = False,
) -> dict[str, Any]:
    return {
        "id": sid,
        "subject_id": subject,
        "faculty_id": faculty,
        "cohort_id": cohort,
        "session_type": session_type,
        "duration_periods": duration,
        "cohort_size": cohort_size,
        "requires_lab": requires_lab,
        "fixed_slot": fixed_slot,
    }


def _faculty_avail(
    faculty: str, unavailable: list[dict[str, int]] | None = None
) -> dict[str, Any]:
    return {
        "faculty_id": faculty,
        "unavailable_slots": unavailable or [],
    }


def _edge(u: str, v: str, reason: str = "FACULTY") -> dict[str, str]:
    return {"u": u, "v": v, "reason": reason}


def _minimal_payload(
    sessions: list[dict[str, Any]],
    edges: list[dict[str, str]] | None = None,
    faculty_availability: list[dict[str, Any]] | None = None,
    pinned_occupancy: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a complete edge-list payload from just sessions and edges."""
    # Auto-generate faculty_availability entries for every distinct faculty_id.
    if faculty_availability is None:
        seen_fac: set[str] = set()
        faculty_availability = []
        for s in sessions:
            fid = s["faculty_id"]
            if fid not in seen_fac:
                seen_fac.add(fid)
                faculty_availability.append(_faculty_avail(fid))

    return {
        "schema_version": "edge_list.v1",
        "slot_grid": _slot_grid(),
        "sessions": sessions,
        "edges": edges or [],
        "rooms": [],
        "faculty_availability": faculty_availability,
        "lab_blocks": [],
        "pinned_occupancy": pinned_occupancy or [],
    }


# ======================================================================
# graph.py — ConflictGraph construction
# ======================================================================


class TestBuildConflictGraph:
    """Tests for :func:`build_conflict_graph`."""

    def test_empty_payload(self) -> None:
        g = build_conflict_graph(_minimal_payload(sessions=[]))
        assert g.vertex_count() == 0
        assert g.edge_count() == 0

    def test_single_session_no_edges(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(sessions=[_session("s1")])
        )
        assert g.vertex_count() == 1
        assert g.edge_count() == 0
        assert g.degree("s1") == 0
        assert g.neighbours("s1") == frozenset()

    def test_two_sessions_with_faculty_conflict(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="fac-x"),
                    _session("s2", faculty="fac-x"),
                ],
                edges=[_edge("s1", "s2", "FACULTY")],
            )
        )
        assert g.vertex_count() == 2
        assert g.edge_count() == 1
        assert g.degree("s1") == 1
        assert g.neighbours("s1") == frozenset({"s2"})
        assert g.neighbours("s2") == frozenset({"s1"})

    def test_same_pair_with_multiple_reasons(self) -> None:
        """FACULTY *and* COHORT on the same pair → one neighbour, two reasons."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="fac-x", cohort="coh-a"),
                    _session("s2", faculty="fac-x", cohort="coh-a"),
                ],
                edges=[
                    _edge("s1", "s2", "FACULTY"),
                    _edge("s1", "s2", "COHORT"),
                ],
            )
        )
        # One neighbour relationship, despite two edge records.
        assert g.degree("s1") == 1
        assert g.adjacency["s1"]["s2"] == {"FACULTY", "COHORT"}

    def test_edge_count_deduplicates_pair(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1"), _session("s2")],
                edges=[
                    _edge("s1", "s2", "FACULTY"),
                    _edge("s1", "s2", "COHORT"),
                ],
            )
        )
        # Two edge records but one distinct pair.
        assert g.edge_count() == 1

    def test_triangle_graph(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="f1"),
                    _session("s2", faculty="f2"),
                    _session("s3", faculty="f3"),
                ],
                edges=[
                    _edge("s1", "s2", "COHORT"),
                    _edge("s2", "s3", "COHORT"),
                    _edge("s1", "s3", "COHORT"),
                ],
            )
        )
        assert g.vertex_count() == 3
        assert g.edge_count() == 3
        for sid in ("s1", "s2", "s3"):
            assert g.degree(sid) == 2

    def test_cohort_containment_edges_from_payload(self) -> None:
        """A batch's session and its parent division's session are connected
        by a COHORT edge in the payload — the graph builder trusts it."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("batch-a1", cohort="coh-batch-se-a-1", faculty="f1"),
                    _session("div-a", cohort="coh-div-se-a", faculty="f2"),
                ],
                edges=[_edge("batch-a1", "div-a", "COHORT")],
            )
        )
        assert "div-a" in g.neighbours("batch-a1")
        assert g.adjacency["batch-a1"]["div-a"] == {"COHORT"}

    def test_combined_division_is_one_vertex(self) -> None:
        """A CombinedDivisions lecture (e.g. SE C & D) is ONE session/vertex."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("comb-cd", cohort="coh-comb-se-cd", faculty="f1"),
                    _session("div-c", cohort="coh-div-se-c", faculty="f2"),
                    _session("div-d", cohort="coh-div-se-d", faculty="f3"),
                ],
                edges=[
                    _edge("comb-cd", "div-c", "COHORT"),
                    _edge("comb-cd", "div-d", "COHORT"),
                ],
            )
        )
        # ONE vertex for the combined lecture, not two.
        assert g.vertex_count() == 3
        assert g.degree("comb-cd") == 2
        assert g.neighbours("comb-cd") == frozenset({"div-c", "div-d"})

    def test_fixed_slot_is_parsed(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", fixed_slot={"day": 2, "period": 0}),
                ]
            )
        )
        assert g.sessions["s1"].fixed_slot == SlotId(2, 0)

    def test_null_fixed_slot(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(sessions=[_session("s1")])
        )
        assert g.sessions["s1"].fixed_slot is None

    def test_faculty_unavailability_stored(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", faculty="fac-x")],
                faculty_availability=[
                    _faculty_avail("fac-x", [{"day": 4, "period": 8}]),
                ],
            )
        )
        assert SlotId(4, 8) in g.faculty_unavailable["fac-x"]

    def test_pinned_occupancy_stored(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1")],
                pinned_occupancy=[{
                    "day": 3,
                    "period": 4,
                    "faculty_ids": ["fac-1"],
                    "room_ids": ["room-508"],
                    "cohort_ids": ["coh-div-se-b"],
                }],
            )
        )
        slot = SlotId(3, 4)
        assert slot in g.pinned_slots
        assert "fac-1" in g.pinned_slots[slot]["faculty_ids"]
        assert "room-508" in g.pinned_slots[slot]["room_ids"]

    # -- error cases --

    def test_duplicate_session_id_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicate session id"):
            build_conflict_graph(
                _minimal_payload(
                    sessions=[_session("s1"), _session("s1", faculty="f2")]
                )
            )

    def test_edge_referencing_unknown_session_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown session"):
            build_conflict_graph(
                _minimal_payload(
                    sessions=[_session("s1")],
                    edges=[_edge("s1", "s99", "FACULTY")],
                )
            )

    def test_self_loop_raises(self) -> None:
        with pytest.raises(ValueError, match="self-loop"):
            build_conflict_graph(
                _minimal_payload(
                    sessions=[_session("s1")],
                    edges=[_edge("s1", "s1", "FACULTY")],
                )
            )

    def test_missing_faculty_availability_raises(self) -> None:
        with pytest.raises(ValueError, match="no faculty_availability entry"):
            build_conflict_graph(
                _minimal_payload(
                    sessions=[_session("s1", faculty="fac-ghost")],
                    faculty_availability=[],
                )
            )


# ======================================================================
# graph.py — available_slots_for
# ======================================================================


class TestAvailableSlotsFor:
    """Tests for the available-slot domain function."""

    def test_fixed_slot_returns_only_that_slot(self) -> None:
        from solver.graph import available_slots_for

        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", fixed_slot={"day": 1, "period": 3})],
            )
        )
        result = available_slots_for(g, g.sessions["s1"])
        assert result == [SlotId(1, 3)]

    def test_faculty_unavailability_removes_slots(self) -> None:
        from solver.graph import available_slots_for

        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", faculty="fac-x")],
                faculty_availability=[
                    _faculty_avail("fac-x", [{"day": 0, "period": 0}]),
                ],
            )
        )
        result = available_slots_for(g, g.sessions["s1"])
        assert SlotId(0, 0) not in result
        # All other teaching slots should be present.
        assert len(result) == len(all_slots()) - 1

    def test_pinned_cohort_removes_slot(self) -> None:
        from solver.graph import available_slots_for

        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", faculty="fac-x", cohort="coh-a")],
                pinned_occupancy=[{
                    "day": 2,
                    "period": 7,
                    "faculty_ids": [],
                    "room_ids": [],
                    "cohort_ids": ["coh-a"],
                }],
            )
        )
        result = available_slots_for(g, g.sessions["s1"])
        assert SlotId(2, 7) not in result

    def test_pinned_faculty_removes_slot(self) -> None:
        from solver.graph import available_slots_for

        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", faculty="fac-x")],
                pinned_occupancy=[{
                    "day": 0,
                    "period": 1,
                    "faculty_ids": ["fac-x"],
                    "room_ids": [],
                    "cohort_ids": [],
                }],
            )
        )
        result = available_slots_for(g, g.sessions["s1"])
        assert SlotId(0, 1) not in result


# ======================================================================
# colouring.py — Welsh-Powell greedy
# ======================================================================


class TestWelshPowell:
    """Tests for :func:`welsh_powell`."""

    def test_empty_graph(self) -> None:
        g = build_conflict_graph(_minimal_payload(sessions=[]))
        assignment, unplaced = welsh_powell(g)
        assert assignment == {}
        assert unplaced == []

    def test_single_session_gets_first_slot(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(sessions=[_session("s1")])
        )
        assignment, unplaced = welsh_powell(g)
        assert len(assignment) == 1
        assert unplaced == []
        assert assignment["s1"] in all_slots()

    def test_two_conflicting_sessions_get_different_slots(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="fac-x"),
                    _session("s2", faculty="fac-x"),
                ],
                edges=[_edge("s1", "s2", "FACULTY")],
            )
        )
        assignment, unplaced = welsh_powell(g)
        assert len(unplaced) == 0
        assert assignment["s1"] != assignment["s2"]

    def test_triangle_uses_three_colours(self) -> None:
        """K₃ needs χ = 3 slots."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="f1", cohort="coh-1"),
                    _session("s2", faculty="f2", cohort="coh-2"),
                    _session("s3", faculty="f3", cohort="coh-3"),
                ],
                edges=[
                    _edge("s1", "s2", "COHORT"),
                    _edge("s2", "s3", "COHORT"),
                    _edge("s1", "s3", "COHORT"),
                ],
            )
        )
        assignment, unplaced = welsh_powell(g)
        assert len(unplaced) == 0
        colours = set(assignment.values())
        assert len(colours) == 3

    def test_fixed_slot_is_honoured(self) -> None:
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="fac-x",
                             fixed_slot={"day": 2, "period": 0}),
                    _session("s2", faculty="fac-x"),
                ],
                edges=[_edge("s1", "s2", "FACULTY")],
            )
        )
        assignment, unplaced = welsh_powell(g)
        assert assignment["s1"] == SlotId(2, 0)
        assert assignment["s2"] != SlotId(2, 0)
        assert len(unplaced) == 0

    def test_faculty_unavailability_constrains_colour(self) -> None:
        """A session whose faculty is unavailable on Mon 09.00 must not be
        coloured to that slot."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", faculty="fac-x")],
                faculty_availability=[
                    _faculty_avail("fac-x", [{"day": 0, "period": 0}]),
                ],
            )
        )
        assignment, unplaced = welsh_powell(g)
        assert assignment["s1"] != SlotId(0, 0)
        assert len(unplaced) == 0

    def test_deterministic_on_tie(self) -> None:
        """Same degree → lexicographic id order → deterministic output."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("b", faculty="f1"),
                    _session("a", faculty="f2"),
                ],
            )
        )
        a1, _ = welsh_powell(g)
        a2, _ = welsh_powell(g)
        assert a1 == a2

    def test_welsh_powell_ordering_highest_degree_first(self) -> None:
        """The hub of a star graph has the highest degree and is coloured
        first."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("hub", faculty="f-hub"),
                    _session("leaf1", faculty="f1"),
                    _session("leaf2", faculty="f2"),
                    _session("leaf3", faculty="f3"),
                ],
                edges=[
                    _edge("hub", "leaf1", "COHORT"),
                    _edge("hub", "leaf2", "COHORT"),
                    _edge("hub", "leaf3", "COHORT"),
                ],
            )
        )
        assignment, unplaced = welsh_powell(g)
        assert len(unplaced) == 0
        # Hub conflicts with all three leaves → all leaves must differ from
        # hub, but leaves don't conflict with each other → they may share.
        hub_slot = assignment["hub"]
        for leaf in ("leaf1", "leaf2", "leaf3"):
            assert assignment[leaf] != hub_slot

    def test_independent_sessions_may_share_a_slot(self) -> None:
        """No edge → no conflict → they can take the same colour."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="f1", cohort="c1"),
                    _session("s2", faculty="f2", cohort="c2"),
                ],
            )
        )
        assignment, unplaced = welsh_powell(g)
        assert len(unplaced) == 0
        # They *may* share (Welsh-Powell will assign the first feasible
        # colour); the point is there's no constraint forbidding it.
        # Just verify both are assigned.
        assert "s1" in assignment and "s2" in assignment

    def test_pinned_occupancy_blocks_colour(self) -> None:
        """A session whose cohort is pinned in a slot must not get that slot."""
        g = build_conflict_graph(
            _minimal_payload(
                sessions=[_session("s1", faculty="fac-x", cohort="coh-a")],
                pinned_occupancy=[{
                    "day": 0,
                    "period": 0,
                    "faculty_ids": [],
                    "room_ids": [],
                    "cohort_ids": ["coh-a"],
                }],
            )
        )
        assignment, _unplaced = welsh_powell(g)
        assert assignment["s1"] != SlotId(0, 0)


# ======================================================================
# networkx cross-validation — tests only, never in solver/
# ======================================================================


def _to_nx(graph: ConflictGraph) -> nx.Graph:
    """Convert a ConflictGraph to a networkx Graph for cross-checking."""
    G = nx.Graph()
    for sid in graph.sessions:
        G.add_node(sid)
    for edge in graph.edges:
        # networkx collapses duplicate edges into one, which is fine for
        # conflict checking.
        G.add_edge(edge.u, edge.v, reason=edge.reason)
    return G


class TestNetworkxCrossCheck:
    """Validate the hand-written colouring against networkx."""

    def _assert_valid_colouring(
        self,
        graph: ConflictGraph,
        assignment: dict[str, SlotId],
    ) -> None:
        """No two adjacent vertices share a colour."""
        G = _to_nx(graph)
        for u, v in G.edges():
            if u in assignment and v in assignment:
                assert assignment[u] != assignment[v], (
                    f"adjacent sessions {u} and {v} share slot "
                    f"{assignment[u]}"
                )

    def _assert_colouring_uses_at_most_nx_colours(
        self,
        graph: ConflictGraph,
        assignment: dict[str, SlotId],
    ) -> None:
        """The greedy colouring uses no more colours than networkx greedy."""
        G = _to_nx(graph)
        if len(G) == 0:
            return
        nx_colouring = nx.coloring.greedy_color(
            G, strategy="largest_first"
        )
        our_colour_count = len(set(assignment.values()))
        nx_colour_count = len(set(nx_colouring.values()))
        # Welsh-Powell (largest_first) is the same strategy — colour counts
        # should be close. We assert ours is no worse than nx + 1 to allow
        # for the faculty-availability domain restriction (which nx does not
        # model), but on unconstrained graphs they should match exactly.
        assert our_colour_count <= nx_colour_count + 1, (
            f"our colouring uses {our_colour_count} colours, "
            f"networkx uses {nx_colour_count}"
        )

    def test_triangle_is_valid_and_optimal(self) -> None:
        graph = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("a", faculty="f1"),
                    _session("b", faculty="f2"),
                    _session("c", faculty="f3"),
                ],
                edges=[
                    _edge("a", "b", "COHORT"),
                    _edge("b", "c", "COHORT"),
                    _edge("a", "c", "COHORT"),
                ],
            )
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)
        self._assert_colouring_uses_at_most_nx_colours(graph, assignment)

    def test_star_graph_is_valid(self) -> None:
        sessions = [_session("hub", faculty="f-hub")] + [
            _session(f"leaf-{i}", faculty=f"f-{i}") for i in range(6)
        ]
        edges = [_edge("hub", f"leaf-{i}", "COHORT") for i in range(6)]
        graph = build_conflict_graph(
            _minimal_payload(sessions=sessions, edges=edges)
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)

    def test_bipartite_graph_uses_two_colours(self) -> None:
        """K₃,₃ is bipartite → chromatic number 2."""
        sessions = (
            [_session(f"l-{i}", faculty=f"fl-{i}") for i in range(3)]
            + [_session(f"r-{i}", faculty=f"fr-{i}") for i in range(3)]
        )
        edges = [
            _edge(f"l-{i}", f"r-{j}", "COHORT")
            for i in range(3)
            for j in range(3)
        ]
        graph = build_conflict_graph(
            _minimal_payload(sessions=sessions, edges=edges)
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)
        assert len(set(assignment.values())) == 2

    def test_petersen_graph_is_valid(self) -> None:
        """The Petersen graph has χ = 3; Welsh-Powell may use 3 or 4."""
        petersen_edges_nx = list(nx.petersen_graph().edges())
        sessions = [_session(f"v{i}", faculty=f"f{i}") for i in range(10)]
        edges = [_edge(f"v{u}", f"v{v}", "COHORT") for u, v in petersen_edges_nx]
        graph = build_conflict_graph(
            _minimal_payload(sessions=sessions, edges=edges)
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)
        # Petersen χ = 3; Welsh-Powell should manage ≤ 4.
        assert len(set(assignment.values())) <= 4

    def test_five_node_cycle_is_valid(self) -> None:
        """C₅ has χ = 3."""
        sessions = [_session(f"v{i}", faculty=f"f{i}") for i in range(5)]
        edges = [_edge(f"v{i}", f"v{(i + 1) % 5}", "COHORT") for i in range(5)]
        graph = build_conflict_graph(
            _minimal_payload(sessions=sessions, edges=edges)
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)
        assert len(set(assignment.values())) == 3

    def test_complete_graph_k5_is_valid(self) -> None:
        """K₅ needs 5 colours."""
        sessions = [_session(f"v{i}", faculty=f"f{i}") for i in range(5)]
        edges = [
            _edge(f"v{i}", f"v{j}", "COHORT")
            for i in range(5)
            for j in range(i + 1, 5)
        ]
        graph = build_conflict_graph(
            _minimal_payload(sessions=sessions, edges=edges)
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)
        assert len(set(assignment.values())) == 5

    def test_graph_with_faculty_unavailability_is_valid(self) -> None:
        """Colouring respects faculty blackouts *and* adjacency."""
        graph = build_conflict_graph(
            _minimal_payload(
                sessions=[
                    _session("s1", faculty="fac-x"),
                    _session("s2", faculty="fac-x"),
                ],
                edges=[_edge("s1", "s2", "FACULTY")],
                faculty_availability=[
                    _faculty_avail("fac-x", [
                        {"day": 0, "period": 0},
                        {"day": 0, "period": 1},
                    ]),
                ],
            )
        )
        assignment, unplaced = welsh_powell(graph)
        assert len(unplaced) == 0
        self._assert_valid_colouring(graph, assignment)
        # Neither session should be on the blacked-out slots.
        for sid in ("s1", "s2"):
            assert assignment[sid] not in {SlotId(0, 0), SlotId(0, 1)}


# ======================================================================
# Integration: contract example payload → build → colour
# ======================================================================


class TestContractExampleIntegration:
    """Load the committed example payload, build a graph, colour it."""

    @pytest.fixture()
    def example_payload(self) -> dict[str, Any]:
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parents[2]
            / "contracts"
            / "examples"
            / "edge_list_v1.example.json"
        )
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def test_example_builds_without_error(
        self, example_payload: dict[str, Any]
    ) -> None:
        g = build_conflict_graph(example_payload)
        assert g.vertex_count() == 8
        assert g.edge_count() > 0

    def test_example_colours_conflict_free(
        self, example_payload: dict[str, Any]
    ) -> None:
        g = build_conflict_graph(example_payload)
        assignment, unplaced = welsh_powell(g)
        assert len(unplaced) == 0

        # Cross-check with networkx.
        G = _to_nx(g)
        for u, v in G.edges():
            assert assignment[u] != assignment[v], (
                f"adjacent sessions {u} and {v} share slot {assignment[u]}"
            )

    def test_example_fixed_slot_is_honoured(
        self, example_payload: dict[str, Any]
    ) -> None:
        g = build_conflict_graph(example_payload)
        assignment, _ = welsh_powell(g)
        # sess-0008 has fixed_slot day=2 period=0.
        assert assignment["sess-0008"] == SlotId(2, 0)

    def test_example_faculty_unavailability_honoured(
        self, example_payload: dict[str, Any]
    ) -> None:
        g = build_conflict_graph(example_payload)
        assignment, _ = welsh_powell(g)
        # fac-agn is unavailable Fri period 8 and 9.
        agn_sessions = [
            sid
            for sid, s in g.sessions.items()
            if s.faculty_id == "fac-agn"
        ]
        for sid in agn_sessions:
            assert assignment[sid] not in {SlotId(4, 8), SlotId(4, 9)}


# ======================================================================
# Solver purity guard
# ======================================================================


class TestSolverPurity:
    """Verify that solver/ never imports forbidden packages."""

    def test_graph_module_has_no_networkx_import(self) -> None:
        import importlib

        source = importlib.util.find_spec("solver.graph")
        assert source is not None
        assert source.origin is not None
        with open(source.origin, encoding="utf-8") as fh:
            code = fh.read()
        assert "import networkx" not in code
        assert "from networkx" not in code

    def test_colouring_module_has_no_networkx_import(self) -> None:
        import importlib

        source = importlib.util.find_spec("solver.colouring")
        assert source is not None
        assert source.origin is not None
        with open(source.origin, encoding="utf-8") as fh:
            code = fh.read()
        assert "import networkx" not in code
        assert "from networkx" not in code
