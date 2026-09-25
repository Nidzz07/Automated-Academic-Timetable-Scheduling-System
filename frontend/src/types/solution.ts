/**
 * TypeScript definitions mirroring contracts/solution_v1.schema.json.
 * 
 * Frozen Contract 3 of 3: Solver -> API (JSON solution contract).
 * 
 * Exactly one of `assignment` or `diagnosis` is present:
 * - A complete timetable with an itemised quality breakdown (`status: 'solved'`)
 * - Or an infeasibility result carrying the minimal conflicting constraint set
 *   and suggested relaxation (`status: 'infeasible'`).
 * 
 * An invalid shape is a compile error, not a runtime surprise.
 */

/** Schema revision identifier */
export type SolutionSchemaVersion = "solution.v1";

/** Solver status outcome */
export type SolutionStatus = "solved" | "infeasible";

/** Teaching day index: Monday=0 .. Friday=4 */
export type DayIndex = 0 | 1 | 2 | 3 | 4;

/** Period index on the wall-clock / teaching grid */
export type PeriodIndex = number;

/** Stable opaque string identifier */
export type Id = string;

/**
 * Individual session placement produced by the solver.
 */
export interface SessionAssignment {
  /** Session identifier matching the edge-list contract */
  session_id: Id;
  /** Teaching day index (0 = Monday .. 4 = Friday) */
  day: DayIndex;
  /**
   * Starting period on the edge-list wall-clock grid.
   * A session of duration n occupies this period and the next n-1 periods in teaching order.
   */
  period: PeriodIndex;
  /** Physical room. Parent room when sub_room_id is specified. */
  room_id: Id;
  /** Sub-room within room_id (e.g. '702-A'). null when occupying the whole room. */
  sub_room_id: string | null;
}

/**
 * Single quality rule contribution.
 */
export interface QualityBreakdownItem {
  /** Rule identifier as declared in solver/rules/quality_rules.yaml */
  rule_id: string;
  /** Weight the rule carried from the YAML */
  weight: number;
  /** The measured quantity before weighting (e.g. violating count) */
  raw: number;
  /** Penalty contribution to score (typically weight * raw) */
  penalty: number;
  /** Human-readable explanation in institutional terms. Never an internal id. */
  explanation: string;
}

/**
 * Itemised quality score for a solved timetable.
 */
export interface QualityEvaluation {
  /** Aggregate quality score. Higher is better. */
  score: number;
  /** One entry per quality rule that fired */
  breakdown: QualityBreakdownItem[];
}

/**
 * Individual constraint member of the minimal unsatisfiable subset (MUS).
 */
export interface ConflictingConstraint {
  /** Stable identifier for the constraint */
  constraint_id: string;
  /** Constraint class, e.g. 'FACULTY_CLASH', 'ROOM_CAPACITY', 'LAB_CONTIGUITY', 'PINNED_BLOCK', 'FACULTY_UNAVAILABLE' */
  kind: string;
  /** Institutional terms only - named faculty, rooms and cohorts */
  description: string;
  /** IDs of the faculty, rooms, cohorts and sessions involved */
  entity_ids: Id[];
}

/**
 * Smallest relaxation that restores feasibility.
 */
export interface SuggestedRelaxation {
  /** Identifier of the constraint to relax (must be in minimal_conflicting_set) */
  constraint_id: string;
  /** Institutional description of the relaxation */
  description: string;
}

/**
 * Infeasibility diagnosis payload explaining why no valid timetable exists.
 */
export interface InfeasibilityDiagnosis {
  /** Minimal unsatisfiable subset (MUS) */
  minimal_conflicting_set: ConflictingConstraint[];
  /** Smallest single change that restores feasibility */
  suggested_relaxation: SuggestedRelaxation;
}

/**
 * Solver run statistics, always present for both outcomes.
 */
export interface SolutionMetadata {
  /** Which algorithm produced this result */
  algorithm: string;
  /** Wall-clock solve time in milliseconds */
  runtime_ms: number;
  /** Total vertices (sessions) in the problem instance */
  sessions_total: number;
  /** Vertices successfully coloured / placed */
  sessions_assigned: number;
  /** Distinct slots occupied (chromatic number). null when infeasible. */
  slots_used: number | null;
  /** Backtracking steps taken. null when algorithm does not backtrack. */
  backtracks: number | null;
}

/**
 * Solved solution contract shape.
 */
export interface SolvedSolution {
  schema_version: SolutionSchemaVersion;
  status: "solved";
  assignment: SessionAssignment[];
  quality: QualityEvaluation;
  displaced: Id[];
  metadata: SolutionMetadata;
  diagnosis?: never;
}

/**
 * Infeasible solution contract shape.
 */
export interface InfeasibleSolution {
  schema_version: SolutionSchemaVersion;
  status: "infeasible";
  diagnosis: InfeasibilityDiagnosis;
  metadata: SolutionMetadata;
  assignment?: never;
  quality?: never;
  displaced?: never;
}

/**
 * Discriminated union of the frozen Solution Contract v1.
 */
export type SolutionContract = SolvedSolution | InfeasibleSolution;

/** Type guard to check if a solution is solved */
export function isSolvedSolution(sol: SolutionContract): sol is SolvedSolution {
  return sol.status === "solved";
}

/** Type guard to check if a solution is infeasible */
export function isInfeasibleSolution(sol: SolutionContract): sol is InfeasibleSolution {
  return sol.status === "infeasible";
}
