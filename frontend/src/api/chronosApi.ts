/**
 * Chronos API clients.
 *
 * VITE_API_MODE picks one: 'http' (the default) calls the S13a backend through the Vite
 * proxy (/api); 'static' serves the files bundled from contracts/examples and
 * data/instances (offline and tests). Every solution payload is validated against
 * contracts/solution_v1.schema.json or solution_v2.schema.json, and every edge list against
 * edge_list_v1.schema.json (see contractValidation.ts); an invalid one throws
 * ContractValidationError.
 */

import {
  SolutionContract,
  SolvedSolution,
  InfeasibleSolution,
  DayIndex,
  PeriodIndex,
  SessionAssignment,
  isSolvedSolution,
  isInfeasibleSolution,
} from '@/adapters/solution';
import solvedFixture from '@contracts/examples/solution_v2.solved.example.json';
import infeasibleFixture from '@contracts/examples/solution_v2.infeasible.example.json';
import edgeListExample from '@contracts/examples/edge_list_v1.example.json';
import d6GridEdgeList from '@contracts/examples/edge_list_v1.d6_grid.example.json';
import {
  DAY_NAMES,
  Display,
  EdgeList,
  cohortsOverlap,
  getCohortLabel,
  getFaculty,
} from '@/adapters/timetable';
import { AnomalyReport, PrintedBaseline, toPrintedBaseline } from '@/adapters/realInstance';
import { ROLE_CAPABILITIES, UserRole } from '@/types/roles';

// ajv and the schemas load on first use, off the main bundle
const validation = () => import('@/api/contractValidation');

/**
 * The contract examples, bundled in both modes: 'example' is the instance the solution
 * examples were solved for; 'd6_grid' shows the D6 grid (per-year lunch as pinned occupancy)
 * and has no solution.
 */
export const EDGE_LIST_INSTANCES = { example: edgeListExample, d6_grid: d6GridEdgeList };

/**
 * A contract example's key, a backend instance id (its data/instances/ directory name,
 * e.g. 'even-2025-26'), or PRINTED_INSTANCE.
 */
export type EdgeListInstance = string;

/** The real CE EVEN 2025-26 SE+TE instance (S9 export, D41 display sidecar). */
export const REAL_INSTANCE = 'even-2025-26';
/**
 * The real instance with the timetable as printed (S12b baseline). Not a backend instance:
 * the backend does not serve real_baseline.*.json, so they are bundled in both modes.
 */
export const PRINTED_INSTANCE = `${REAL_INSTANCE}:printed`;

export interface InstanceOption {
  id: EdgeListInstance;
  label: string;
  /** The backend can solve it (http mode, backend instances only) */
  solvable: boolean;
}

const INSTANCE_LABELS: Record<string, string> = {
  example: 'Example instance',
  d6_grid: 'D6 grid example (no solution)',
  [REAL_INSTANCE]: 'EVEN 2025-26 SE+TE (real)',
  [PRINTED_INSTANCE]: 'EVEN 2025-26 printed (real)',
};

const option = (id: EdgeListInstance, solvable = false): InstanceOption => ({
  id,
  label: INSTANCE_LABELS[id] ?? id,
  solvable,
});

const isExample = (instance: EdgeListInstance): instance is keyof typeof EDGE_LIST_INSTANCES =>
  Object.keys(EDGE_LIST_INSTANCES).includes(instance);

/** The backend instance whose files an instance reads. */
const baseOf = (instance: EdgeListInstance) => (instance === PRINTED_INSTANCE ? REAL_INSTANCE : instance);

/** The instance files the backend serves (S13a); any but the edge list may be absent. */
type InstanceFile = 'edge_list' | 'display' | 'anomalies' | 'solution';

type RealEvenFile = InstanceFile | 'real_baseline.assignment' | 'real_baseline.report';

// Lazy, so each file loads only when picked; solution.json has no loader until it is solved
const realEven = import.meta.glob(
  '@instances/even-2025-26/{edge_list,display,solution,anomalies,real_baseline.assignment,real_baseline.report}.json',
  { import: 'default' }
);

async function loadRealEven(file: RealEvenFile): Promise<unknown> {
  const load = Object.entries(realEven).find(([path]) => path.endsWith(`/${file}.json`))?.[1];
  return load ? JSON.parse(JSON.stringify(await load())) : null;
}

export interface MoveSessionRequest {
  sessionId: string;
  targetDay: DayIndex;
  targetWallClockPeriod: PeriodIndex;
  targetRoomId?: string;
  targetSubRoomId?: string | null;
}

export interface ViolatedConstraint {
  constraint_id: string;
  kind: string;
  description: string;
  entity_ids: string[];
}

export interface MoveSessionResult {
  success: boolean;
  solution?: SolvedSolution;
  rejectionReason?: string;
  violatedConstraint?: ViolatedConstraint;
}

/**
 * Common API Client interface that both the mock and real HTTP backend client implement.
 */
export interface ChronosApiClient {
  /**
   * Fetch current timetable. Returns either SolvedSolution or InfeasibleSolution.
   */
  getTimetable(id?: string): Promise<SolutionContract>;

  /**
   * Fetch an instance's edge list (grid, rooms, sessions, pinned occupancy).
   */
  getEdgeList(instance?: EdgeListInstance): Promise<EdgeList>;

  /**
   * The edge list the next solve or repair builds: a backend instance's committed edge list with
   * every accepted change in force (http mode, D52); otherwise getEdgeList's.
   */
  getCurrentEdgeList(instance: EdgeListInstance): Promise<EdgeList>;

  /**
   * The instance's display sidecar (D41: names, pin kinds and labels, clock times);
   * null for the contract examples, which have none.
   */
  getDisplay(instance: EdgeListInstance): Promise<Display | null>;

  /**
   * The solution published beside the instance's edge list; null when it is not solved yet.
   * The example instance's solutions come from getTimetable().
   */
  getInstanceSolution(instance: EdgeListInstance): Promise<SolutionContract | null>;

  /** The instance's ingestion anomaly report (anomalies.json); null when it has none. */
  getAnomalies(instance: EdgeListInstance): Promise<AnomalyReport | null>;

  /**
   * The timetable as printed, with its violations and score: for the real instance and its
   * printed view, null for any other.
   */
  getPrintedBaseline(instance: EdgeListInstance): Promise<PrintedBaseline | null>;

  /** The instances to offer: the contract examples, then the real ones. */
  listInstances(): Promise<InstanceOption[]>;

  /**
   * Request solver to generate a timetable.
   */
  generateTimetable(): Promise<SolutionContract>;

  /**
   * Move a session to a target slot. Validates constraints.
   */
  moveSession(req: MoveSessionRequest, currentSolution: SolvedSolution): Promise<MoveSessionResult>;

  /**
   * Helper to retrieve solved fixture.
   */
  getSolvedSolution(): Promise<SolvedSolution>;

  /**
   * Helper to retrieve infeasible fixture.
   */
  getInfeasibleSolution(): Promise<InfeasibleSolution>;
}

/**
 * Mock Chronos API client for Phase 2 Track C.
 * Provides both solved and infeasible responses and a configurable reject-the-move path.
 */
export class MockChronosApiClient implements ChronosApiClient {
  private simulatedOutcome: 'solved' | 'infeasible' = 'solved';
  private rejectMode: boolean = false;
  private rejectionReason: string = 'Simulated backend rejection: Hard constraint violation (faculty clash)';

  constructor(initialOutcome: 'solved' | 'infeasible' = 'solved') {
    this.simulatedOutcome = initialOutcome;
  }

  /**
   * Configure whether future move operations should be rejected for testing/simulation.
   */
  public setRejectMode(reject: boolean, reason?: string) {
    this.rejectMode = reject;
    if (reason) {
      this.rejectionReason = reason;
    }
  }

  public isRejectMode(): boolean {
    return this.rejectMode;
  }

  /**
   * Set simulated solver outcome ('solved' or 'infeasible').
   */
  public setSimulatedOutcome(outcome: 'solved' | 'infeasible') {
    this.simulatedOutcome = outcome;
  }

  public getSimulatedOutcome(): 'solved' | 'infeasible' {
    return this.simulatedOutcome;
  }

  public async getTimetable(id?: string): Promise<SolutionContract> {
    if (id === 'infeasible' || this.simulatedOutcome === 'infeasible') {
      return this.getInfeasibleSolution();
    }
    return this.getSolvedSolution();
  }

  /** An instance's file; null when it has none. The static client has the real instance only. */
  protected async readInstanceFile(instance: EdgeListInstance, file: InstanceFile): Promise<unknown> {
    return instance === REAL_INSTANCE ? loadRealEven(file) : null;
  }

  public async listInstances(): Promise<InstanceOption[]> {
    return [...Object.keys(EDGE_LIST_INSTANCES), REAL_INSTANCE, PRINTED_INSTANCE].map((id) => option(id));
  }

  public async getEdgeList(instance: EdgeListInstance = 'example'): Promise<EdgeList> {
    const { validateContract } = await validation();
    if (isExample(instance)) return validateContract('edge_list', JSON.parse(JSON.stringify(EDGE_LIST_INSTANCES[instance])));
    const edgeList = await this.readInstanceFile(baseOf(instance), 'edge_list');
    if (edgeList === null) throw new Error(`Unknown instance '${instance}'`);
    return validateContract('edge_list', edgeList);
  }

  /** Static mode has no accepted changes: the committed edge list. */
  public async getCurrentEdgeList(instance: EdgeListInstance): Promise<EdgeList> {
    return this.getEdgeList(instance);
  }

  public async getDisplay(instance: EdgeListInstance): Promise<Display | null> {
    if (isExample(instance)) return null;
    const display = (await this.readInstanceFile(baseOf(instance), 'display')) as Display | null;
    if (display === null) return null;
    const pins = (await this.getEdgeList(instance)).pinned_occupancy.length;
    // pins[i] describes pinned_occupancy[i]: a sidecar out of step would mislabel every pin
    if (display.pins.length !== pins) {
      throw new Error(`display.json has ${display.pins.length} pins for ${pins} pinned_occupancy entries`);
    }
    return display;
  }

  public async getInstanceSolution(instance: EdgeListInstance): Promise<SolutionContract | null> {
    if (isExample(instance) || instance === PRINTED_INSTANCE) return null;
    const solution = await this.readInstanceFile(instance, 'solution');
    return solution === null ? null : (await validation()).parseSolution(solution);
  }

  public async getAnomalies(instance: EdgeListInstance): Promise<AnomalyReport | null> {
    if (isExample(instance)) return null;
    return (await this.readInstanceFile(baseOf(instance), 'anomalies')) as AnomalyReport | null;
  }

  public async getPrintedBaseline(instance: EdgeListInstance): Promise<PrintedBaseline | null> {
    if (baseOf(instance) !== REAL_INSTANCE) return null;
    const [assignment, report, edgeList] = await Promise.all([
      loadRealEven('real_baseline.assignment'),
      loadRealEven('real_baseline.report'),
      this.getEdgeList(REAL_INSTANCE),
    ]);
    return toPrintedBaseline(assignment, report, edgeList);
  }

  public async generateTimetable(): Promise<SolutionContract> {
    // Simulate brief solver runtime
    await new Promise((resolve) => setTimeout(resolve, 50));
    if (this.simulatedOutcome === 'infeasible') {
      return this.getInfeasibleSolution();
    }
    return this.getSolvedSolution();
  }

  public async getSolvedSolution(): Promise<SolvedSolution> {
    // Deep clone of the solved example, validated like any API payload
    const solution = (await validation()).parseSolution(JSON.parse(JSON.stringify(solvedFixture)));
    if (!isSolvedSolution(solution)) throw new Error('Expected a solved solution payload');
    return solution;
  }

  public async getInfeasibleSolution(): Promise<InfeasibleSolution> {
    // Deep clone of the infeasible example, validated like any API payload
    const solution = (await validation()).parseSolution(JSON.parse(JSON.stringify(infeasibleFixture)));
    if (!isInfeasibleSolution(solution)) throw new Error('Expected an infeasible solution payload');
    return solution;
  }

  /**
   * Validate and apply session move.
   */
  public async moveSession(
    req: MoveSessionRequest,
    currentSolution: SolvedSolution
  ): Promise<MoveSessionResult> {
    // Simulate network latency (small for test responsiveness)
    await new Promise((resolve) => setTimeout(resolve, 30));

    // 1. Check explicit reject simulation toggle
    if (this.rejectMode) {
      return {
        success: false,
        rejectionReason: this.rejectionReason,
        violatedConstraint: {
          constraint_id: 'mock.simulated-reject',
          kind: 'SIMULATED_REJECTION',
          description: this.rejectionReason,
          entity_ids: [req.sessionId],
        },
      };
    }

    // 2. Validate session existence in current solution
    const sessionIndex = currentSolution.assignment.findIndex(
      (a) => a.session_id === req.sessionId
    );
    if (sessionIndex === -1) {
      return {
        success: false,
        rejectionReason: `Session '${req.sessionId}' not found in current timetable assignment.`,
      };
    }

    // The solution examples were solved for the example instance
    const edgeList = await this.getEdgeList('example');
    const edgeSession = edgeList.sessions.find((s) => s.id === req.sessionId);
    const slotLabel = `${DAY_NAMES[req.targetDay]} P${req.targetWallClockPeriod}`;

    // 3. Reject if the session itself is fixed / pinned
    if (edgeSession?.fixed_slot !== null && edgeSession?.fixed_slot !== undefined) {
      const reason = `Cannot move session '${req.sessionId}': session is pinned to a fixed slot (fixed_slot in the edge list).`;
      return {
        success: false,
        rejectionReason: reason,
        violatedConstraint: {
          constraint_id: `pin.${req.sessionId}`,
          kind: 'PINNED_SESSION',
          description: reason,
          entity_ids: [req.sessionId],
        },
      };
    }

    // 4. Reject if pinned occupancy at the target holds the session's cohort, teacher or room
    const roomId = currentSolution.assignment[sessionIndex].room_id;
    const pin = edgeList.pinned_occupancy.find(
      (p) =>
        p.day === req.targetDay &&
        p.period === req.targetWallClockPeriod &&
        ((!!edgeSession && p.cohort_ids.some((c) => cohortsOverlap(c, edgeSession.cohort_id))) ||
          (!!edgeSession && p.faculty_ids.includes(edgeSession.faculty_id)) ||
          p.room_ids.includes(roomId))
    );
    if (pin) {
      const held = [
        ...pin.cohort_ids.map(getCohortLabel),
        ...pin.room_ids.map((id) => `room ${edgeList.rooms.find((r) => r.id === id)?.code ?? id}`),
      ].join(', ');
      const reason = `Slot conflict: ${slotLabel} is held by pinned occupancy (${held}).`;
      return {
        success: false,
        rejectionReason: reason,
        violatedConstraint: {
          constraint_id: `pinned.${req.targetDay}.${req.targetWallClockPeriod}`,
          kind: 'PINNED_BLOCK',
          description: reason,
          entity_ids: [...pin.cohort_ids, ...pin.room_ids, ...pin.faculty_ids, req.sessionId],
        },
      };
    }

    // 5. Reject if moving causes a faculty clash with another session
    const facultyId = edgeSession?.faculty_id;
    if (facultyId) {
      for (const other of currentSolution.assignment) {
        if (other.session_id === req.sessionId) continue;
        const otherEdge = edgeList.sessions.find((s) => s.id === other.session_id);

        if (
          other.day === req.targetDay &&
          other.period === req.targetWallClockPeriod &&
          otherEdge?.faculty_id === facultyId
        ) {
          const faculty = getFaculty(facultyId);
          const reason = `Faculty clash: ${faculty.initials} (${faculty.name}) is already scheduled for session '${other.session_id}' on this slot.`;
          return {
            success: false,
            rejectionReason: reason,
            violatedConstraint: {
              constraint_id: `clash.fac.${facultyId}.${req.targetDay}.${req.targetWallClockPeriod}`,
              kind: 'FACULTY_CLASH',
              description: reason,
              entity_ids: [facultyId, req.sessionId, other.session_id],
            },
          };
        }
      }
    }

    // 6. Valid move: apply updated placement
    const updatedAssignment: SessionAssignment[] = currentSolution.assignment.map((a) => {
      if (a.session_id === req.sessionId) {
        return {
          ...a,
          day: req.targetDay,
          period: req.targetWallClockPeriod,
          room_id: req.targetRoomId ?? a.room_id,
          sub_room_id: req.targetSubRoomId !== undefined ? req.targetSubRoomId : a.sub_room_id,
        };
      }
      return a;
    });

    const updatedSolution: SolvedSolution = {
      ...currentSolution,
      assignment: updatedAssignment,
      displaced: Array.from(new Set([...currentSolution.displaced, req.sessionId])),
    };

    (await validation()).parseSolution(updatedSolution);
    return {
      success: true,
      solution: updatedSolution,
    };
  }
}

export type JobStatus = 'queued' | 'running' | 'solved' | 'infeasible' | 'timeout' | 'error';

const JOB_STATUSES: JobStatus[] = ['queued', 'running', 'solved', 'infeasible', 'timeout', 'error'];

/** The job has ended: no further status follows. */
export const isFinished = (status: JobStatus | undefined) =>
  status !== undefined && status !== 'queued' && status !== 'running';

type Slot = { day: number; period: number };

/** One change a repair job makes to the official timetable (S14c, solver.repair.apply_change). */
export type RepairChange =
  | { kind: 'faculty_unavailable'; faculty_id: string; slots: Slot[] }
  | { kind: 'room_unavailable'; room_id: string; slots: Slot[] }
  | { kind: 'move_session'; session_id: string; day: number; period: number; room_id: string; sub_room_id?: string }
  | { kind: 'substitute_faculty'; session_id: string; faculty_id: string };

/** GET /jobs/{id}. A timeout carries no solution (D33): it never proves infeasibility. */
export interface SolveJob {
  id: string;
  instance_id: string;
  kind?: 'solve' | 'repair';
  time_limit_s: number;
  status: JobStatus;
  /** While running, when the backend reports it (S13d, S14c) */
  phase?: 'search' | 'improve' | 'repair';
  /** Repair: the job id of the solution it started from, or 'committed' (D48) */
  base?: string;
  change?: RepairChange;
  /** Repair: when it became the official timetable (D49) */
  accepted_at?: string;
  /** The job ids of the accepted changes its edge list includes (D52) */
  built_with?: string[];
  /**
   * Finished solve: built with other accepted changes than those in force when it ended, so it
   * is kept but never official (D56, S14i)
   */
  stale?: boolean;
  /** Present when status is solved or infeasible */
  solution?: SolutionContract;
  error?: string;
}

/** GET /instances/{id}/changes row: an accepted change every solve and repair includes (D52). */
export interface AcceptedChange {
  job_id: string;
  change: RepairChange;
  requested_by: string;
  /** null for repairs accepted before S14f */
  accepted_by: string | null;
  accepted_at: string;
}

/** GET /instances/{id}/sessions/{sid}/substitutes (S14g, D53). */
export interface Substitutes {
  session_id: string;
  /** Who teaches it now */
  faculty_id: string;
  /** Best first: the score with this substitute minus the score now */
  candidates: Array<{ faculty_id: string; score_change: number }>;
  /** The other qualified faculty: 'busy', 'unavailable', and what they would break (solver.validate) */
  left_out: Array<{
    faculty_id: string;
    reasons: string[];
    violations: Array<{ kind: string; session_ids: string[]; slots: Slot[]; entity_ids: string[]; detail: string }>;
  }>;
}

/** GET /audit row (S13b). */
export interface AuditEntry {
  id: number;
  actor: string;
  action: string;
  timestamp: string;
  detail: Record<string, unknown> | null;
}

/** A non-2xx response from the backend. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Who is logged in (http mode). The role is for display only: the backend enforces it. */
export interface AuthSession {
  username: string;
  token: string;
  role: UserRole;
  /** The faculty member or cohort the account is linked to (D50); the UI locks to it */
  facultyId?: string | null;
  cohortId?: string | null;
}

/** The session, and whether the last one ended on a 401 (the backend refused its token). */
export interface AuthState {
  session: AuthSession | null;
  expired: boolean;
}

const SESSION_KEY = 'chronos.session';

const isRole = (role: unknown): role is UserRole => typeof role === 'string' && role in ROLE_CAPABILITIES;

/** The token's role claim, decoded without checking the signature (display only); null if none. */
export function roleFromToken(token: string): UserRole | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return isRole(payload.role) ? payload.role : null;
  } catch {
    return null;
  }
}

// sessionStorage may be unavailable (private mode, blocked storage): the session then lives in memory only
function restoreSession(): AuthSession | null {
  try {
    const stored = JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? 'null') as AuthSession | null;
    return typeof stored?.token === 'string' && isRole(stored.role) ? stored : null;
  } catch {
    return null;
  }
}

let authState: AuthState = { session: restoreSession(), expired: false };
const authListeners = new Set<() => void>();

function setAuthState(next: AuthState) {
  authState = next;
  try {
    if (next.session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(next.session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    // memory only
  }
  authListeners.forEach((listener) => listener());
}

export const getAuthState = () => authState;

export function subscribeAuth(listener: () => void) {
  authListeners.add(listener);
  return () => {
    authListeners.delete(listener);
  };
}

/** Log in (a session) or out (null); its token is sent with every request. */
export const setSession = (session: AuthSession | null) => setAuthState({ session, expired: false });

/**
 * The S13a backend over HTTP. The contract examples stay bundled (the backend does not serve
 * them), as do the printed baseline and the example's simulation toggles and moves.
 */
export class HttpChronosApiClient extends MockChronosApiClient {
  constructor(private readonly baseUrl: string = import.meta.env.VITE_API_BASE_URL ?? '/api') {
    super();
  }

  private async request(path: string, init: RequestInit = {}): Promise<unknown> {
    const headers = new Headers(init.headers);
    const { session } = authState;
    // the one place the Authorization header is attached
    if (session) headers.set('Authorization', `Bearer ${session.token}`);
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    // the token was refused (expired, revoked): back to the login screen
    if (response.status === 401 && session && authState.session === session) {
      setAuthState({ session: null, expired: true });
    }
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
      const detail = typeof body?.detail === 'string' ? body.detail : response.statusText;
      throw new ApiError(response.status, `${init.method ?? 'GET'} ${path}: ${response.status} ${detail}`);
    }
    return response.json();
  }

  protected async readInstanceFile(instance: EdgeListInstance, file: InstanceFile): Promise<unknown> {
    try {
      return await this.request(`/instances/${encodeURIComponent(instance)}/${file.replace('_', '-')}`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }

  /** POST /auth/login. The role comes from the response, else from the token's claims. */
  public async login(username: string, password: string): Promise<AuthSession> {
    const body = (await this.request('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })) as { access_token: string; role?: unknown; faculty_id?: string | null; cohort_id?: string | null };
    const role = isRole(body.role) ? body.role : roleFromToken(body.access_token);
    if (role === null) throw new Error('The login response names no role');
    return { username, token: body.access_token, role, facultyId: body.faculty_id ?? null, cohortId: body.cohort_id ?? null };
  }

  /** GET /audit: the newest entries first (administrator only). */
  public async getAudit(limit: number): Promise<AuditEntry[]> {
    return (await this.request(`/audit?limit=${limit}`)) as AuditEntry[];
  }

  public async listInstances(): Promise<InstanceOption[]> {
    const ids = (await this.request('/instances')) as Array<{ id: string }>;
    return [
      ...Object.keys(EDGE_LIST_INSTANCES).map((id) => option(id)),
      ...ids.flatMap(({ id }) => [option(id, true), ...(id === REAL_INSTANCE ? [option(PRINTED_INSTANCE)] : [])]),
    ];
  }

  /** POST /instances/{id}/solve: queue a solve (administrator and coordinator only). */
  public async startSolve(
    instance: EdgeListInstance,
    timeLimitS: number
  ): Promise<{ job_id: string; status: JobStatus }> {
    return (await this.request(`/instances/${encodeURIComponent(instance)}/solve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ time_limit_s: timeLimitS }),
    })) as { job_id: string; status: JobStatus };
  }

  /** POST /instances/{id}/repair: queue a repair of the official timetable (administrator and coordinator only). */
  public async startRepair(
    instance: EdgeListInstance,
    change: RepairChange
  ): Promise<{ job_id: string; status: JobStatus }> {
    return (await this.request(`/instances/${encodeURIComponent(instance)}/repair`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change }),
    })) as { job_id: string; status: JobStatus };
  }

  /** POST /jobs/{id}/accept: make a solved repair official (D49); 409 when its base no longer is. */
  public async acceptRepair(jobId: string): Promise<SolveJob> {
    const job = (await this.request(`/jobs/${encodeURIComponent(jobId)}/accept`, { method: 'POST' })) as SolveJob;
    return job.solution === undefined ? job : { ...job, solution: (await validation()).parseSolution(job.solution) };
  }

  /** GET /jobs/{id}/base-solution: the solution a repair started from (D48). */
  public async getBaseSolution(jobId: string): Promise<SolutionContract> {
    return (await validation()).parseSolution(await this.request(`/jobs/${encodeURIComponent(jobId)}/base-solution`));
  }

  /**
   * GET /instances/{id}/edge-list/current (S14i): the committed edge list with every accepted,
   * uncleared change applied (absences, room closures, substitutions; D52). The contract
   * examples and the printed view are not backend instances: their bundled edge list.
   */
  public async getCurrentEdgeList(instance: EdgeListInstance): Promise<EdgeList> {
    if (isExample(instance) || instance === PRINTED_INSTANCE) return this.getEdgeList(instance);
    const edgeList = await this.request(`/instances/${encodeURIComponent(instance)}/edge-list/current`);
    return (await validation()).validateContract('edge_list', edgeList);
  }

  /** GET /jobs/{id}/edge-list (S14i): the edge list the job ran on (its built_with changes and, for a repair, its own). */
  public async getJobEdgeList(jobId: string): Promise<EdgeList> {
    const edgeList = await this.request(`/jobs/${encodeURIComponent(jobId)}/edge-list`);
    return (await validation()).validateContract('edge_list', edgeList);
  }

  /** GET /instances/{id}/changes: the accepted changes, in acceptance order (D52). */
  public async getChanges(instance: EdgeListInstance): Promise<AcceptedChange[]> {
    return (await this.request(`/instances/${encodeURIComponent(instance)}/changes`)) as AcceptedChange[];
  }

  /** DELETE /instances/{id}/changes: clear the accepted changes (administrator only); returns the cleared ones. */
  public async clearChanges(instance: EdgeListInstance): Promise<AcceptedChange[]> {
    return (await this.request(`/instances/${encodeURIComponent(instance)}/changes`, { method: 'DELETE' })) as AcceptedChange[];
  }

  /** GET .../sessions/{sid}/substitutes: who may take the session where it is (administrator and coordinator only). */
  public async getSubstitutes(instance: EdgeListInstance, sessionId: string): Promise<Substitutes> {
    return (await this.request(
      `/instances/${encodeURIComponent(instance)}/sessions/${encodeURIComponent(sessionId)}/substitutes`
    )) as Substitutes;
  }

  public async getJob(jobId: string): Promise<SolveJob> {
    const job = (await this.request(`/jobs/${encodeURIComponent(jobId)}`)) as SolveJob;
    // an unknown status would be polled forever
    if (!JOB_STATUSES.includes(job.status)) throw new Error(`Job ${jobId} has unknown status '${job.status}'`);
    return job.solution === undefined ? job : { ...job, solution: (await validation()).parseSolution(job.solution) };
  }
}

/** 'static' serves the bundled files (offline, tests); anything else calls the backend. */
export const API_MODE: 'static' | 'http' = import.meta.env.VITE_API_MODE === 'static' ? 'static' : 'http';

/** The client the app uses, by API_MODE. */
export const chronosApiClient: MockChronosApiClient =
  API_MODE === 'static' ? new MockChronosApiClient() : new HttpChronosApiClient();
