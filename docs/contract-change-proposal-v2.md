# Contract change proposal — v2

**Status:** PROPOSAL — nothing in `contracts/` has changed. No schema moves until all three
members sign the decision table at the end.
**Branch:** `contracts/v2-proposal` (off `main` @ `f1e5b1b`)
**Date:** 2026-10-03 (revision 3: change 6 added — quality-block evaluation status and rule-set version)
**Author:** Nidhi (drafted with Claude Code)

Read before this document: `CONTEXT.md` §5 (the three frozen contracts),
`CURRENT-PROGRESS.md` → Contract change log, `contracts/ingestion_v1.schema.json`,
`contracts/solution_v1.schema.json`, `contracts/edge_list_v1.schema.json`, and
`solver/backtracking.py` + `solver/graph.py` on `origin/track/solver` (`d10dcce`).

**Dependency order:** change 5 is a prerequisite of change 3 (§8). Changes 2–6 ship together
as `solution.v2`. Change 1 ships as `ingestion.v2`. `edge_list_v1` does not change (§9, Q1).

---

## 0. How "v2" vs "additive v1" is decided here

The schemas use `additionalProperties: false` throughout and pin `schema_version` with
`const`. So *any* new field makes a new payload invalid under the old schema file. That
alone cannot be the test, or every change would be v2. The rule this document applies:

| Classification | Condition |
|---|---|
| **Additive v1** (no `schema_version` bump, logged in the change log) | Every payload that was valid under the old schema is still valid under the new one, **and** no existing field changes meaning. New fields are optional. The schema file and all three consumers update in the same merge, so no producer emits a field a consumer's copy of the schema rejects. |
| **v2** (new file `*_v2.schema.json`, `schema_version` → `"*.v2"`) | Some old-valid payload becomes invalid (a field is removed, becomes required, or an enum narrows), **or** an existing field's meaning changes. |

The `edge_list_v1` `default`-annotation change of 2026-09-24 is the precedent for
"additive v1". Everything below is judged against this rule.

---

## 1. `ingestion_v1` — faculty initials are division-scoped and can be ambiguous

### Problem

`faculty[].initials` is one `string | null` per faculty member. The real data contradicts
that shape (`ingestion/initials_legend_report.txt`, 21 legend tables, 207 entries,
38 distinct initials):

- **Initials are not globally unique — they are division-scoped.** Three CONFLICTs:
  - `SD` = Sonali Dudhihalli (EVEN SE-Comp B, D; "Sonali D." in SE-Comp C) but
    Surekha Dholay (EVEN TE-Comp A, C, D; ODD TE-Comp A, B).
  - `SM` = Suman M. (EVEN SE-Comp B) but Sudeep Mali (EVEN TE-Comp C, D; ODD TE-Comp B, D).
  - `SK` = Swapnali Kurhade (EVEN SE-Comp B, C, D; ODD TE-Comp D) but also Suhas Kakade.
- **Initials can be ambiguous inside one legend.** ODD `BE Comp- A & B` (table t18) lists
  `SK` → *both* Swapnali Kurhade *and* Suhas Kakade. A cell reading `… / SK` in that division
  cannot be attributed to one person from the document. It must stay unresolved.
- **Initials are case-sensitive.** `AsT` (Asma Tambe) and `AT` (Anuj Tawari) are different
  people.

Migration `0004_faculty_initials` already moved the database to this shape. It drops
`faculty.initials` and adds a `faculty_initials` table with one row per
`(faculty_id, initials, semester_id, division_id)`, plus `source ∈ {legend, manual}` and
`is_ambiguous`. An ambiguous initial keeps every candidate row. The DB can now hold what the
contract that feeds it cannot express.

The contract today can only say "unresolved": `initials: null` plus an
`UNRESOLVED_FACULTY_INITIALS` anomaly, and `observed_sessions[].faculty_id: null`. That
discards *which* people are candidates. It also cannot distinguish "nobody matches" from
"two people match".

### Proposed schema change

**(a) Remove** `faculty[].initials`. A person has no single initials.

**(b) Add** a top-level required array `faculty_initials`, mirroring the 0004 table:

```jsonc
"faculty_initials": {
  "type": "array",
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["faculty_id", "initials", "division_id", "source", "is_ambiguous", "legend_ref"],
    "properties": {
      "faculty_id":   { "$ref": "#/$defs/id" },
      "initials":     { "type": "string", "minLength": 1,
                        "description": "Case-sensitive, verbatim: 'AsT' and 'AT' are different people." },
      "division_id":  { "type": ["string", "null"], "minLength": 1,
                        "description": "Scope. null = unscoped (manual mapping valid file-wide). Semester scope is implicit: a payload covers exactly one `semester`." },
      "source":       { "enum": ["legend", "manual"] },
      "is_ambiguous": { "type": "boolean",
                        "description": "true iff another row in this payload has the same (initials, division_id). Every candidate is listed; none is chosen." },
      "legend_ref":   { "type": ["string", "null"],
                        "description": "Where the mapping was read, e.g. 'ODD t18 BE Comp- A & B'. null for source=manual." }
    }
  }
}
```

The DB's `semester_id` column is omitted on purpose. An ingestion payload is already one
source file for one `semester`, so the scope is implicit. The seeder supplies `semester_id`
from `payload.semester`. The DB check `source <> 'legend' OR division_id IS NOT NULL`
carries over as a contract-level rule (`if source = legend then division_id non-null`).

**(c) Give every `observed_sessions[]` entry exactly one faculty-resolution state.** The full
rule is in §9 Q1. In short: `faculty_initials_raw` is always present, `faculty_id` is set only
on a unique resolution, and `faculty_candidates` (≥ 2 ids) is set only when the initials are
ambiguous.

**(d) Extend** the `anomalies[].code` enum with `AMBIGUOUS_FACULTY_INITIALS`, kept distinct
from `UNRESOLVED_FACULTY_INITIALS`. The schema's own description says "extending it is a
contract revision".

Cross-field rules cannot be stated in JSON Schema. These are: `is_ambiguous` matches the
duplicate-key fact, and every ambiguous or unresolved session has a matching anomaly. They
become contract tests in `tests/contracts/`, as the DB-side equivalent already is a test.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB (Nidhi)** | `contracts/examples/ingestion_v1.example.json` loses six `initials` keys and gains a `faculty_initials` array. No parser emits `ingestion_v1` yet, so there is no producer code to change. The DB is already in the target shape (0004), so no migration is needed. |
| **Solver (Rohan)** | None. The solver never sees initials, and `edge_list_v1` does not change. Ambiguity stops at the DB → edge-list boundary (§9 Q1). |
| **Frontend (Dhruv)** | `frontend/src/lib/timetableData.ts:186-187` reads `ingestionFixture.faculty[].initials` and breaks. See §10. |

### Version

**v2 (`ingestion.v2`).** Removing a required field invalidates every existing payload, and
the meaning of "a faculty member's initials" changes. An additive alternative — keep
`faculty.initials` as deprecated-nullable alongside the new array — is **not recommended**.
It creates two sources of truth for the same fact, and the old field can only ever hold a
wrong-or-null value for SD/SM/SK. The cost of v2 is low because there is no production emitter yet.

---

## 2. `solution_v1` — infeasible results hide the partial placement

### Problem

When `status = "infeasible"`, the `allOf` branch sets `assignment: false`, yet
`metadata.sessions_assigned` reports progress. The infeasible example has 5 of 8. A
consumer knows five sessions were placed but not which, where, or which three were not.

The obvious fix — allow `assignment` when infeasible — is unsafe. Any consumer that tests
"has `assignment`" instead of "`status == solved`" would render a broken timetable as a
working one. Today's schema prevents that confusion structurally, and the fix must keep that.

A related gap: the infeasible branch forbids `assignment` but **does not forbid `quality` or
`displaced`**. An infeasible payload carrying a quality score is currently schema-valid.

### Proposed schema change

1. **Nest the partial placement inside `diagnosis`**, under a name that cannot be mistaken
   for a timetable:

   ```jsonc
   "diagnosis": {
     "properties": {
       "partial_placement": {
         "description": "Diagnostic only - NOT a timetable. The deepest consistent partial assignment the search reached before proving infeasibility. Never to be published, scored or edited.",
         "type": "array",
         "items": { "$ref": "#/$defs/placement" }
       },
       "unplaced_session_ids": {
         "type": "array", "minItems": 1,
         "items": { "$ref": "#/$defs/id" }
       }
     }
   }
   ```

   Both are required for every infeasible result, whatever its `method` (§5).
   `$defs/placement` is the existing `assignment` item, lifted to `$defs` so both use one
   definition. `unplaced_session_ids` has `minItems: 1` because an infeasible result with
   nothing unplaced is a contradiction.

2. **Close the masquerade gap.** In the infeasible `then` branch, set
   `"properties": { "assignment": false, "quality": false, "displaced": false }`.

3. **Pin which partial.** Backtracking visits many partials. To keep output
   deterministic, the contract states: *the partial with the most sessions placed; ties go
   to the first reached in the solver's deterministic search order.*

4. Contract tests (not expressible in JSON Schema):
   `len(partial_placement) == metadata.sessions_assigned`;
   `partial_placement ∪ unplaced_session_ids` partitions the instance's session ids;
   `partial_placement` is itself conflict-free (reuse the Hypothesis conflict checker).

Note on today's code: when `_solve` fails, `backtracking.py` has already unwound every
assignment. It then reports whatever is left, which is only seeded or `fixed_slot` sessions.
That is not the deepest partial. Keeping a snapshot of the deepest partial is new solver work.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB** | None. |
| **Solver (Rohan)** | Snapshot the deepest partial during search and emit it with `unplaced_session_ids`. The two schema-conformance tests in `solver/tests/test_backtracking.py` (≈ lines 848–892) move to the v2 schema. |
| **Frontend (Dhruv)** | `InfeasibilityDiagnosisPanel` can overlay `partial_placement` as a greyed, non-editable layer and list `unplaced_session_ids`. It must never reuse the drag-and-drop grid for the partial. |

### Version

**v2** — new required fields and a tightened branch both invalidate payloads that were legal.

---

## 3. `solution_v1` — the suggested relaxation is prose only

**Prerequisite: change 5.** The legal `action_type`s for a relaxation depend on the
constraint `kind` it relaxes. That needs `kind` to be a closed set (§5, §8).

### Problem

`suggested_relaxation` is `{constraint_id, description}`. The example's relaxation is
genuinely good advice: "Classify room 606 as a lab…". But a program can only print it.
"Apply the suggested relaxation" — one click that changes the input and re-solves — cannot
be built without parsing English. Infeasibility diagnosis with an actionable minimal fix is
one of the project's **two headline novelties** (CONTEXT.md §1). A diagnosis the UI cannot
act on is half that feature.

A second weakness: **a relaxation from one MUS does not guarantee feasibility.** Removing a
constraint makes *that* subset satisfiable. If the instance contains a second, disjoint
MUS, it is still infeasible. The v1 description promises "the smallest single change that
restores feasibility", but nothing in the payload shows that this was checked.

### Proposed schema change

```jsonc
"suggested_relaxation": {
  "required": ["constraint_id", "description", "action", "verification"],
  "properties": {
    "constraint_id": { ... unchanged ... },
    "description":   { ... unchanged - still the human sentence ... },
    "action": {
      "type": "object",
      "additionalProperties": false,
      "required": ["action_type", "params"],
      "properties": {
        "action_type": { "enum": ["UNFIX_SLOT", "RELAX_FACULTY_AVAILABILITY",
                                  "RELAX_PINNED_BLOCK", "RECLASSIFY_ROOM", "MANUAL"] },
        "params": { "type": "object" }
      },
      "allOf": [ /* one if/then per action_type fixing its exact params - see §8 */ ]
    },
    "verification": {
      "type": "object",
      "additionalProperties": false,
      "required": ["status", "runtime_ms"],
      "properties": {
        "status": { "enum": ["restored", "still_infeasible", "timeout", "not_attempted"] },
        "runtime_ms": { "type": ["number", "null"], "minimum": 0,
                        "description": "Wall-clock time of the verification solve. null iff status = not_attempted." }
      }
    }
  },
  "allOf": [
    { "if":   { "properties": { "action": { "properties": { "action_type": { "const": "MANUAL" } } } } },
      "then": { "properties": { "verification": { "properties": { "status": { "const": "not_attempted" } } } } },
      "else": { "properties": { "verification": { "properties": { "status": { "not": { "const": "not_attempted" } } } } } } }
  ]
}
```

The action vocabulary and its link to `kind` are in §8. That section explains why three of
the originally suggested action types were dropped or deferred, and why `RECLASSIFY_ROOM`
was added.

### Verification status, not a boolean

An earlier draft had `verified: boolean`. It is replaced by `verification: {status, runtime_ms}`.

- **Why not a boolean.** `false` conflates "checked, and it did not restore feasibility"
  with "never checked". That is the same honesty gap change 3 exists to close: a UI could
  not tell a tested fix from an untested one.
- **Always attempted, within a budget.** For every non-`MANUAL` action, the solver applies
  the action to the instance (`solver/relaxation.py`, §9 Q2) and re-solves within a
  configurable time budget. The budget is a solver/backend configuration value. This
  proposal deliberately does not fix a number.
- **`restored`** — the re-solve found a complete timetable.
- **`still_infeasible`** — the re-solve proved infeasibility again. A second, independent
  conflict exists. This supports an iterative fix-one-find-the-next loop: apply, re-diagnose,
  and a new MUS appears.
- **`timeout`** — the budget ran out before either answer. The UI must say "could not
  confirm", never "fixed".
- **`not_attempted`** — only for `MANUAL` actions, which cannot be auto-applied. The schema
  `if/then` above makes this pairing exact in both directions.
- **Cost.** Deletion-based MUS extraction (ROADMAP: `solver/mus.py`, not yet on any branch)
  already calls the solver once per candidate constraint. One more verification solve is a
  marginal cost.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB** | None in ingestion. The backend gains the apply endpoint (§9 Q2). |
| **Solver (Rohan)** | Emit a structured action chosen through the kind → action map (§8). Add `solver/relaxation.py`. Run the verification solve. |
| **Frontend (Dhruv)** | `SuggestedRelaxation` gains `action` (a discriminated union on `action_type`) and `verification`. Apply control per §9 Q2. Show a visible caveat for `still_infeasible` / `timeout`. |

### Version

**v2.** `action` and `verification` must be **required**. If they were optional, the UI
could never rely on them. This is the change that most justifies a `solution.v2`.

---

## 4. `solution_v1` — conflicting-set entries carry time only in prose

### Problem

`minimal_conflicting_set[]` entries locate themselves in time only inside `description`,
e.g. *"Only three lab rooms are free on Monday from 10.00 to 12.00…"*. A UI that wants to
highlight the conflicting cells must regex English.

### Proposed schema change

```jsonc
"$defs": {
  "slot_ref": {
    "type": "object",
    "additionalProperties": false,
    "required": ["day", "period"],
    "properties": {
      "day":    { "$ref": "#/$defs/day" },
      "period": { "$ref": "#/$defs/period" }
    }
  }
}

// in minimal_conflicting_set.items
"slots": {
  "description": "Every (day, period) cell this constraint is about, on the edge-list wall-clock axis. Empty when the constraint is not slot-specific.",
  "type": "array",
  "items": { "$ref": "#/$defs/slot_ref" }
}
```

- **Individual cells, not a `{start, duration}` range.** The wall-clock axis has breaks.
  "Monday 10.00–12.00" is `[{day:0, period:1}, {day:0, period:3}]`, which skips break
  period 2.
- **Wall-clock axis**, the same as `assignment.period` (decision of 2026-09-24).
- `slot_ref` is reused by the action params in §8 (`RELAX_FACULTY_AVAILABILITY.slots`,
  `RELAX_PINNED_BLOCK.slot`).

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB** | None. |
| **Solver (Rohan)** | MUS members carry their slots. Clash and contiguity constraints may emit `[]`. |
| **Frontend (Dhruv)** | `ConflictingConstraint` gains `slots: SlotRef[]`, so the grid can highlight cells directly. |

### Version

Alone it could be additive v1 (`slots` optional). Inside `solution.v2`: **required, possibly
empty**, so "no slots" is a positive statement.

---

## 5. `solution_v1` — close `kind`, retire the placeholder kinds, add `diagnosis.method`

### Problem

`minimal_conflicting_set[].kind` is `{"type": "string", "minLength": 1}`. The five names in
its description are examples, not an `enum`. `backtracking.py` (on `origin/track/solver`)
uses that openness: its fallback diagnosis emits `kind: "UNSATISFIABLE_DOMAIN"` (one entry
per unplaced session) or `kind: "INFEASIBLE_INSTANCE"` (when nothing is unplaced). Both
validate today. An open `kind` has two consequences:

- **The UI and the relaxation map cannot rely on the vocabulary.** Change 3's kind →
  action mapping (§8) needs a closed set to map from.
- **The fallback misrepresents itself.** It is a list of unplaced sessions presented as
  a minimal unsatisfiable subset of *constraints*. Its descriptions embed internal ids,
  which the schema prose forbids. Its relaxation ("Relax constraints on session X") is not
  a single concrete change.

### 5.1 Close `kind` to an enum of constraints the solver enforces

The members come from reconciling three sources:

- **(a)** the example names in `solution_v1`'s `kind` description;
- **(b)** the edge `reason` enum in `edge_list_v1` (`FACULTY`, `ROOM`, `COHORT`);
- **(c)** the checks in `solver/backtracking.py` and `solver/graph.py` on `origin/track/solver`.

Every member is a constraint that (c) actually checks.

| `kind` | Meaning | (a) v1 example | (b) edge reason | (c) where the solver enforces it |
|---|---|---|---|---|
| `FACULTY_CLASH` | Two sessions sharing a faculty member may not share a slot | ✓ | `FACULTY` | Conflict-graph adjacency: `_slot_is_available_for_session`, `_forward_check` step 1 |
| `COHORT_CLASH` | Two sessions with overlapping students may not share a slot | — | `COHORT` | Same adjacency checks (edges are reason-agnostic in the search) |
| `ROOM_CLASH` | Two sessions the data layer declared to contend for the only room that can hold both | — | `ROOM` | Same adjacency checks |
| `ROOM_OCCUPANCY` | One session per room or sub-room per slot; a parent room in use locks its sub-rooms and vice versa | — | — | `_room_is_available`, `_forward_check` step 2, `_gen_room_tuples` |
| `ROOM_CAPACITY` | `cohort_size ≤ room.capacity` | ✓ | — | `_build_initial_domains`, `_candidate_rooms_for_session`, `_lab_block_candidates` |
| `ROOM_TYPE` | `requires_lab ⇒ room.is_lab` | — | — | Same three functions as `ROOM_CAPACITY` |
| `FACULTY_UNAVAILABLE` | A faculty member's declared or absence-derived blackout slots | ✓ | — | `graph.available_slots_for` (`faculty_unavailable`) |
| `PINNED_BLOCK` | Slots held by immovable blocks for named faculty, rooms or cohorts | ✓ | — | `available_slots_for` (faculty, cohort); `_room_is_available` and `_build_initial_domains` (rooms) |
| `LAB_CONTIGUITY` | A lab block's sessions start together and run over a contiguous teaching-order chain | ✓ | — | `_contiguous_start_slots`, `_lab_block_candidates`, `_solve_block` |
| `FIXED_SLOT` | A session pre-assigned (e.g. frozen by freeze-and-expand) must stay in its slot | — | — | `available_slots_for` returns only `fixed_slot`; `backtrack_solve` pre-places it |

**Reconciliation notes:**

- **`ROOM_CAPACITY` is narrowed to its literal meaning: head count.** The v1 infeasible
  example uses `ROOM_CAPACITY` for "only three lab rooms are free on Monday 10.00–12.00".
  That is room *supply*, which the solver enforces as `ROOM_OCCUPANCY` (+ `ROOM_TYPE`). The
  v2 example must relabel that entry `ROOM_OCCUPANCY`.
- **`ROOM_CLASH` and `ROOM_OCCUPANCY` are both kept** because the solver checks both
  independently. `ROOM` edges are precomputed by the data layer, while occupancy is checked
  natively during search. The two overlap. Whether the data layer should keep emitting
  `ROOM` edges at all is a question for Rohan and Nidhi; it is not part of this proposal.
- **Named by a source but left out, because nothing enforces it:**
  - `edge_list_v1.sessions[].duration_periods` for a session that is **not** in a lab
    block. `_solve_session` places such a session in one slot and books its room for that
    slot only. A multi-period standalone session's later periods are never checked, so no
    "duration" kind exists.
- **Enforced but deliberately not a kind:**
  - The teaching-period grid (breaks are unschedulable). It defines the slot palette
    itself, not a constraint between entities. Nothing can relax it. Breaks that occupy
    a slot are already `PINNED_BLOCK`.
  - Soft quality rules (`quality_rules.yaml`). These score a solution; they never make an
    instance infeasible, so they cannot be in a MUS.

**Solver observations found while deriving the table.** These are not contract changes; they
are for Rohan. Both were reproduced against a scratch copy of `origin/track/solver` (`d10dcce`):

1. **A `fixed_slot` overrides faculty unavailability and pinned faculty/cohort checks.**
   `available_slots_for` returns `[fixed_slot]` before it consults either. A session fixed to
   a slot its faculty member is unavailable in was placed and reported `solved`. So
   `FIXED_SLOT` vs `FACULTY_UNAVAILABLE` (or `PINNED_BLOCK`) can never surface in a MUS
   today.
2. **A lab block's later periods are not clash-checked.** A block records only `chain[0]`
   in `slot_assignment`, and `_forward_check` prunes only that slot. A 2-period lab for
   cohort C1 at Monday periods 0–1 plus a C1 theory session with a `COHORT` edge to it
   returned `solved` with the theory at Monday period 1. The cohort was double-booked. This
   breaks CLAUDE.md's conflict-free invariant. The Hypothesis property test should catch
   it once it generates multi-period blocks.

### 5.2 Retire `UNSATISFIABLE_DOMAIN` and `INFEASIBLE_INSTANCE`

Neither joins the enum. They describe search **outcomes** ("a domain emptied", "the
instance failed"), not **constraints**. A MUS is a set of constraints, and every member must
be something a coordinator could relax. "This session's domain emptied" cannot be relaxed.
It is the symptom whose cause the MUS is supposed to name.

They exist only because the current diagnosis is a placeholder. No MUS extraction exists yet
(`solver/mus.py` is planned in ROADMAP, not on any branch). Admitting them into a closed enum
would make the placeholder a permanent part of the contract, and a consumer could never tell
a real diagnosis from the stand-in.

The placeholder still needs an honest place to go. That is what §5.3 provides.

### 5.3 Add `diagnosis.method`

```jsonc
"diagnosis": {
  "required": ["method", "minimal_conflicting_set", "partial_placement", "unplaced_session_ids"],
  "properties": {
    "method": {
      "enum": ["mus", "search_exhaustion"],
      "description": "mus: a minimal unsatisfiable subset was extracted. search_exhaustion: complete search proved no timetable exists, but no explanation was extracted."
    },
    "minimal_conflicting_set": { "type": "array", "items": { /* kind: closed enum of §5.1 */ } },
    "suggested_relaxation": { /* change 3 */ },
    "partial_placement": { /* change 2 */ },
    "unplaced_session_ids": { /* change 2 */ }
  },
  "allOf": [
    { "if":   { "properties": { "method": { "const": "search_exhaustion" } } },
      "then": { "properties": { "minimal_conflicting_set": { "maxItems": 0 },
                                "suggested_relaxation": false } } },
    { "if":   { "properties": { "method": { "const": "mus" } } },
      "then": { "required": ["suggested_relaxation"],
                "properties": { "minimal_conflicting_set": { "minItems": 1 } } } }
  ]
}
```

- **`method = search_exhaustion`**: `minimal_conflicting_set` is present and **empty**, and
  `suggested_relaxation` is **absent**. The diagnosis's information is change 2's
  `unplaced_session_ids` (plus `partial_placement`). The current backtracking placeholder
  can therefore emit an **honest** infeasible result: exhaustive search is still a proof of
  infeasibility. The schema makes it impossible for that result to claim a minimal set or a
  smallest relaxation.
- **`method = mus`**: `minimal_conflicting_set` is **non-empty**, every `kind` is from the
  closed enum, and `suggested_relaxation` is required.

**The current `solver/backtracking.py` output will NOT validate under v2. This is
intended.** Its fallback emits placeholder kinds that are no longer in the enum. It also
emits a non-empty set with a relaxation, which `search_exhaustion` forbids. It migrates to
`method = "search_exhaustion"` with an empty set, no relaxation, and the
`unplaced_session_ids` / `partial_placement` of change 2. Once `solver/mus.py` lands, the
MUS path emits `method = "mus"`.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB** | None. |
| **Solver (Rohan)** | Fallback rewritten as above. Placeholder kinds deleted. Kinds come from the §5.1 enum only. |
| **Frontend (Dhruv)** | `ConflictingConstraint.kind` becomes a string-literal union. `InfeasibilityDiagnosisPanel` must render `search_exhaustion`, which has no set and no relaxation: show the unplaced sessions and the partial placement, and say no explanation is available. |

### Version

**v2** — narrowing `kind` from any string to an enum invalidates payloads that were legal.

---

## 6. `solution_v1` — the quality block cannot say "not evaluated" or which rule set scored it

### Problem

Three facts a score must carry cannot be expressed in `solution_v1`'s `quality` block.

**(a) "Not evaluated" vs "evaluated, zero penalty".** Some quality rules depend on data that
a department may legitimately not supply: a configured threshold, or faculty preferences.
That data is optional per department, so in some instances such a rule cannot run. The
scoring engine must then be able to say "this rule was not evaluated, because…" in a way
that is distinct from "this rule ran and found nothing to penalise". v1 has no way to say
that without overloading a field:

- Each `breakdown` entry *requires* `rule_id`, `weight`, `raw`, `penalty` and `explanation`,
  with `additionalProperties: false`. `raw` and `penalty` are `"type": "number"`, not
  nullable. So a not-evaluated rule must either report `penalty: 0`, which reads as
  "fine", or put its status in the free-text `explanation`, which a program cannot read.
- Leaving the rule out of `breakdown` does not work either, because absence already has a
  meaning (see (c)).
- `score` is a bare `number`. Nothing marks it as computed over fewer rules than the rule
  set declares, so a partial total reads as a complete one.

**(b) Which rule set produced the score.** CONTEXT.md rule 4: *"Scoring rules and weights
live in a versioned YAML file."* The `quality` block is `additionalProperties: false` with
only `score` and `breakdown`. `metadata` is equally closed (`algorithm`, `runtime_ms`,
`sessions_total`, `sessions_assigned`, `slots_used`, `backtracks`). The only place a version
could go is the free-text `metadata.algorithm`, which would be overloading. Per-entry
`weight` records the weight a rule carried, but not which file revision supplied it. And
under (c), rules that did not fire are absent, so their weights are not recorded at all.
Two scores computed under different YAML revisions are indistinguishable.

**(c) "Ran and scored zero" vs "not in the rule set".** The schema defines `breakdown` as
*"One entry per quality rule that fired"*. An absent rule already means "did not fire",
which reads as "fine". The same definition means a rule that *was* evaluated and
contributed zero is also absent, exactly like a rule the loaded YAML never declared. A
reader of a v1 payload cannot tell which rules were run at all. Only a breakdown that lists
every loaded rule makes "ran and scored zero" distinguishable from "not in the rule set".

The current code already shows the risk. `BacktrackResult.to_solution_dict` on
`origin/track/solver` defaults `quality` to `{"score": 100.0, "breakdown": []}` when no
scoring ran. That is a perfect score with an empty breakdown, valid under v1, and
indistinguishable from a timetable that really scored 100.

### Proposed schema change

The starting point is validated against the v1 schema, with two corrections:

- The v1 field is named `penalty`, not `contribution`. It is kept as `penalty` to avoid a
  rename that changes nothing.
- The *"one entry per rule that fired"* definition has to change. Otherwise
  not-evaluated rules still have nowhere to appear, and "evaluated, zero" stays
  indistinguishable from absent.

```jsonc
"quality": {
  "type": "object",
  "additionalProperties": false,
  "required": ["score", "rules_version", "breakdown", "not_evaluated_rule_ids"],
  "properties": {
    "score": {
      "type": "number",
      "description": "Aggregate over EVALUATED rules only. Complete iff not_evaluated_rule_ids is empty."
    },
    "rules_version": {
      "type": "string", "minLength": 1,
      "description": "The `version` declared at the top of solver/rules/quality_rules.yaml for the rule set that produced this score."
    },
    "not_evaluated_rule_ids": {
      "type": "array", "uniqueItems": true,
      "items": { "type": "string", "minLength": 1 },
      "description": "rule_ids whose breakdown entry has status not_evaluated. Non-empty means `score` is partial."
    },
    "breakdown": {
      "description": "One entry per rule in the loaded rule set - fired, zero, or not evaluated. Never only the rules that fired.",
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["rule_id", "status", "weight"],
        "properties": {
          "rule_id":     { "type": "string", "minLength": 1 },
          "status":      { "enum": ["evaluated", "not_evaluated"] },
          "weight":      { "type": "number", "description": "Weight from the YAML. Known even when the rule could not run." },
          "raw":         { "type": "number" },
          "penalty":     { "type": "number" },
          "explanation": { "type": "string", "minLength": 1 },
          "reason":      { "type": "string", "minLength": 1,
                           "description": "Why the rule could not run, in institutional terms, e.g. 'FAC_PREFERENCE_MISMATCH: no faculty preferences supplied for this instance.' (Illustrative only; FAC_PREFERENCE_MISMATCH is not one of the four ROADMAP rules.)" }
        },
        "allOf": [
          { "if":   { "properties": { "status": { "const": "evaluated" } } },
            "then": { "required": ["raw", "penalty", "explanation"],
                      "properties": { "reason": false } } },
          { "if":   { "properties": { "status": { "const": "not_evaluated" } } },
            "then": { "required": ["reason"],
                      "properties": { "raw": false, "penalty": false, "explanation": false } } }
        ]
      }
    }
  }
}
```

Design notes:

- **A not-evaluated entry forbids `raw` and `penalty`.** It does not just leave them
  optional. That makes "unknown" structurally impossible to write as `0`.
- **`weight` stays required in both states.** The weight is known from the YAML even when
  the rule cannot run. Showing it tells a coordinator how much of the score is missing.
- **`not_evaluated_rule_ids` duplicates information in `breakdown` on purpose.** A
  consumer that reads only `score` and the top-level fields still cannot mistake a partial
  total for a complete one. The two must agree; that is a contract test (below).
- **`rules_version` comes from the YAML file itself.** `quality_rules.yaml` declares a
  top-level `version`. The scoring loader fails loudly if it is missing, the same way
  ROADMAP already requires an unknown rule ID to fail at startup. The contract can carry
  the version, but it cannot force anyone to bump it when a weight changes. That
  discipline belongs to review of the YAML file. Per-entry `weight`, now present for
  every rule, gives a second, direct record of the weights used.
- **Not-evaluated is decided by input availability, deterministically.** A rule is
  `not_evaluated` when its required input is absent, never when its result looks odd.

Contract tests (not expressible in JSON Schema):

- `breakdown` `rule_id`s are unique;
- `not_evaluated_rule_ids` equals the set of entries with `status = not_evaluated`;
- `score` equals the documented aggregate (as `solver/scoring.py` defines it) over evaluated
  entries only.

A solver test checks that `breakdown`'s rule ids equal the rule set loaded from the YAML.

**Workload source for `FAC_LOAD_IMBALANCE` — no contract change needed.** The T/P figures
on the faculty timetables (`6T+ 8P =14`) count a faculty member's theory and practical
hours in the timetable. Every `edge_list_v1` session already carries what is needed to
derive them, all as required fields: `faculty_id`, `duration_periods`, and `session_type`
(`theory` | `lab`). A faculty member's T is the sum of `duration_periods` over their
`theory` sessions, and P is the same sum over their `lab` sessions. A batch-parallel lab
contributes one session per batch, each with its own faculty. A combined-division lecture
is one session, so it counts once. So the scorer derives T/P-weighted load from the
instance's own sessions. The database's published T/P totals are a **validation target**
(ingestion should reproduce them, as with the lab-utilisation figures in CONTEXT.md §3.6),
not a scoring input. One caveat for that validation: `pinned_occupancy` entries (MDM, HSS,
LLC, …) name faculty per slot but carry no `session_type`. If the published totals include
pinned-block hours, the derived totals will differ by exactly those hours. The validation
then shows that difference; the scorer does not paper over it.

**Rule definition for sign-off — a ROADMAP clarification, not a contract change.** Faculty
assignment is an input. Every session arrives with `faculty_id` fixed, and the solver
chooses only the slot and the room. So each faculty member's *total* T/P-weighted load is
identical in every timetable for a given instance. A rule that measures total-load
imbalance across faculty gives every timetable for an instance the same penalty, so it
cannot tell one timetable from another. Proposed:

- `FAC_LOAD_IMBALANCE` measures the imbalance of **each faculty member's T/P-weighted load
  across the days of the week**. One example is the spread between their heaviest and
  lightest teaching day, aggregated over faculty. Slot choice determines this, so it does
  distinguish timetables.
- Cross-faculty *total* load belongs to substitution ordering in Phase 4 absence handling
  (candidates ordered by ascending T/P-weighted workload). That matches CONTEXT.md §3.4,
  which names both "load balancing and substitution ordering" as users of the weighting.

This changes no schema. It refines the meaning of ROADMAP Phase 3 Track A's
`FAC_LOAD_IMBALANCE` line, which is Rohan's rule. **It needs Rohan's agreement** before
`solver/scoring.py` implements it.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB (Nidhi)** | No ingestion change. `db/models.py` `Timetable` stores only `quality_score: float \| None`. A partial score stored there loses its "partial" flag and its rule-set version. The table needs `rules_version` and the not-evaluated rule ids (or the full breakdown) beside the score. That is a migration, not a contract change, but it should land with v2. |
| **Solver (Rohan)** | `solver/scoring.py` (Phase 3, not yet written) emits one entry per loaded rule with a status, and reads `version` from the YAML. The `{"score": 100.0, "breakdown": []}` default in `to_solution_dict` must go, since it cannot validate under v2 (`rules_version` is required). The v2 solved example should use the registry's rule ids (`FAC_BACK_TO_BACK`, `FAC_LOAD_IMBALANCE`, `STU_IDLE_GAPS`, `FAC_DAILY_OVERLOAD`) instead of v1's `room_capacity_waste` / `lab_spans_short_break`, and include one `not_evaluated` entry. |
| **Frontend (Dhruv)** | `QualityBreakdownItem` in `types/solution.ts` becomes a union discriminated on `status`. Its comment "One entry per quality rule that fired" changes. `QualityScoreCard` must render not-evaluated rules distinctly, with their reason, and label the score as partial whenever `not_evaluated_rule_ids` is non-empty. It shows `rules_version`. |

### Version

**v2 (`solution.v2`).** New required fields (`status`, `rules_version`,
`not_evaluated_rule_ids`) invalidate v1 payloads. The meaning of `breakdown` also changes,
from "rules that fired" to "every rule in the set". Either alone is v2 under §0.

---

## 7. Summary and recommended bundling

| # | Contract | Change | Breaking? | Recommended version |
|---|---|---|---|---|
| 1 | ingestion | `faculty.initials` → scoped `faculty_initials[]`; per-session resolution state; `AMBIGUOUS_FACULTY_INITIALS` | Yes (field removed) | **`ingestion.v2`** |
| 2 | solution | `diagnosis.partial_placement` + `unplaced_session_ids`; forbid `quality`/`displaced` when infeasible | Yes | **`solution.v2`** |
| 3 | solution | `suggested_relaxation.action` (typed) + `verification` status object | Yes | **`solution.v2`**, after 5 |
| 4 | solution | `slot_ref` + `minimal_conflicting_set[].slots` | Only if required | **`solution.v2`** (required, may be empty) |
| 5 | solution | closed `kind` enum; retire placeholder kinds; `diagnosis.method` | Yes (enum narrows) | **`solution.v2`**, prerequisite of 3 |
| 6 | solution | per-rule `status` (`evaluated` \| `not_evaluated`) with `reason`; `not_evaluated_rule_ids`; `rules_version`; breakdown lists every rule | Yes (new required; `breakdown` meaning changes) | **`solution.v2`** |

`edge_list_v1` is untouched by all six. (§11 row 7 is a ROADMAP clarification, not a contract change, so it is not listed here.)

Proposed sequence once signed:
1. Add `ingestion_v2.schema.json`, `solution_v2.schema.json` and
   `relaxation_actions_v2.json` (§8) beside the v1 files. Do not edit v1 in place. Add v2
   examples and contract tests.
2. Producers and consumers move to v2 in one coordinated merge per contract. v1 files stay
   until nothing references them, then move to a cut-list entry.
3. Log both in `CURRENT-PROGRESS.md` → Contract change log, with all three names. Copy the
   §10 seed decision into the Decision log.

---

## 8. Coupling between change 5 and change 3

### 8.1 Action types — validated, not copied

The suggested starting set was REASSIGN_FACULTY, REASSIGN_ROOM, MOVE_SESSION, UNFIX_SLOT,
RELAX_FACULTY_AVAILABILITY, RELAX_PINNED_BLOCK, MANUAL. Each was checked against two tests.
Is it a change to the solver's **input**? (A relaxation changes the problem, not the
answer.) And can some component in this system actually perform it?

| `action_type` | Verdict | `params` | Executed by |
|---|---|---|---|
| `UNFIX_SLOT` | **Kept** | `session_id` | Solver: `relaxation.py` sets `fixed_slot = null`. Backend: releases the freeze on that session. |
| `RELAX_FACULTY_AVAILABILITY` | **Kept** | `faculty_id`, `slots: [slot_ref]` | Solver: removes those slots from `faculty_availability`. Backend: edits the faculty member's *declared* unavailability. It **refuses** if a slot comes from an `AbsenceRecord`, because a recorded absence is a fact, not a preference. The edge list does not distinguish the two, so the backend must check. |
| `RELAX_PINNED_BLOCK` | **Kept** | `slot: slot_ref`, `entity_kind ∈ {faculty, room, cohort}`, `entity_id` | Solver: removes that entity from that slot's `pinned_occupancy` entry. Backend: edits the `PinnedBlock` row. Coordinator/admin only (§9 Q2). `pinned_occupancy` entries carry no id in `edge_list_v1`, so the action names slot + entity, and the backend maps that back to the row. |
| `RECLASSIFY_ROOM` | **Added** | `room_id`, `is_lab: boolean` | Solver: flips `is_lab` on that room. Backend: updates the room's classification. This is the action the v1 example already describes in prose ("classify room 606 as a lab"). It was missing from the suggested set. |
| `MANUAL` | **Kept** | `{}` | Nobody automatically. A human acts on `description`. `verification.status = not_attempted`. |
| `REASSIGN_FACULTY` | **Deferred** | — | The backend could execute it, but the solver cannot *propose* one. Naming a substitute needs faculty–subject qualifications, which `edge_list_v1` does not carry. Adding them is an edge-list change, out of scope here (§9 Q1 keeps `edge_list_v1` fixed). Until then it is `MANUAL`. |
| `REASSIGN_ROOM` | **Dropped** | — | Rooms are not inputs: `edge_list_v1` sessions carry no room, and the solver already searches every eligible room. There is nothing to relax. The real input lever on rooms is `RECLASSIFY_ROOM`. |
| `MOVE_SESSION` | **Dropped** | — | A free session's slot is already searched exhaustively, so moving it changes the answer, not the problem. The only legitimate case, a session pinned to a slot, is `UNFIX_SLOT`. Manually moving a session is drag-and-drop editing, a separate feature. |
| (lab-block split, cohort split) | **`MANUAL`** | — | Administrative decisions, not something the system does. `must_be_contiguous` is also `const: true` in `edge_list_v1`. |

`params` per type is fixed by one `if/then` per `action_type` inside `action` (change 3), so
the frontend can `switch` exhaustively on a closed union.

### 8.2 The kind → action map

`MANUAL` is permitted for every kind.

| `kind` | Permitted `action_type`s | Why |
|---|---|---|
| `FACULTY_CLASH` | `MANUAL` | Only a different teacher relaxes it. `REASSIGN_FACULTY` is deferred (§8.1). |
| `COHORT_CLASH` | `MANUAL` | Splitting or regrouping students is administrative. |
| `ROOM_CLASH` | `MANUAL` | The edge is derived by the data layer. `relaxation.py` cannot re-derive it, so any automated action would leave the very edge it targets in place. |
| `ROOM_OCCUPANCY` | `RECLASSIFY_ROOM`, `MANUAL` | Adding an eligible room increases supply. |
| `ROOM_CAPACITY` | `MANUAL` | Capacity is physical. The fix is a cohort split or a different room choice made by a person. |
| `ROOM_TYPE` | `RECLASSIFY_ROOM`, `MANUAL` | Makes a room lab-eligible (or not). |
| `FACULTY_UNAVAILABLE` | `RELAX_FACULTY_AVAILABILITY`, `MANUAL` | Declared blackouts only; absences are refused (§8.1). |
| `PINNED_BLOCK` | `RELAX_PINNED_BLOCK`, `MANUAL` | Overrides an institutional decision, so authorisation is gated. |
| `LAB_CONTIGUITY` | `MANUAL` | Contiguity is `const: true` in the edge list; splitting a block is administrative. |
| `FIXED_SLOT` | `UNFIX_SLOT`, `MANUAL` | Releases a frozen or pre-assigned session. |

**One caveat on `RECLASSIFY_ROOM` verification.** `relaxation.py` flips `is_lab` but cannot
re-derive the data layer's `ROOM` edges. Stale `ROOM` edges can only *over*-constrain. So a
`restored` verdict is still sound, but `still_infeasible` may be pessimistic. When it
persists the change, the backend re-derives the edge list from the DB before the real re-solve.

### 8.3 Where the map lives and how it is enforced

JSON Schema cannot enforce "`action.action_type` must be legal for the `kind` of the
`minimal_conflicting_set` entry whose `constraint_id` equals
`suggested_relaxation.constraint_id`". That is a lookup across elements, which the schema
language cannot express. So:

- The map is stored as data at **`contracts/relaxation_actions_v2.json`**:
  `{ "<kind>": ["<action_type>", ...], ... }`.
- **A contract test in `tests/contracts/` enforces it:**
  1. its keys equal the `kind` enum exactly;
  2. every value is a subset of the `action_type` enum and contains `MANUAL`;
  3. every non-`MANUAL` action appears under at least one kind;
  4. for every `solution_v2` example and every solver-produced payload in the solver
     tests, the relaxation's `action_type` is in the map entry for the referenced
     constraint's `kind`.
- The solver's own action-selection table is drift-checked against this file. This follows
  the precedent of `solver/slots.py` being drift-checked against the edge-list schema's
  `default`s.

### 8.4 The ongoing coupling rule

- **Adding a `kind`** requires declaring, in the same change, which actions relax it. At
  minimum this is `MANUAL`.
- **Adding an `action_type`** requires declaring which kinds it applies to, its `params`,
  and which component executes it.
- **Both are contract changes.** They need three-way agreement and a change-log entry, like
  any schema edit, even though the map is a JSON data file and not a schema.

---

## 9. Resolved open questions

### Q1 — Faculty on sessions in `ingestion.v2`

Each `observed_sessions[]` entry carries:

- **`faculty_initials_raw`** — always present: the initials token as printed, e.g. `"SK"`.
  *Refinement for sign-off:* the faculty individual timetable's cell format
  (`SUBJECT / BATCH / DIVISION / ROOM`, CONTEXT.md §3.3) prints **no** initials, because the
  faculty member is the page. So the key is always present, but nullable, and null only for
  that source format.
- **`faculty_id`** — set **only** when resolution is unique.
- **`faculty_candidates`** — set **only** when the initials are ambiguous: 2 or more ids.

Exactly one resolution state per session, enforced by a `oneOf`:

| State | `faculty_id` | `faculty_candidates` | Required anomaly |
|---|---|---|---|
| resolved | id | absent | — |
| ambiguous | null | ≥ 2 ids | `AMBIGUOUS_FACULTY_INITIALS` |
| unresolved | null | absent | `UNRESOLVED_FACULTY_INITIALS` |

The anomaly requirement is cross-element (anomaly `source_cell` = session `source_cell`),
so it is a contract test.

**At the DB → edge-list boundary**, sessions without a resolved `faculty_id` are excluded
from the edge list and reported by the backend alongside the solve. Any timetable produced
must show it does not cover them. **Consequence: `edge_list_v1` does NOT change.**
`sessions[].faculty_id` stays a required non-null id, and ambiguity stops at the boundary.
The solver never guesses which `SK`.

### Q2 — Ownership of "apply relaxation"

| Owner | Responsibility |
|---|---|
| **Rohan — solver** | A pure function `apply_relaxation(instance, action) -> instance` in **`solver/relaxation.py`**. Plain data in, plain data out, no DB. Re-solving is a call to the existing solver. The verification solve of change 3 uses the same function. |
| **Nidhi — backend** | The endpoint. It loads the instance, calls `apply_relaxation`, re-solves, and persists the result as a **candidate** timetable. The live timetable is not overwritten until someone confirms. It writes the `AuditEntry`. It enforces authorisation: `RELAX_PINNED_BLOCK` overrides an institutional decision, so only coordinator/admin may apply it. (Proposed for sign-off: `RECLASSIFY_ROOM` edits institute-level room data and gets the same gate.) It refuses `RELAX_FACULTY_AVAILABILITY` on absence-derived slots. |
| **Dhruv — frontend** | The Apply control, enabled only for non-`MANUAL` actions. An explicit confirmation step for any action overriding a pinned block. The candidate is shown beside the live timetable until confirmed. |

### Q3 — Verification timing

As in change 3: verification is always attempted for non-`MANUAL` actions, within a
configurable time budget. The result is the `verification` status object, never a boolean.

---

## 10. Migration impact

- **Solver:** `backtracking.py`'s infeasible output migrates to
  `method = "search_exhaustion"` (empty set, no relaxation, plus `partial_placement` /
  `unplaced_session_ids`). The placeholder kinds `UNSATISFIABLE_DOMAIN` /
  `INFEASIBLE_INSTANCE` are removed. New `solver/relaxation.py`. The two observations in
  §5.1 (fixed-slot bypass, lab second-period clash) are separate bug fixes. The
  `{"score": 100.0, "breakdown": []}` quality default in `to_solution_dict` is removed
  (change 6).
- **Frontend:** `frontend/src/lib/timetableData.ts:186-187` reads `faculty[].initials` and
  breaks under `ingestion.v2` (change 1). `InfeasibilityDiagnosisPanel` must handle
  `method = "search_exhaustion"`, which has no conflicting set to render. `QualityScoreCard`
  renders not-evaluated rules and labels a partial score (change 6).
- **Backend / ingestion:** `ingestion/seed_legends.py` writes reference data (initials
  legends, legend-only faculty, aliases) straight to the database, bypassing the ingestion
  contract. **Proposed as a deliberate decision, for reference data only.** Timetable
  observations must go through the contract: the Phase 2 class-timetable parser
  `ingestion/class_tt.py` (not yet written) emits `ingestion.v2` payloads and the seeder
  consumes them. `Timetable.quality_score` alone cannot hold a partial score; it needs
  `rules_version` and the not-evaluated rule ids beside it (migration, change 6).

---

## 11. Decision table

Mark each cell **Agree / Agree with changes / Disagree**, with initials and date. A contract
change (rows 1–6) proceeds only with three Agrees. Row 3 cannot proceed unless row 5 is
agreed. Row 7 is a ROADMAP clarification (§6) that alters no contract; it needs Rohan's Agree
before `solver/scoring.py` implements it. Nidhi and Dhruv may add a comment but do not sign it.

| # | Change | Proposed version | Nidhi | Rohan | Dhruv |
|---|---|---|---|---|---|
| 1 | `ingestion`: division-scoped faculty initials with flagged ambiguity | `ingestion.v2` | | | |
| 2 | `solution`: expose partial placement inside `diagnosis`; forbid `quality`/`displaced` when infeasible | `solution.v2` | | | |
| 3 | `solution`: structured action + verification status object on `suggested_relaxation` (requires row 5) | `solution.v2` | | | |
| 4 | `solution`: structured `slots` on `minimal_conflicting_set` entries | `solution.v2` | | | |
| 5 | `solution`: close `kind` to an enum of enforced constraints; retire `UNSATISFIABLE_DOMAIN` / `INFEASIBLE_INSTANCE`; add `diagnosis.method` (`mus` \| `search_exhaustion`) — **prerequisite of row 3** | `solution.v2` | | | |
| 6 | `solution`: quality breakdown gets per-rule `status` (`evaluated` \| `not_evaluated`, `reason` required when not evaluated); score over evaluated rules only, with `not_evaluated_rule_ids`; `rules_version` | `solution.v2` | | | |
| 7 | **ROADMAP clarification (NOT a schema change):** `FAC_LOAD_IMBALANCE` measures each faculty member's T/P-weighted load spread across the days of the week; cross-faculty total load moves to Phase 4 substitution ordering | none (no contract version change) | n/a | | n/a |