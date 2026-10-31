"""repair() (S14a): a changed timetable stays valid and moves as little as it can.

Run on the committed real EVEN timetable (``solution.json``) with the changes of
``solver/benchmarks/real_repair.py`` and on the seeded property instances that
backtracking solves (fixed slots, lab blocks, sub-rooms, pins). repair() checks
its own result with the validator; these tests check it again against
:func:`solver.repair.apply_change`, and against the ``solution.v2`` schema.

S14e: protected pins, substitutes (``substitute_candidates`` and the
``substitute_faculty`` change). The full real explanation (Kurhade all Tuesday)
is ``slow``; the default run explains it with no search nodes.
"""

from __future__ import annotations

import copy
import json
import random
import time

import pytest

import solver.backtracking
from solver.backtracking import backtrack_solve
from solver.benchmarks.real_repair import CE207, INSTANCE, SCENARIOS, TEACHING
from solver.graph import build_conflict_graph
from solver.mus import apply_action, explain
from solver.repair import apply_change, repair, substitute_candidates
from solver.scoring import score
from solver.slots import SlotId
from solver.tests.test_property_solved_is_valid import SEED, generate_instance
from solver.tests.test_solution_v2 import SOLUTION_V2
from solver.validate import validate_solution

CHANGES = dict(SCENARIOS)
KURHADE_TUESDAY = CHANGES["Swapnali Kurhade unavailable all Tuesday"]
LAB_603_MONDAY = CHANGES["Lab 603 unavailable all Monday"]
FREE_DRAG = CHANGES["CE207 lecture dragged to a free slot (Wed 09.00, 601)"]
FROZEN_DRAG = CHANGES["CE207 lecture dragged onto SE-Comp A's frozen MDM-I lab (Mon 09.00, 605)"]
BUSY_DRAG = CHANGES["CE207 lecture dragged onto an occupied slot (Mon 17.15, 605)"]
# S14e: onto SE lunch (Wed P5, display.json pins[5]), and onto 609 at Thu P3, which a frozen
# out-of-scope session holds (D35, pins[226]) while SE-Comp A and Anant Nimkar are free
LUNCH_DRAG = {"kind": "move_session", "session_id": CE207, "day": 2, "period": 5,
              "room_id": "room-605", "sub_room_id": None}
ROOM_DRAG = {"kind": "move_session", "session_id": CE207, "day": 3, "period": 3,
             "room_id": "room-609", "sub_room_id": None}


@pytest.fixture(scope="module")
def real() -> tuple[dict, dict]:
    edge_list = json.loads((INSTANCE / "edge_list.json").read_text(encoding="utf-8"))
    solution = json.loads((INSTANCE / "solution.json").read_text(encoding="utf-8"))
    return edge_list, solution


@pytest.fixture(scope="module")
def display() -> dict:
    return json.loads((INSTANCE / "display.json").read_text(encoding="utf-8"))


def _by_id(solution: dict) -> dict[str, dict]:
    return {p["session_id"]: p for p in solution["assignment"]}


def _starts(solution: dict) -> dict[str, SlotId]:
    return {p["session_id"]: SlotId(p["day"], p["period"]) for p in solution["assignment"]}


def _sub(session_id: str, faculty_id: str) -> dict:
    return {"kind": "substitute_faculty", "session_id": session_id, "faculty_id": faculty_id}


def _check(edge_list: dict, solution: dict, change: dict, stats: dict | None = None,
           **options: object) -> dict:
    """repair() on copies; inputs untouched, result schema-valid, valid if solved,
    ``displaced`` exactly the sessions whose slot changed."""
    payload, before = copy.deepcopy(edge_list), copy.deepcopy(solution)
    result = repair(payload, before, change, stats=stats, **options)
    assert payload == edge_list and before == solution
    SOLUTION_V2.validate(result)
    if result["status"] == "solved":
        assert validate_solution(apply_change(edge_list, change), result) == []
        old, new = _by_id(solution), _by_id(result)
        assert result["displaced"] == sorted(
            sid for sid in new
            if (new[sid]["day"], new[sid]["period"]) != (old[sid]["day"], old[sid]["period"])
        )
    return result


def test_free_drag_moves_only_the_dragged_lecture(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    result = _check(edge_list, solution, FREE_DRAG)
    assert result["displaced"] == [CE207]
    new, old = _by_id(result), _by_id(solution)
    assert new.pop(CE207) == {"session_id": CE207, "day": 2, "period": 0,
                              "room_id": "room-601", "sub_room_id": None}
    assert all(new[sid] == old[sid] for sid in new)  # nothing else moved, not even a room
    assert result["metadata"]["algorithm"].startswith("freeze-and-expand")


def test_busy_drag_moves_what_is_in_the_way_and_keeps_the_rest(
        real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    stats: dict = {}
    result = _check(edge_list, solution, BUSY_DRAG, stats)
    assert {CE207, "obs-t0-r5-c4-l0", "obs-t6-r1-c5-l0"} <= set(stats["hit"])
    assert _by_id(result)[CE207]["day"] == 0 and _by_id(result)[CE207]["period"] == 9
    old, new = _by_id(solution), _by_id(result)
    kept = [sid for sid in old if new[sid] == old[sid]]
    assert len(kept) >= len(old) - 10


def test_lab_603_monday_empties_603_and_moves_few(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    stats: dict = {}
    result = _check(edge_list, solution, LAB_603_MONDAY, stats)
    assert stats["hit"]  # 603 was in use on Monday
    assert not any(p["room_id"] == "room-603" and p["day"] == 0 for p in result["assignment"])
    old, new = _by_id(solution), _by_id(result)
    assert sum(new[sid] != old[sid] for sid in old) <= 10  # 156 sessions, 7 hit


def test_drag_onto_a_frozen_item_names_the_pin(real: tuple[dict, dict]) -> None:
    """S14b pre-check: SE-Comp A's frozen MDM-I lab is blamed, not Anant Nimkar,
    before any search, with a proven-minimal set and a verified relaxation."""
    edge_list, solution = real
    stats: dict = {}
    result = _check(edge_list, solution, FROZEN_DRAG, stats)
    diagnosis = result["diagnosis"]
    assert result["status"] == "infeasible" and diagnosis["method"] == "mus"
    assert stats["rings"] == [] and stats["mus"]["proven_minimal"]
    members = {m["constraint_id"]: m for m in diagnosis["minimal_conflicting_set"]}
    assert set(members) == {"pin.238", "change"}
    display = json.loads((INSTANCE / "display.json").read_text(encoding="utf-8"))
    assert display["pins"][238]["source_ref"] == "pin-t0-r1-c1-l0"  # "MDM - I LABs", Mon P0-P1
    assert "coh-se-a" in members["pin.238"]["entity_ids"]
    assert members["change"]["kind"] == "FIXED_SLOT"
    assert members["change"]["entity_ids"] == [CE207, "room-605"]
    relaxation = diagnosis["suggested_relaxation"]
    assert relaxation["action"] == {"action_type": "RELAX_PINNED_BLOCK", "params": {
        "slot": {"day": 0, "period": 0}, "entity_kind": "cohort", "entity_id": "coh-se-a"}}
    assert relaxation["verification"]["status"] == "restored"
    # independently: with SE-Comp A freed from that pin the drag repairs
    relaxed = apply_action(edge_list, relaxation["action"])
    assert repair(relaxed, solution, FROZEN_DRAG)["status"] == "solved"


def test_drag_onto_a_pinned_room_names_the_pin(real: tuple[dict, dict], display: dict) -> None:
    """S14e: only the dropped room is pinned (609 at Thu P3, a frozen out-of-scope
    session, D35): the pin is blamed through the room and the room is freed."""
    edge_list, solution = real
    pin = edge_list["pinned_occupancy"][226]
    assert (pin["day"], pin["period"], pin["room_ids"]) == (3, 3, ["room-609"])
    assert "coh-se-a" not in pin["cohort_ids"] and "fac-anant-nimkar" not in pin["faculty_ids"]
    assert display["pins"][226]["kind"] == "out_of_scope"
    assert display["pins"][226]["source_ref"] == "oos-t19-r4-c4-l0"
    stats: dict = {}
    result = _check(edge_list, solution, ROOM_DRAG, stats)
    diagnosis = result["diagnosis"]
    assert result["status"] == "infeasible" and diagnosis["method"] == "mus"
    assert stats["rings"] == [] and stats["mus"]["proven_minimal"]
    members = {m["constraint_id"]: m for m in diagnosis["minimal_conflicting_set"]}
    assert set(members) == {"pin.226", "change"}
    assert members["change"]["entity_ids"] == [CE207, "room-609"]
    relaxation = diagnosis["suggested_relaxation"]
    assert relaxation["action"] == {"action_type": "RELAX_PINNED_BLOCK", "params": {
        "slot": {"day": 3, "period": 3}, "entity_kind": "room", "entity_id": "room-609"}}
    assert relaxation["verification"]["status"] == "restored"
    relaxed = apply_action(edge_list, relaxation["action"])
    assert repair(relaxed, solution, ROOM_DRAG)["status"] == "solved"


def test_a_protected_lunch_is_never_suggested(real: tuple[dict, dict], display: dict) -> None:
    """S14e: the lecture dragged onto SE lunch. Today's suggestion frees SE-Comp A
    from that lunch; with display.json's lunch pins protected, as the backend will
    pass them (D41), the lunch stays in the set and the suggestion is MANUAL."""
    edge_list, solution = real
    lunch = [i for i, pin in enumerate(display["pins"]) if pin["kind"] == "lunch"]
    assert 5 in lunch and display["pins"][5]["unique_label"] == "SE lunch, Wed P5"
    today = _check(edge_list, solution, LUNCH_DRAG)["diagnosis"]["suggested_relaxation"]
    assert today["action"] == {"action_type": "RELAX_PINNED_BLOCK", "params": {
        "slot": {"day": 2, "period": 5}, "entity_kind": "cohort", "entity_id": "coh-se-a"}}
    assert today["verification"]["status"] == "restored"

    stats: dict = {}
    result = _check(edge_list, solution, LUNCH_DRAG, stats, protected=lunch)
    diagnosis = result["diagnosis"]
    assert diagnosis["method"] == "mus"
    assert {m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]} == {"pin.5",
                                                                                  "change"}
    relaxation = diagnosis["suggested_relaxation"]
    assert relaxation["action"] == {"action_type": "MANUAL", "params": {}}
    assert relaxation["verification"] == {"status": "not_attempted", "runtime_ms": None}
    assert relaxation["constraint_id"] == "change"  # the first member not protected
    assert stats["mus"]["relaxations"] == []
    with pytest.raises(ValueError, match="protected"):
        repair(edge_list, solution, LUNCH_DRAG, protected=[len(edge_list["pinned_occupancy"])])


def test_kurhade_tuesday_is_explained_fast(real: tuple[dict, dict]) -> None:
    """The slow test's change explained with no search nodes (``mus_nodes=0``): pre-solve
    alone keeps her Monday off, the absence and her clash in the set but shows no member
    necessary, so the set is proven infeasible, not minimal, and nothing is verified."""
    stats: dict = {}
    result = _check(*real, KURHADE_TUESDAY, stats, mus_nodes=0)
    diagnosis = result["diagnosis"]
    assert result["status"] == "infeasible" and stats["rings"][-1][0] == "all"
    members = {m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]}
    assert {"change", "unavailable.fac-swapnali-kurhade.0",
            "faculty_clash.fac-swapnali-kurhade"} <= members
    assert diagnosis["method"] == "presolve" and not stats["mus"]["proven_minimal"]
    assert set(stats["mus"]["unknown"]) == members - {"change"}  # the known timetable needs it
    relaxation = diagnosis["suggested_relaxation"]
    assert relaxation["action"]["action_type"] == "MANUAL"
    assert relaxation["constraint_id"] != "change"


@pytest.fixture(scope="module")
def kurhade(real: tuple[dict, dict]) -> tuple[dict, dict]:
    stats: dict = {}
    return _check(*real, KURHADE_TUESDAY, stats), stats


@pytest.mark.slow
def test_kurhade_tuesday_is_explained(kurhade: tuple[dict, dict]) -> None:
    """Her declared Monday off, the Tuesday absence and her not teaching two
    classes at once are in the set; the set is proven infeasible, and is called
    minimal only if every member was shown necessary."""
    result, stats = kurhade
    diagnosis = result["diagnosis"]
    assert result["status"] == "infeasible"
    assert stats["rings"][-1][0] == "all"  # only the run with everything free decides
    members = {m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]}
    assert {"change", "unavailable.fac-swapnali-kurhade.0",
            "faculty_clash.fac-swapnali-kurhade"} <= members
    assert diagnosis["method"] == ("mus" if stats["mus"]["proven_minimal"] else "presolve")
    assert set(stats["mus"]["unknown"]) <= members
    relaxation = diagnosis["suggested_relaxation"]
    restored = [a for a in stats["mus"]["relaxations"]
                if a["verification"]["status"] == "restored"]
    if relaxation["action"]["action_type"] == "MANUAL":
        assert restored == []
    else:
        assert restored == [relaxation]
    assert relaxation["constraint_id"] != "change"  # the absence itself is never relaxed


def test_a_change_that_hits_nothing_keeps_the_timetable(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    used = {(p["day"], p["period"]) for p in solution["assignment"]
            if p["room_id"] == "room-603"}
    idle = next((d, p) for d in range(5) for p in TEACHING if (d, p) not in used)
    change = {"kind": "room_unavailable", "room_id": "room-603",
              "slots": [{"day": idle[0], "period": idle[1]}]}
    result = _check(edge_list, solution, change)
    assert result["assignment"] == solution["assignment"]
    assert result["displaced"] == []
    assert result["quality"] == solution["quality"]


def test_deterministic(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    for change in (LAB_603_MONDAY, BUSY_DRAG, FROZEN_DRAG, _sub(CE207, "fac-sudhir-dhage")):
        runs = [repair(edge_list, solution, change) for _ in range(2)]
        for run in runs:
            run["metadata"].pop("runtime_ms")
            if run["status"] == "infeasible":
                run["diagnosis"]["suggested_relaxation"]["verification"].pop("runtime_ms")
        assert runs[0] == runs[1]


def test_a_timeout_is_never_infeasible(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    with pytest.raises(TimeoutError):
        repair(edge_list, solution, LAB_603_MONDAY, time_limit_s=0.0)


def test_rejects_bad_input(real: tuple[dict, dict]) -> None:
    edge_list, solution = real
    for change in (
        {"kind": "teacher_sick"},
        {"kind": "faculty_unavailable", "faculty_id": "fac-nobody", "slots": [{"day": 0,
                                                                               "period": 0}]},
        {"kind": "room_unavailable", "room_id": "room-603", "slots": []},
        {"kind": "room_unavailable", "room_id": "room-603", "slots": [{"day": 7, "period": 0}]},
        {**FREE_DRAG, "session_id": "obs-nothing"},
        {**FREE_DRAG, "room_id": "room-nowhere"},
        _sub("obs-nothing", "fac-sudhir-dhage"),
        _sub(CE207, "fac-nobody"),
        _sub(CE207, "fac-anant-nimkar"),  # already teaches it
    ):
        with pytest.raises(ValueError):
            repair(edge_list, solution, change)
    with pytest.raises(ValueError, match="solved timetable"):
        repair(edge_list, {**solution, "status": "infeasible"}, FREE_DRAG)


def test_preferred_values_reproduce_a_valid_timetable(real: tuple[dict, dict]) -> None:
    """backtrack_solve(prefer=...) tries the old place first, so a still-valid
    timetable comes back unchanged."""
    edge_list, solution = real
    old = {p["session_id"]: (SlotId(p["day"], p["period"]), p["sub_room_id"] or p["room_id"])
           for p in solution["assignment"]}
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list, prefer=old)
    assert result.solved
    assert {sid: (result.assignment[sid], result.room_assignment[sid]) for sid in old} == old


def test_property_instances() -> None:
    """Random changes on solved property instances: valid or diagnosed, and when the
    hit sessions alone could be re-placed, nothing else moved."""
    solved = infeasible = frozen_only = 0
    for i in range(120):
        rng = random.Random(SEED + i)
        edge_list = generate_instance(rng)
        result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
        if not result.solved:
            continue
        solution = result.to_solution_v2_dict()
        target = rng.choice(solution["assignment"])
        session = next(s for s in edge_list["sessions"] if s["id"] == target["session_id"])
        cell = [{"day": target["day"], "period": target["period"]}]
        grid = edge_list["slot_grid"]
        change = [
            {"kind": "faculty_unavailable", "faculty_id": session["faculty_id"], "slots": cell},
            {"kind": "room_unavailable", "room_id": target["sub_room_id"] or target["room_id"],
             "slots": cell},
            {"kind": "move_session", "session_id": session["id"],
             "day": rng.randrange(grid["days"]), "period": rng.choice(grid["teaching_periods"]),
             "room_id": target["room_id"], "sub_room_id": target["sub_room_id"]},
        ][i % 3]
        stats: dict = {}
        repaired = _check(edge_list, solution, change, stats)
        if repaired["status"] == "infeasible":
            infeasible += 1
            assert stats["rings"][-1][0] == "all" or (stats["rings"] == []
                                                      and change["kind"] == "move_session")
            continue
        solved += 1
        if stats["rings"][-1][0] == 0:
            frozen_only += 1
            assert set(repaired["displaced"]) <= set(stats["hit"])
    assert solved >= 20 and infeasible >= 1 and frozen_only >= 5


# --- S14e: substitutes (D53) ---------------------------------------------------------------


def _fits(edge_list: dict, solution: dict, session_id: str, faculty_id: str) -> bool:
    """The validator, not substitute_candidates, on whether the timetable survives the swap."""
    changed = apply_change(edge_list, _sub(session_id, faculty_id))
    return validate_solution(changed, solution) == []


def test_substitute_faculty_redraws_the_faculty_edges() -> None:
    """The session gets the new teacher; its FACULTY edges join it to exactly the new
    teacher's other sessions; nothing else changes; the input is left alone."""
    edge_list = generate_instance(random.Random(SEED))
    before = copy.deepcopy(edge_list)
    sid = edge_list["sessions"][0]["id"]
    new = next(a["faculty_id"] for a in edge_list["faculty_availability"]
               if a["faculty_id"] != edge_list["sessions"][0]["faculty_id"])
    changed = apply_change(edge_list, _sub(sid, new))
    assert edge_list == before
    taught = {s["id"]: s["faculty_id"] for s in changed["sessions"]}
    assert taught == {**{s["id"]: s["faculty_id"] for s in before["sessions"]}, sid: new}

    def faculty_pairs(payload: dict) -> set[frozenset[str]]:
        return {frozenset((e["u"], e["v"])) for e in payload["edges"] if e["reason"] == "FACULTY"}

    ids = sorted(taught)
    same_teacher = {frozenset((a, b)) for i, a in enumerate(ids) for b in ids[i + 1:]
                    if taught[a] == taught[b]}
    assert faculty_pairs(changed) == same_teacher
    assert {p for p in faculty_pairs(changed) if sid not in p} == {
        p for p in faculty_pairs(before) if sid not in p}
    assert ([e for e in changed["edges"] if e["reason"] != "FACULTY"]
            == [e for e in before["edges"] if e["reason"] != "FACULTY"])


def test_substitute_candidates_property_instances() -> None:
    """Everyone in the instance as 'qualified': exactly those under whom the validator
    accepts the unchanged timetable, each with its score change, best first."""
    fit = clash = 0
    for i in range(30):
        rng = random.Random(SEED + i)
        edge_list = generate_instance(rng)
        result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
        if not result.solved:
            continue
        solution = result.to_solution_v2_dict()
        session = rng.choice(edge_list["sessions"])
        everyone = [a["faculty_id"] for a in edge_list["faculty_availability"]]
        found = substitute_candidates(edge_list, solution, session["id"], iter(everyone * 2))
        others = sorted(set(everyone) - {session["faculty_id"]})
        expected = [f for f in others if _fits(edge_list, solution, session["id"], f)]
        fit, clash = fit + len(expected), clash + len(others) - len(expected)
        assert sorted(c["faculty_id"] for c in found) == expected
        assert found == sorted(found, key=lambda c: (-c["score_change"], c["faculty_id"]))
        now = score(edge_list, _starts(solution))["score"]
        for c in found:
            changed = apply_change(edge_list, _sub(session["id"], c["faculty_id"]))
            assert c["score_change"] == score(changed, _starts(solution))["score"] - now
    assert fit >= 10 and clash >= 5  # 24 and 8 with these seeds


def test_substitution_repair_property_instances() -> None:
    """A substitute who fits changes no placement; one who does not is repaired like any
    change (something changes slot), or explained without relaxing the substitution."""
    fit = repaired = explained = 0
    for i in range(40):
        rng = random.Random(SEED + i)
        edge_list = generate_instance(rng)
        result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
        if not result.solved:
            continue
        solution = result.to_solution_v2_dict()
        session = rng.choice(edge_list["sessions"])
        others = sorted({a["faculty_id"] for a in edge_list["faculty_availability"]}
                        - {session["faculty_id"]})
        for fid in others:
            stats: dict = {}
            out = _check(edge_list, solution, _sub(session["id"], fid), stats)
            if _fits(edge_list, solution, session["id"], fid):
                fit += 1
                assert out["assignment"] == solution["assignment"] and stats["hit"] == []
            elif out["status"] == "solved":
                repaired += 1
                assert session["id"] in stats["hit"] and out["displaced"]
            else:
                explained += 1
                members = {m["constraint_id"] for m in out["diagnosis"]["minimal_conflicting_set"]}
                assert "change" not in members  # background, never relaxed
    assert fit >= 10 and repaired >= 5 and explained >= 1  # 28, 7 and 5 with these seeds


def overloaded_substitute() -> tuple[dict, dict]:
    """g teaches both periods of the only day; f's lecture handed to g fits nowhere."""
    sessions = [{"id": sid, "subject_id": "subj", "faculty_id": fid, "cohort_id": cohort,
                 "session_type": "theory", "duration_periods": 1, "cohort_size": 30,
                 "requires_lab": False, "fixed_slot": None}
                for sid, fid, cohort in (("a", "f", "c0"), ("b0", "g", "c1"), ("b1", "g", "c2"))]
    edge_list = {
        "schema_version": "edge_list.v1",
        "slot_grid": {"days": 1, "periods_per_day": 2, "teaching_periods": [0, 1],
                      "adjacency": [[0, 1]]},
        "sessions": sessions,
        "edges": [{"u": "b0", "v": "b1", "reason": "FACULTY"}],
        "rooms": [{"id": f"r{i}", "code": f"R{i}", "capacity": 30, "is_lab": False,
                   "parent_room_id": None} for i in range(3)],
        "faculty_availability": [{"faculty_id": f, "unavailable_slots": []} for f in "fg"],
        "lab_blocks": [],
        "pinned_occupancy": [],
    }
    result = backtrack_solve(build_conflict_graph(edge_list), edge_list)
    assert result.solved
    return edge_list, result.to_solution_v2_dict()


def test_an_impossible_substitution_is_explained() -> None:
    """Repaired as usual: nothing fits even with everything free, so it is explained,
    and the set names g's clash, not the substitution (background)."""
    edge_list, solution = overloaded_substitute()
    assert substitute_candidates(edge_list, solution, "a", ["f", "g"]) == []
    stats: dict = {}
    result = _check(edge_list, solution, _sub("a", "g"), stats)
    diagnosis = result["diagnosis"]
    assert result["status"] == "infeasible" and stats["rings"][-1][0] == "all"
    assert [m["constraint_id"] for m in diagnosis["minimal_conflicting_set"]] == [
        "faculty_clash.g"]
    assert diagnosis["suggested_relaxation"]["action"]["action_type"] == "MANUAL"


def test_substitute_candidates_rejects_bad_input() -> None:
    edge_list, solution = overloaded_substitute()
    for session_id, qualified in (("nothing", ["f"]), ("a", ["f", "nobody"])):
        with pytest.raises(ValueError):
            substitute_candidates(edge_list, solution, session_id, qualified)
    with pytest.raises(ValueError, match="solved timetable"):
        substitute_candidates(edge_list, {**solution, "status": "infeasible"}, "a", ["g"])


def _ce207_teachers(edge_list: dict) -> list[str]:
    """Mechanism check, NOT SPIT data: the instance's own CE207 teachers stand in for the
    qualified list, which Track B reads from SPIT's faculty-subject sheets in S14f (D53)."""
    subject = next(s["subject_id"] for s in edge_list["sessions"] if s["id"] == CE207)
    return sorted({s["faculty_id"] for s in edge_list["sessions"] if s["subject_id"] == subject})


def test_substitute_candidates_on_the_real_timetable(real: tuple[dict, dict]) -> None:
    """Who of CE207's instance teachers could take Anant Nimkar's SE-Comp A lecture
    (Thu P1, 701): not he himself, not Nataasha Raul, who teaches elsewhere then."""
    edge_list, solution = real
    qualified = _ce207_teachers(edge_list)
    assert qualified == ["fac-anant-nimkar", "fac-nataasha-raul", "fac-prasenjit-bhavathankar",
                         "fac-sudhir-dhage"]
    found = substitute_candidates(edge_list, solution, CE207, qualified)
    assert [c["faculty_id"] for c in found] == ["fac-sudhir-dhage"]
    now = score(edge_list, _starts(solution))["score"]
    for c in found:
        assert _fits(edge_list, solution, CE207, c["faculty_id"])
        changed = apply_change(edge_list, _sub(CE207, c["faculty_id"]))
        assert c["score_change"] == score(changed, _starts(solution))["score"] - now
    busy = validate_solution(apply_change(edge_list, _sub(CE207, "fac-nataasha-raul")), solution)
    assert {v.kind for v in busy} == {"FACULTY_CLASH"}


def test_substitution_repair_on_the_real_timetable(real: tuple[dict, dict]) -> None:
    """A free substitute keeps every placement and is scored with the new teacher; a busy
    one moves only the lecture."""
    edge_list, solution = real
    free = _sub(CE207, "fac-sudhir-dhage")
    stats: dict = {}
    kept = _check(edge_list, solution, free, stats)
    assert stats["hit"] == [] and kept["displaced"] == []
    assert kept["assignment"] == solution["assignment"]
    assert kept["quality"] == score(apply_change(edge_list, free), _starts(solution))

    stats = {}
    moved = _check(edge_list, solution, _sub(CE207, "fac-nataasha-raul"), stats)
    assert stats["hit"] == [CE207] and moved["displaced"] == [CE207]
    old, new = _by_id(solution), _by_id(moved)
    assert all(new[sid] == old[sid] for sid in old if sid != CE207)


# --- S14k: deadlines ------------------------------------------------------------------------

# S15c's change 9 (bench/repair_vs_regen.py, seed 0), whose explanation ran over 20 minutes
SUDEEP_MALI = {"kind": "faculty_unavailable", "faculty_id": "fac-sudeep-mali",
               "slots": [{"day": 0, "period": 6}, {"day": 0, "period": 7}, {"day": 3, "period": 5}]}
MARGIN_S = 3.0  # the check in flight when the deadline passes, then the result is assembled


def test_a_fresh_infeasible_solve_is_explained_within_its_limit(real: tuple[dict, dict]) -> None:
    """explain() alone, as an infeasible solve job (S14i) calls it: a fresh solve of the
    changed edge list, proved by pre-solve; a 1 s deadline cuts the explanation and
    leaves the verdict alone."""
    changed = apply_change(real[0], SUDEEP_MALI)
    fresh = backtrack_solve(build_conflict_graph(changed), changed).to_solution_v2_dict()
    assert fresh["diagnosis"]["method"] == "presolve"
    stats: dict = {}
    began = time.perf_counter()
    out = explain(changed, fresh, time_limit_s=1.0, stats=stats)
    assert time.perf_counter() - began < 1.0 + MARGIN_S
    assert out is not None
    SOLUTION_V2.validate(out)
    assert out == fresh or (stats["cut"] and out["diagnosis"]["method"] == "presolve")


@pytest.mark.slow
def test_the_twenty_minute_change_ends_within_its_limit(real: tuple[dict, dict]) -> None:
    """repair(time_limit_s=10) on change 9: the whole call, explanation included, ends
    within the limit plus the margin, and the change is still infeasible (pre-solve)."""
    stats: dict = {}
    began = time.perf_counter()
    result = _check(*real, SUDEEP_MALI, stats, time_limit_s=10.0)
    assert time.perf_counter() - began < 10.0 + MARGIN_S
    assert result["status"] == "infeasible" and stats["rings"][-1] == ["all", 156, "infeasible"]
    method = result["diagnosis"]["method"]
    assert method == ("presolve" if stats["mus"]["cut"] else "mus")


# --- S14l: the repair timeout S14i found ------------------------------------------------------

KURHADE_AFTERNOON = CHANGES["Swapnali Kurhade unavailable Tuesday afternoon (P5-P9)"]
WED_P0_601 = {"kind": "move_session", "session_id": CE207, "day": 2, "period": 0,
              "room_id": "room-601", "sub_room_id": None}


@pytest.mark.slow
def test_the_accumulated_drag_times_out_though_feasible(
        real: tuple[dict, dict], monkeypatch: pytest.MonkeyPatch) -> None:
    """S14i's sequence, accepted changes accumulating (D52): Kurhade unavailable Tuesday
    afternoon; Prasenjit Bhavathankar takes the SE-Comp A CE207 lecture; that lecture is
    dragged to Wed P0 in 601. The last repair's every-session-free search does not settle
    within its limit, so it is a timeout, never infeasible (D33). The drag is feasible: with
    sub-rooms tried before a whole split lab (D58) a fresh solve finds a valid timetable
    (docs/repair-even-2025-26.md, S14l)."""
    edge_list, solution = real
    first = _check(edge_list, solution, KURHADE_AFTERNOON)
    edge_list = apply_change(edge_list, KURHADE_AFTERNOON)
    substitute = _sub(CE207, "fac-prasenjit-bhavathankar")
    second = _check(edge_list, first, substitute)
    assert second["displaced"] == ["obs-t6-r5-c1-l0"]  # his own SE-Comp D lecture (S14u)
    edge_list = apply_change(edge_list, substitute)
    began = time.perf_counter()
    with pytest.raises(TimeoutError):
        repair(edge_list, second, WED_P0_601, time_limit_s=10.0)
    assert time.perf_counter() - began < 10.0 + MARGIN_S

    monkeypatch.setattr(solver.backtracking, "_room_order", lambda state, sid, rooms: sorted(
        rooms, key=lambda r: (r not in state.parent_of, r)))
    changed = apply_change(edge_list, WED_P0_601)
    found = backtrack_solve(build_conflict_graph(changed), changed,
                            seed_rooms={CE207: "room-601"}, time_limit_s=60.0)
    assert found.solved
    assert validate_solution(changed, found.to_solution_v2_dict()) == []
