# Chronos: UML diagrams (S16e)

First written in S16e; last updated 2026-11-01 (S17c).
Mermaid, which renders on GitHub. Every box and message names something in the code; the files
are listed under each diagram. Requirements: [docs/srs.md](srs.md).

## 1. Use cases by role

```mermaid
flowchart LR
    Student([Student])
    Faculty([Faculty member])
    Coordinator([Timetable coordinator])
    Administrator([Administrator])

    LogIn((Log in))
    ViewTimetable((View the official timetable))
    ViewOwn((View own timetable, locked when the account is linked))
    ViewWorkload((View own weekly load))
    ViewRooms((View room timetable and free rooms))
    ViewAnomalies((View the anomaly report))
    FacultyAtSlot((See free and engaged faculty at a slot))
    Solve((Solve the instance))
    Repair((Repair after an absence, a closed room or a drag))
    Substitute((Find a qualified substitute and repair with it))
    Accept((Accept a repair))
    ReadChanges((Read the accepted changes))
    ClearChanges((Clear the accepted changes))
    ReadAudit((Read the audit log))

    Student --> LogIn & ViewTimetable & ViewOwn
    Faculty --> LogIn & ViewTimetable & ViewOwn & ViewWorkload
    Coordinator --> LogIn & ViewTimetable & ViewRooms & ViewAnomalies & FacultyAtSlot
    Coordinator --> Solve & Repair & Substitute & Accept & ReadChanges
    Administrator --> LogIn & ViewTimetable & ViewRooms & ViewAnomalies & FacultyAtSlot
    Administrator --> Solve & Repair & Substitute & Accept & ReadChanges
    Administrator --> ClearChanges & ReadAudit
```

Files: `backend/app/routers.py` (`Solver` = administrator or coordinator, `Administrator`),
`frontend/src/types/roles.ts` (`ROLE_CAPABILITIES`), `frontend/src/App.tsx` (which panel each
role sees). Reading routes need only a valid token. The faculty and student lock (D50) is in the
UI only, because timetables are not secret.

## 2. Class diagrams

### 2.1 Database models

```mermaid
classDiagram
    class Institute { +int id }
    class Department { +int id; +int institute_id }
    class Programme { +int id; +int department_id }
    class Semester { +int id; +int programme_id }
    class Room { +int id; +int institute_id; +capacity }
    class SubRoom { +int id; +int room_id }
    class Faculty { +int id; +int department_id }
    class FacultyInitials { +int faculty_id }
    class FacultyAlias { +int faculty_id }
    class Subject { +int id; +int department_id }
    class Cohort { +int id; +int department_id; +semester_id }
    class Division
    class Batch
    class ElectiveGroup
    class CombinedDivisions
    class Timetable { +int id; +int department_id }
    class LabBlock { +int id; +int division_id }
    class Session { +int id; +int timetable_id; +cohort_id; +subject_id; +faculty_id; +room_id; +sub_room_id; +lab_block_id }
    class PinnedBlock { +int id; +timetable_id; +cohort_id; +faculty_id; +room_id; +sub_room_id }
    class FacultyUnavailability { +int timetable_id; +int faculty_id }
    class AbsenceRecord { +int faculty_id; +replacement_faculty_id }
    class AuditEntry { +int id; +str actor; +str action; +timestamp; +str detail }
    class User { +str username; +str password_hash; +UserRole role; +faculty_ref; +cohort_ref }
    class SolveJob { +str id; +str instance_id; +str kind; +str status; +str phase; +base; +solution; +accepted_at; +cleared_at; +built_with; +audit_id }

    Institute "1" --> "*" Department
    Institute "1" --> "*" Room
    Department "1" --> "*" Programme
    Programme "1" --> "*" Semester
    Room "1" --> "*" SubRoom
    Faculty "1" --> "*" FacultyInitials
    Faculty "1" --> "*" FacultyAlias
    Faculty "*" -- "*" Subject : qualification
    Cohort <|-- Division
    Cohort <|-- Batch
    Cohort <|-- ElectiveGroup
    Cohort <|-- CombinedDivisions
    Division "1" --> "*" Batch : batches
    Timetable "1" --> "*" Session
    LabBlock "1" --> "*" Session
    Session --> Cohort
    Session --> Subject
    Session --> Faculty
    Session --> Room
    Session --> SubRoom
    PinnedBlock --> Timetable
    FacultyUnavailability --> Faculty
    AbsenceRecord --> Faculty
    SolveJob --> AuditEntry : audit_id
```

File: `db/models.py`. Every entity carries `department_id` except `Institute`, `Room` and
`SubRoom` (`docs/CONTEXT.md` rule 5). `User` is the table `app_user`.

`SolveJob` holds solve and repair jobs. An accepted repair's change is the accepted change that
later jobs include (`accepted_at`, `cleared_at`, `built_with`; migration
`0009_accepted_changes`). There is no separate table for accepted changes.

### 2.2 Solver core types

```mermaid
classDiagram
    class SlotId { +int day; +int period }
    class SlotGrid { +int days; +int periods_per_day; +teaching_periods; +adjacency }
    class Session { +str id; +str subject_id; +str faculty_id; +str cohort_id; +str session_type; +int duration_periods; +int cohort_size; +bool requires_lab; +fixed_slot }
    class Edge { +str u; +str v; +str reason }
    class ConflictGraph { +grid; +sessions; +edges; +adjacency; +faculty_unavailable; +pinned_slots; +lab_blocks; +neighbours(session_id) }
    class Room { +str id; +str code; +int capacity; +room_type; +parent_room_id }
    class LabBlock { +str id; +session_ids; +int duration_periods }
    class BacktrackResult { +assignment; +room_assignment; +bool solved; +int nodes_explored; +bool timed_out; +bool rooms_by_id_fallback; +certificate; +to_solution_v2_dict() }
    class Certificate { +str check; +str kind; +session_ids; +str resource; +str reason; +slots }
    class Violation { +str kind; +session_ids; +slots }
    class Rule { +str id; +float weight; +parameters }
    class RuleSet { +str version; +rules }

    ConflictGraph --> SlotGrid
    ConflictGraph "1" --> "*" Session
    ConflictGraph "1" --> "*" Edge
    SlotGrid ..> SlotId : slot()
    BacktrackResult --> Room
    BacktrackResult --> Certificate : pre-solve proof
    RuleSet "1" --> "4" Rule
```

Files: `solver/slots.py` (`SlotId`, `SlotGrid`), `solver/graph.py` (`Session`, `Edge`,
`ConflictGraph`), `solver/backtracking.py` (`Room`, `LabBlock`, `BacktrackResult`),
`solver/presolve.py` (`Certificate`), `solver/validate.py` (`Violation`), `solver/scoring.py`
(`Rule`, `RuleSet`). The solver takes and returns plain data (the edge-list and `solution.v2`
contracts); these types never leave `solver/`.

## 3. Sequence diagrams

### 3.1 Login

```mermaid
sequenceDiagram
    actor User
    participant LoginScreen as LoginScreen (frontend)
    participant Client as HttpChronosApiClient
    participant Router as routers.login
    participant Service as ChronosService
    participant Database as PostgreSQL
    User->>LoginScreen: username, password
    LoginScreen->>Client: login(username, password)
    Client->>Router: POST /auth/login
    Router->>Service: login(username, password)
    Service->>Database: select app_user by username
    Service->>Service: verify_password (scrypt, constant time)
    Service->>Database: audit_entry "login" {success}
    Service-->>Router: Actor or None
    alt password matches
        Router->>Router: issue_token(actor) (HS256, role, faculty_id, cohort_id)
        Router-->>Client: 200 Token
        Client->>Client: setSession (sessionStorage "chronos.session")
    else wrong username or password
        Router-->>Client: 401 incorrect username or password
    end
```

Files: `frontend/src/components/auth/LoginScreen.tsx`, `frontend/src/api/chronosApi.ts`,
`backend/app/routers.py`, `backend/app/service.py`, `backend/app/auth.py`.

### 3.2 A solve job

```mermaid
sequenceDiagram
    actor Coordinator
    participant SolvePanel as SolvePanel (frontend)
    participant Client as HttpChronosApiClient
    participant Router as routers.start_solve / get_job
    participant Service as ChronosService
    participant Database as PostgreSQL
    participant Worker as Worker process (ProcessPoolExecutor)
    Coordinator->>SolvePanel: Solve
    SolvePanel->>Client: startSolve(instance)
    Client->>Router: POST /instances/{id}/solve
    Router->>Service: start_solve(instance_id, time_limit_s, max_moves, actor)
    Service->>Service: _built (committed edge list + accepted changes, D52)
    Service->>Database: audit_entry "solve", solve_job status "queued"
    Service->>Worker: submit solve_edge_list(edge list, ...)
    Router-->>Client: 202 {job_id}
    Worker->>Database: _mark_running: status "running", phase "search"
    Worker->>Worker: backtrack_solve (pre-solve, sub-rooms first within 5000 nodes, then rooms by id)
    alt solved
        Worker->>Database: phase "improve"
        Worker->>Worker: improve (local search)
    else infeasible
        Worker->>Worker: explain (minimal conflicting set, protected break pins)
    end
    Worker-->>Service: (status, solution.v2 or None on timeout)
    Service->>Database: _job_done: status, solution, ended_at, complete the audit row
    loop until the job ends
        SolvePanel->>Client: getJob(job_id)
        Client->>Router: GET /jobs/{id}
        Router-->>Client: JobView (status, phase, solution)
    end
```

Files: `frontend/src/components/timetable/SolvePanel.tsx`, `frontend/src/api/queries.ts`
(`useSolveMutation`, `useJobQuery`), `backend/app/routers.py`, `backend/app/service.py`
(`start_solve`, `_start`, `solve_edge_list`, `_mark_running`, `_job_done`), `solver/backtracking.py`,
`solver/improve.py`, `solver/mus.py`. The search makes up to two attempts (S14x): sub-rooms first
within 5,000 nodes (`SUB_ROOM_NODES` = `RING_NODES`), then rooms by id in the time left, only if
that budget ran out with no verdict. A verdict of the first attempt stands, and running out of
time is the status `timeout`, never `infeasible` (D33).

### 3.3 An absence, repaired and accepted

```mermaid
sequenceDiagram
    actor Coordinator
    participant RepairPanel as RepairPanel (frontend)
    participant Client as HttpChronosApiClient
    participant Router as routers
    participant Service as ChronosService
    participant Database as PostgreSQL
    participant Worker as Worker process
    Coordinator->>RepairPanel: Mark unavailable (faculty, slots)
    RepairPanel->>Client: startRepair(instance, faculty_unavailable)
    Client->>Router: POST /instances/{id}/repair
    Router->>Service: start_repair(instance_id, change, ...)
    Service->>Service: _built, apply_change (422 if unknown or already in force)
    Service->>Database: audit_entry "repair", solve_job kind "repair", base = official
    Service->>Worker: submit repair_edge_list(edge list, official solution, change)
    Router-->>Client: 202 {job_id}
    Worker->>Worker: repair (freeze and expand, explain if infeasible)
    Worker-->>Service: (status, solution.v2 or None)
    Service->>Database: _job_done
    Note over RepairPanel,Client: useRepair (App.tsx) polls and fetches
    Client->>Router: GET /jobs/{id}, /jobs/{id}/base-solution, /jobs/{id}/edge-list
    Router-->>Client: proposal, its base and its edge list
    Client-->>RepairPanel: the proposal with its changes outlined
    Coordinator->>RepairPanel: Accept
    RepairPanel->>Client: acceptRepair(job_id)
    Client->>Router: POST /jobs/{id}/accept
    Router->>Service: accept(job_id, actor)
    alt base still official and built with the changes in force
        Service->>Database: accepted_at, accepted_by, audit_entry "accept"
        Router-->>Client: 200 JobView (official, D49)
    else
        Router-->>Client: 409 Conflict (D49, D56)
    end
```

Files: `frontend/src/components/timetable/RepairPanel.tsx`, `frontend/src/api/queries.ts`
(`useRepair`), `backend/app/routers.py`, `backend/app/service.py` (`start_repair`,
`repair_edge_list`, `accept`), `solver/repair.py`.

### 3.4 A substitution (both workloads recalculated, S14m)

```mermaid
sequenceDiagram
    actor Coordinator
    participant SubstitutePanel as SubstitutePanel (frontend)
    participant App as App.tsx (useRepair, queries)
    participant RepairPanel as RepairPanel (frontend)
    participant Workload as FacultyWorkloadCard (frontend)
    participant Client as HttpChronosApiClient
    participant Router as routers
    participant Service as ChronosService
    participant Solver as solver.repair
    Coordinator->>SubstitutePanel: open a session
    SubstitutePanel->>Client: getSubstitutes(instance, session_id)
    Client->>Router: GET /instances/{id}/sessions/{session_id}/substitutes
    Router->>Service: substitutes(instance_id, session_id)
    Service->>Service: qualified (qualifications.json, D53)
    Service->>Solver: substitute_candidates(edge list, official, session, qualified)
    Solver-->>Service: candidates with score change
    Service-->>Client: candidates, and those left out with reasons
    Coordinator->>SubstitutePanel: choose a substitute
    SubstitutePanel->>Client: startRepair(instance, substitute_faculty)
    Client->>Router: POST /instances/{id}/repair
    Note over Router,Service: as in 3.3, refused (422) if not qualified
    App->>Client: getCurrentEdgeList, getJobEdgeList
    App->>App: proposalWorkload: both teachers' load, current edge list vs the job's
    App->>RepairPanel: workload (before, after)
    Coordinator->>RepairPanel: Accept
    Note over RepairPanel,Router: POST /jobs/{id}/accept, as in 3.3
    App->>App: official solution = the accepted job's (setQueryData)
    App->>Client: getCurrentEdgeList, getChanges (refetched)
    App->>Workload: official solution on the current edge list
    Workload->>Workload: every teacher's load recalculated
```

Files: `frontend/src/components/timetable/SubstitutePanel.tsx`, `RepairPanel.tsx`,
`FacultyWorkloadCard.tsx`, `frontend/src/App.tsx`, `frontend/src/api/queries.ts`
(`useSubstitutesQuery`), `backend/app/service.py` (`substitutes`, `qualified`),
`solver/repair.py` (`substitute_candidates`, `apply_change`).

### 3.5 Clearing the accepted changes (D52, D56)

```mermaid
sequenceDiagram
    actor Administrator
    participant Panel as AcceptedChangesPanel (frontend)
    participant Client as HttpChronosApiClient
    participant Router as routers.clear_changes
    participant Service as ChronosService
    participant Database as PostgreSQL
    Administrator->>Panel: Clear accepted changes
    Panel->>Client: clearChanges(instance)
    Client->>Router: DELETE /instances/{id}/changes (administrator only)
    Router->>Service: clear_changes(instance_id, actor)
    Service->>Database: cleared_at on every accepted change
    Service->>Service: _official: newest finished solve or accepted repair not stale and on no cleared change, else the committed solution.json
    Service->>Database: audit_entry "clear_changes" {cleared, official}
    Service-->>Client: the cleared changes
    Panel->>Panel: refetch changes, current edge list, solution and audit log
```

Files: `frontend/src/components/timetable/AcceptedChangesPanel.tsx`, `frontend/src/api/queries.ts`
(`useClearChangesMutation`), `backend/app/routers.py`, `backend/app/service.py`
(`clear_changes`, `_official`, `_stale`).

## 4. State diagram of a job

```mermaid
stateDiagram-v2
    [*] --> queued : POST solve or repair (audited)
    queued --> running : worker starts (phase search, improve or repair)
    running --> solved
    running --> infeasible
    running --> timeout : time_limit_s ran out (never infeasible, D33)
    running --> error : exception, cancelled
    queued --> error : server restarted
    running --> error : server restarted
    solved --> [*]
    infeasible --> [*]
    timeout --> [*]
    error --> [*]

    state solved {
        [*] --> NotOfficial
        NotOfficial --> Official : a solve when it ends, if not stale, or a repair when accepted (D49)
        Official --> NotOfficial : a newer official job, or its changes cleared (D56)
        NotOfficial --> Stale : built with other changes than those in force (D56)
    }
```

Files: `backend/app/service.py` (statuses `queued`, `running`, `solved`, `infeasible`, `timeout`,
`error`; the code says `error`, not "failed"; `_official`, `_stale`, `accept`),
`backend/app/routers.py` (`JobView`). A finished infeasible solve can also be the official
result (`_official` takes solves that are solved or infeasible). A repair is official only once
accepted, and only a solved one can be.

## 5. Activity diagram of a repair

```mermaid
flowchart TD
    Start([repair: timetable, change]) --> Apply[apply_change to the edge list]
    Apply --> Drag{A drag onto a pinned item?}
    Drag -- yes --> PreCheck[explain from that pin and the drag]
    PreCheck --> ReturnDiag([infeasible, explained])
    Drag -- no --> Hit[Hit: sessions the change forbids, and what stands in a drag's way]
    Hit --> Freeze[Freeze every other session at its slot and room]
    Freeze --> Ring[Backtracking on the free sessions within ring_nodes]
    Ring --> Solved{Solved?}
    Solved -- no, not everything free --> Grow[Grow the free set by one ring: conflict neighbours, same room same day]
    Grow --> Ring
    Solved -- no, everything free --> Last{last_ring_portfolio?}
    Last -- "no: uncapped search" --> LastResult{Outcome}
    Last -- "yes (default): capped search ran out" --> Fallback[Fallback: sub-rooms first, no old-place preference]
    Fallback --> LastResult
    LastResult -- timeout --> Timeout([TimeoutError, never infeasible])
    LastResult -- infeasible --> Explain[explain within the time left]
    Explain --> ReturnDiag
    Solved -- yes --> Restore[Restore moved sessions to their old places where they fit]
    LastResult -- solved --> Restore
    Restore --> Improve[improve, moving only sessions that already moved]
    Improve --> Validate[validate_solution against the changed edge list]
    Validate --> Done([solved: the repaired timetable])
```

File: `solver/repair.py` (`repair`, `apply_change`, `_frozen_in_the_way`, `_in_the_way`).
Defaults: `RING_NODES = 5_000`, `MAX_MOVES = 20_000`. `prefer_sub_rooms` and
`last_ring_portfolio` are on by default since S14u (added off in S14s, D58). `time_limit_s`
covers the whole call (S14k).

## 6. Component diagram

```mermaid
flowchart LR
    subgraph Frontend["frontend/ (React, TypeScript)"]
        App[App.tsx]
        Screens[components/timetable and components/auth]
        ApiClient[api/chronosApi.ts HttpChronosApiClient]
        Queries[api/queries.ts]
        Wording[lib/wording.ts, lib/format.ts]
        App --> Screens --> Queries --> ApiClient
        Screens --> Wording
    end
    subgraph Backend["backend/app/ (FastAPI)"]
        Main[main.py create_app]
        Routers[routers.py]
        Deps[deps.py current_actor, require_role]
        Auth[auth.py]
        ServiceC[service.py ChronosService]
        Store[store.py InstanceStore]
        Main --> Routers --> Deps --> Auth
        Routers --> ServiceC --> Store
    end
    subgraph Solver["solver/ (stdlib only, D61)"]
        Graph[graph.py]
        Backtracking[backtracking.py and presolve.py]
        Improve[improve.py]
        RepairC[repair.py]
        Mus[mus.py]
        Validate[validate.py]
        Scoring[scoring.py and rules/quality_rules.yaml]
    end
    Db[(db/models.py on PostgreSQL)]
    Contracts[[contracts/ edge_list_v1, solution_v2]]
    Instances[[data/instances/even-2025-26]]
    ApiClient -- HTTP JSON, bearer token --> Routers
    ServiceC --> Backtracking & Improve & RepairC & Mus
    ServiceC --> Db
    Store --> Instances
    ServiceC -. check_contract .-> Contracts
    RepairC --> Backtracking & Improve & Mus & Validate
    Backtracking --> Graph
    Improve --> Scoring
```

Files as named in the boxes. `backend/app/service.py` is the only backend module that calls the
solver. `solver/` imports no web, ORM or database code.

## 7. Deployment diagram (D55, D57)

```mermaid
flowchart LR
    Browser["Browser (the built React app)"]
    subgraph Render["Render web service, free instance (deployed by hand, S16c)"]
        subgraph Image["Docker image from backend/Dockerfile.prod"]
            Uvicorn["uvicorn backend.app.prod:app, 1 worker: API under /api, built frontend at /"]
            Pool["Worker processes: ProcessPoolExecutor, 2 workers"]
            Files["data/instances (committed edge list, display, solution)"]
            Uvicorn --> Pool
            Uvicorn --> Files
        end
    end
    Supabase[("Supabase PostgreSQL, eu-west-2 (D55)")]
    Browser -- HTTPS --> Uvicorn
    Uvicorn -- "SQLAlchemy, remote host allowed only with CHRONOS_ALLOW_REMOTE_DB=1, set by hand in Render (D57)" --> Supabase
    Pool -- "job status and phase" --> Supabase
```

Files: `backend/Dockerfile.prod`, `backend/app/prod.py`, `backend/app/service.py`
(`max_workers=2`), `db/local_guard.py`.

- **Built and deployed** (S16c, 2026-11-01): one Render web service on the free instance, built
  from `backend/Dockerfile.prod`. It runs one uvicorn worker and a pool of 2 solver worker
  processes (`ProcessPoolExecutor`, `max_workers=2` in `ChronosService`). Its database is
  Supabase PostgreSQL in eu-west-2 (D55). Locally the same app runs against Docker Postgres.
- **By hand only:** migrations and demo resets reach Supabase only when Nidhi runs them, with
  `CHRONOS_ALLOW_REMOTE_DB=1` set for that one command (D55, D57, D59). Only the Render service
  sets that variable, in Render's settings.
- **Live demos run on a laptop** (D64): Render's free instance is about 9 times slower than a
  laptop, so the deployed site is shown, not driven.
