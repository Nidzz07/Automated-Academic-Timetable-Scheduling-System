# Contract change proposal — v2

**Status:** PROPOSAL — nothing in `contracts/` has changed. No schema moves until all three
members sign the decision table at the end.
**Branch:** `contracts/v2-proposal` (off `main` @ `f1e5b1b`)
**Date:** 2026-10-03
**Author:** Nidhi (drafted with Claude Code)

Read before this document: `CONTEXT.md` §5 (the three frozen contracts),
`CURRENT-PROGRESS.md` → Contract change log, `contracts/ingestion_v1.schema.json`,
`contracts/solution_v1.schema.json`.

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
contract that feeds it cannot express. `ingestion/seed_legends.py` currently writes these
rows **straight to the DB**, bypassing the contract. That works as a Phase 1 seed, but the
Phase 2 parsers are meant to go through `ingestion_v1`.

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

**(c) Extend** `observed_sessions[]` with two fields, so an ambiguous cell keeps its
evidence while `faculty_id` stays null:

```jsonc
"faculty_initials_raw":   { "type": ["string", "null"],
                            "description": "The initials token exactly as it appeared in the cell, e.g. 'SK'." },
"faculty_candidate_ids":  { "type": "array", "items": { "$ref": "#/$defs/id" },
                            "description": "Every faculty the scoped legend maps faculty_initials_raw to. Exactly one ⇒ faculty_id is that id. Two or more ⇒ faculty_id is null and the session is ambiguous. Zero ⇒ unresolved." }
```

**(d) Extend** the `anomalies[].code` enum with `AMBIGUOUS_FACULTY_INITIALS`, kept distinct
from `UNRESOLVED_FACULTY_INITIALS`. The schema's own description says "extending it is a
contract revision".

Cross-field rules (`is_ambiguous` matches the duplicate-key fact; `faculty_id` agrees with
`faculty_candidate_ids`) cannot be stated in JSON Schema. They become contract tests in
`tests/contracts/`, as the DB-side equivalent already is a test.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB (Nidhi)** | `contracts/examples/ingestion_v1.example.json` loses six `initials` keys and gains a `faculty_initials` array. No Phase 2 parser emits `ingestion_v1` yet, so there is no producer code to change. `seed_legends.py` should, in Phase 2, *consume* this array instead of reading legends itself. The DB is already in the target shape (0004), so no migration is needed. |
| **Solver (Rohan)** | **None directly.** The solver never sees initials; it reads `edge_list_v1`. One consequence to agree on: `edge_list_v1.sessions[].faculty_id` is a required non-null id. A session whose faculty is ambiguous therefore **cannot enter an edge list** until a human resolves it. This is correct: guessing would let the solver double-book one of the two people. The backend must block "generate" and list the blocking sessions. Nothing in `solver/` changes. |
| **Frontend (Dhruv)** | `frontend/src/lib/timetableData.ts:186-187` reads `ingestionFixture.faculty[].initials` to label cells. That breaks. The label must come from `faculty_initials` filtered by the cell's division, with a fallback for ambiguous or unscoped cases. `frontend/src/fixtures/ingestion_v1.example.json` must be re-copied. A good outcome: the UI can show "SK — ambiguous: Kurhade / Kakade" instead of a wrong name. |

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
For a coordinator the most useful facts are "these three sessions are the ones that could
not go anywhere" and "here is what *did* fit". The coordinator gets neither.

The obvious fix — allow `assignment` when infeasible — is unsafe. Any consumer that tests
"has `assignment`" instead of "`status == solved`" would render a broken timetable as a
working one. Today's schema prevents that confusion structurally, and the fix must keep that.

A related gap found while reading the schema: the infeasible branch forbids `assignment`
but **does not forbid `quality` or `displaced`**. An infeasible payload carrying a quality
score is currently schema-valid. That is the same masquerade risk through a different field.

### Proposed schema change

1. **Nest the partial placement inside `diagnosis`**, under a name that cannot be mistaken
   for a timetable:

   ```jsonc
   "diagnosis": {
     "required": ["minimal_conflicting_set", "suggested_relaxation",
                  "partial_placement", "unplaced_session_ids"],
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

   `$defs/placement` is the existing `assignment` item, lifted to `$defs` so both use one
   definition. `unplaced_session_ids` has `minItems: 1` because an infeasible result
   with nothing unplaced is a contradiction.

2. **Close the masquerade gap.** In the infeasible `then` branch, set
   `"properties": { "assignment": false, "quality": false, "displaced": false }`.

3. **Pin which partial.** Backtracking visits many partials. To keep output
   deterministic, the contract states: *the partial with the most sessions placed; ties go
   to the first reached in the solver's deterministic search order.* That is a solver
   obligation, recorded in the description and tested.

4. Contract tests (not expressible in JSON Schema):
   `len(partial_placement) == metadata.sessions_assigned`;
   `partial_placement ∪ unplaced_session_ids` partitions the instance's session ids;
   `partial_placement` is itself conflict-free (reuse the Hypothesis conflict checker).

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB** | None. |
| **Solver (Rohan)** | `backtracking.py` (on `origin/track/solver`) already tracks `self.unplaced_sessions`. It must also keep a snapshot of the best partial and emit both. The deterministic tie-break must be preserved. `solution_v1.infeasible.example.json` gains the two fields. The two schema-conformance tests in `solver/tests/test_backtracking.py` (≈ lines 848–892) need the new schema file. |
| **Frontend (Dhruv)** | `InfeasibilityDiagnosisPanel` can overlay `partial_placement` as a greyed, non-editable layer and list `unplaced_session_ids`. `types/solution.ts` gains two fields on `InfeasibilityDiagnosis`. The panel must never reuse the drag-and-drop grid component for the partial, because that would let a user "edit" a non-timetable. |

### Version

Taken alone, **v2**: making `partial_placement`/`unplaced_session_ids` required and
forbidding `quality`/`displaced` both invalidate payloads that were legal. A purely additive
variant (both fields optional, gap left open) is possible but leaves the masquerade gap in
place. Recommendation: **ship in `solution.v2`, together with changes 3 and 4.**

---

## 3. `solution_v1` — the suggested relaxation is prose only

### Problem

`suggested_relaxation` is `{constraint_id, description}`. The example's relaxation is
genuinely good advice: "Classify room 606 as a lab…". But a program can only print it.
"Apply the suggested relaxation" — one click that changes the input and re-solves — cannot
be built without parsing English. Infeasibility diagnosis with an actionable minimal fix is
one of the project's **two headline novelties** (CONTEXT.md §1, CLAUDE.md). A diagnosis
the UI cannot act on is half that feature.

Two further weaknesses surfaced while reading:

- **A relaxation from one MUS does not guarantee feasibility.** Removing a constraint makes
  *that* subset satisfiable. If the instance contains a second, disjoint MUS, it is still
  infeasible. The schema description promises "the smallest single change that restores
  feasibility", which the contract cannot currently show was checked.
- `backtracking.py`'s fallback relaxation is `"Relax constraints on session <id> to restore
  feasibility."` (see §5). It conforms to the schema but is not something a coordinator
  could act on, programmatically or by hand.

### Proposed schema change

Add a required, typed `action`, plus a `verified` flag:

```jsonc
"suggested_relaxation": {
  "required": ["constraint_id", "description", "action", "verified"],
  "properties": {
    "constraint_id": { ... unchanged ... },
    "description":   { ... unchanged - still the human sentence ... },
    "action": {
      "type": "object",
      "required": ["action_type", "params"],
      "properties": {
        "action_type": { "enum": [
          "RECLASSIFY_ROOM",          // params: room_id, to_room_type ∈ {class, lab}
          "RELEASE_PINNED_BLOCK",     // params: pinned_block_id
          "MOVE_PINNED_BLOCK",        // params: pinned_block_id, to: slot_ref
          "ADD_FACULTY_AVAILABILITY", // params: faculty_id, slots: [slot_ref]
          "REASSIGN_FACULTY",         // params: session_id, from_faculty_id, to_faculty_id
          "RELAX_LAB_CONTIGUITY",     // params: lab_block_id
          "MANUAL"                    // params: {} - no programmatic form; description is the instruction
        ]},
        "params": { "type": "object" }
      },
      "allOf": [ /* one if/then per action_type fixing the exact required params */ ]
    },
    "verified": {
      "type": "boolean",
      "description": "true iff the solver re-ran with this action applied and the instance became feasible. false = removes this MUS only; other conflicts may remain."
    }
  }
}
```

Design notes for review:

- **Why typed `params`, not a single `target_entity_id`.** One id is not enough for most
  actions. `RECLASSIFY_ROOM` needs the new type, `MOVE_PINNED_BLOCK` needs a destination
  slot, and `REASSIGN_FACULTY` needs two faculty ids. A per-type `if/then` keeps each
  action fully specified and lets the frontend `switch` exhaustively on a closed enum
  (strict TS, no `any`).
- **`MANUAL` is the honest escape hatch.** When the solver cannot express the fix
  structurally, it says so instead of inventing an action. The UI hides "Apply" for `MANUAL`.
- **The action targets *input data*, not the solution.** Applying it means the backend
  mutates the DB (room type, pinned block, availability, …), writes an `AuditEntry`, and
  re-solves. It is never silently applied. A human confirms, consistent with the
  "deterministic, human-in-the-loop" rule. Ids in `params` must be the same stable ids the
  edge list carried, so the backend can map them back to rows.
- **The action vocabulary depends on a closed `kind` vocabulary.** Picking an action is a
  deterministic mapping from the relaxed constraint's `kind` (`ROOM_CAPACITY` →
  `RECLASSIFY_ROOM`/`RELEASE_PINNED_BLOCK`, `FACULTY_UNAVAILABLE` →
  `ADD_FACULTY_AVAILABILITY`, …). See §5. This proposal does not change `kind`, but the
  two should be discussed together.
- Selection stays rule-based and deterministic. No learned ranking (CLAUDE.md non-negotiable).

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB (Nidhi)** | No ingestion change. The backend gains an apply-relaxation endpoint that translates each `action_type` into a DB write + audit entry + re-solve. **This crosses into `backend/`, which is also Nidhi's, but the re-solve call crosses into Rohan's solver API, so the boundary needs to be agreed.** |
| **Solver (Rohan)** | Must emit a structured action for every relaxation, which requires the `kind → action_type` mapping. Setting `verified` costs one extra solve with the action applied. That is bounded and fits the existing deletion-based MUS loop. The fallback path in `backtracking.py` must emit `MANUAL` (or a real action). |
| **Frontend (Dhruv)** | `SuggestedRelaxation` in `types/solution.ts` gains `action` (discriminated union) and `verified`. `InfeasibilityDiagnosisPanel` gains an "Apply and re-solve" button for non-`MANUAL` actions and a visible caveat when `verified` is false. |

### Version

**v2.** `action` and `verified` must be **required**. If `action` were optional, the UI
could never rely on it, and the feature would be the same prose-only feature it is today.
Required fields invalidate existing payloads. This is the change that most justifies a
`solution.v2`.

---

## 4. `solution_v1` — conflicting-set entries carry time only in prose

### Problem

`minimal_conflicting_set[]` entries locate themselves in time only inside `description`,
e.g. *"Only three lab rooms are free on Monday from 10.00 to 12.00…"*. `entity_ids` gives
the *who/where* in structured form, but nothing gives the *when*. A UI that wants to
highlight the conflicting cell(s) on the grid must regex English. That breaks the first
time the wording changes, and the schema itself says `description` is for humans.

### Proposed schema change

Add a shared `$defs/slot_ref` and a `slots` array on each conflicting-set entry:

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
  "description": "Every (day, period) cell this constraint is about, on the edge-list wall-clock axis. Empty when the constraint is not slot-specific (e.g. a lab-contiguity rule over the whole week).",
  "type": "array",
  "items": { "$ref": "#/$defs/slot_ref" }
}
```

- **Individual cells, not a `{start, duration}` range.** The wall-clock axis has breaks.
  "Monday 10.00–12.00" is `[{day:0, period:1}, {day:0, period:3}]`, which skips break
  period 2. Listing cells removes any need for the UI to know the adjacency table.
- **Wall-clock axis**, the same as `assignment.period`, per the 2026-09-24 decision. The
  teaching-order 0–7 axis of `ingestion_v1` must not leak into the solution contract.
- The same `slot_ref` is reused by the change-3 action params (`MOVE_PINNED_BLOCK.to`,
  `ADD_FACULTY_AVAILABILITY.slots`), so there is one slot shape across the contract.

### What breaks

| Side | Impact |
|---|---|
| **Ingestion / DB** | None. |
| **Solver (Rohan)** | MUS members must carry their slots. For slot-specific constraints (`ROOM_CAPACITY` at a time, `PINNED_BLOCK`, `FACULTY_UNAVAILABLE`) the solver already knows them when it builds the constraint. Contiguity- or clash-type constraints can emit `[]`. |
| **Frontend (Dhruv)** | `ConflictingConstraint` gains `slots: SlotRef[]`. The grid can highlight cells directly. No prose parsing. |

### Version

If shipped alone, it can be **additive v1**: `slots` optional, nothing else changes. Inside
`solution.v2` (recommended, since 2 and 3 already force it), make `slots` **required,
possibly empty**. Then "no slots" is a positive statement and not just an omission.

---

## 5. Recorded, no change proposed: `kind: "UNSATISFIABLE_DOMAIN"` in `backtracking.py`

**Where.** `solver/backtracking.py` does not exist on `main`. It exists on
`origin/track/solver` (`d10dcce`, 2026-09-26). In its fallback diagnosis (≈ lines 165–205),
when no MUS was computed, it emits one entry per unplaced session with
`kind: "UNSATISFIABLE_DOMAIN"`, `constraint_id: "unplaced.<session_id>"`. If there are no
unplaced sessions, it emits a single `kind: "INFEASIBLE_INSTANCE"`,
`constraint_id: "general.infeasible"`.

**Verified: both values are permitted by the frozen `solution_v1` schema.**
`minimal_conflicting_set[].kind` is declared `{"type": "string", "minLength": 1}`.
`FACULTY_CLASH`, `ROOM_CAPACITY`, `LAB_CONTIGUITY`, `PINNED_BLOCK` and
`FACULTY_UNAVAILABLE` appear only as "e.g." in the description; there is no `enum`. So this
is **not a schema-level widening**, and nothing needs logging in the contract change log on
that count.

It is still a contract problem, and it should be resolved in this review:

1. **The `kind` vocabulary is de facto open.** Two values now in code appear in no contract
   document. Each producer can invent kinds the frontend has never heard of. Change 3's
   `kind → action_type` mapping needs this vocabulary to be closed and documented.
2. **The fallback entries break documented (non-machine-checked) rules of the contract:**
   - `description` embeds an internal id ("Session sess-0007 could not be placed…"). The
     schema says *"Never clause indices, vertex numbers or internal ids."*
   - The set is the list of unplaced sessions, not a *minimal unsatisfiable subset of
     constraints*. `constraint_id: "unplaced.<sid>"` names a session, not a constraint.
   - The fallback `suggested_relaxation` ("Relax constraints on session X") is not a single
     concrete change. Under change 3 it would have to be `MANUAL`.
3. These rules are prose in `description` fields, so the current conformance tests
   (`test_infeasible_solution_conforms_to_solution_v1_schema`) pass anyway. Schema-valid
   is not the same as contract-conformant.

**For the three of us to decide (not proposed here):** whether `kind` becomes a closed
`enum` in `solution.v2`, whether `UNSATISFIABLE_DOMAIN`/`INFEASIBLE_INSTANCE` join it, are
renamed, or the fallback path is removed in favour of always running MUS extraction, and
whether `INFEASIBLE_INSTANCE` with `entity_ids: []` is ever an acceptable diagnosis given
CONTEXT.md's "a bare failure is not a legal response".

---

## 6. Summary and recommended bundling

| # | Contract | Change | Breaking? | Recommended version |
|---|---|---|---|---|
| 1 | ingestion | `faculty.initials` → scoped `faculty_initials[]` + session candidates + `AMBIGUOUS_FACULTY_INITIALS` | Yes (field removed) | **`ingestion.v2`** |
| 2 | solution | `diagnosis.partial_placement` + `unplaced_session_ids`; forbid `quality`/`displaced` when infeasible | Yes (new required; branch tightened) | **`solution.v2`** |
| 3 | solution | `suggested_relaxation.action` (typed) + `verified` | Yes (new required) | **`solution.v2`** |
| 4 | solution | `slot_ref` + `minimal_conflicting_set[].slots` | Only if required | **`solution.v2`** (required, may be empty) |
| 5 | solution | `kind` vocabulary (§5) | — | Record only; decide alongside 3 |

`edge_list_v1` is untouched by all four.

Proposed sequence once signed:
1. Add `ingestion_v2.schema.json` and `solution_v2.schema.json` beside the v1 files. Do not
   edit v1 in place. Add v2 examples and contract tests.
2. Producers and consumers move to v2 in one coordinated merge per contract. v1 files stay
   until nothing references them, then move to a cut-list entry.
3. Log both in `CURRENT-PROGRESS.md` → Contract change log, with all three names.

---

## 7. Decision table

Mark each cell **Agree / Agree with changes / Disagree**, with initials and date. A change
proceeds only with three Agrees.

| # | Change | Proposed version | Nidhi | Rohan | Dhruv |
|---|---|---|---|---|---|
| 1 | `ingestion`: division-scoped faculty initials with flagged ambiguity | `ingestion.v2` | | | |
| 2 | `solution`: expose partial placement inside `diagnosis`; forbid `quality`/`displaced` when infeasible | `solution.v2` | | | |
| 3 | `solution`: structured `action` + `verified` on `suggested_relaxation` | `solution.v2` | | | |
| 4 | `solution`: structured `slots` on `minimal_conflicting_set` entries | `solution.v2` (or additive v1 if alone) | | | |
| 5 | `solution`: resolve the open `kind` vocabulary (`UNSATISFIABLE_DOMAIN`, `INFEASIBLE_INSTANCE`) — record only | to be decided | | | |
