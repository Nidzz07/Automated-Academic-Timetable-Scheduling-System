/**
 * Solution contract -> view types.
 *
 * Shapes come from src/types/generated (json2ts over contracts/solution_v1.schema.json and
 * contracts/solution_v2.schema.json). json2ts cannot express the schemas' `allOf` if/then
 * branches, so the solved / infeasible split, and v2's diagnosis and quality-rule entries
 * (which json2ts collapses to `{ [k: string]: unknown }`), are written out here; ajv has
 * enforced them before any value reaches these types. Components read the views below
 * (toQualityView, toDiagnosisView), never a raw v2 diagnosis or breakdown.
 */

import type { ChronosSolutionContractV1 } from '@/types/generated/solution_v1.schema';
import type {
  ChronosSolutionContractV2,
  Kind,
  Placement,
  SlotRef,
} from '@/types/generated/solution_v2.schema';

/** Drops the `[k: string]: unknown` json2ts emits for the schema's top-level allOf. */
type KnownKeys<T> = { [K in keyof T as string extends K ? never : K]: T[K] };
type SolutionV1 = KnownKeys<ChronosSolutionContractV1>;
type SolutionV2 = KnownKeys<ChronosSolutionContractV2>;
type Branch = 'status' | 'assignment' | 'quality' | 'displaced' | 'diagnosis';
type Present<S, K extends keyof S> = { [P in K]-?: NonNullable<S[P]> };

/** A v2 breakdown entry: the schema's evaluated / not_evaluated branches. */
export type QualityRule =
  | {
      rule_id: string;
      status: 'evaluated';
      weight: number;
      raw: number;
      penalty: number;
      explanation: string;
    }
  | { rule_id: string; status: 'not_evaluated'; weight: number; reason: string };

interface ConflictV2 {
  constraint_id: string;
  /** Closed enum (10 members); UNSATISFIABLE_DOMAIN / INFEASIBLE_INSTANCE are retired. */
  kind: Kind;
  description: string;
  entity_ids: string[];
  slots: SlotRef[];
}

interface RelaxationV2 {
  constraint_id: string;
  description: string;
  action: {
    action_type:
      | 'UNFIX_SLOT'
      | 'RELAX_FACULTY_AVAILABILITY'
      | 'RELAX_PINNED_BLOCK'
      | 'RECLASSIFY_ROOM'
      | 'MANUAL';
    params: unknown;
  };
  verification: {
    status: 'restored' | 'still_infeasible' | 'timeout' | 'not_attempted';
    runtime_ms: number | null;
  };
}

/** contract row 9 (D43) added presolve; ajv enforces the enum, wording.ts words each method. */
export type DiagnosisMethod = 'mus' | 'search_exhaustion' | 'presolve';

interface DiagnosisV2 {
  method: DiagnosisMethod;
  minimal_conflicting_set: ConflictV2[];
  /** Present iff method is mus or presolve. */
  suggested_relaxation?: RelaxationV2;
  partial_placement: Placement[];
  unplaced_session_ids: string[];
}

type SolvedV1 = Omit<SolutionV1, Branch> &
  Present<SolutionV1, 'assignment' | 'quality' | 'displaced'> & { status: 'solved'; diagnosis?: never };

type InfeasibleV1 = Omit<SolutionV1, Branch> &
  Present<SolutionV1, 'diagnosis'> &
  Pick<SolutionV1, 'quality' | 'displaced'> & { status: 'infeasible'; assignment?: never };

type SolvedV2 = Omit<SolutionV2, Branch> &
  Present<SolutionV2, 'assignment' | 'displaced'> & {
    status: 'solved';
    quality: Omit<NonNullable<SolutionV2['quality']>, 'breakdown'> & { breakdown: QualityRule[] };
    diagnosis?: never;
  };

type InfeasibleV2 = Omit<SolutionV2, Branch> & {
  status: 'infeasible';
  diagnosis: DiagnosisV2;
  assignment?: never;
  quality?: never;
  displaced?: never;
};

export type SolvedSolution = SolvedV1 | SolvedV2;
export type InfeasibleSolution = InfeasibleV1 | InfeasibleV2;
export type SolutionContract = SolvedSolution | InfeasibleSolution;

export type SessionAssignment = SolvedSolution['assignment'][number];
export type SolutionMetadata = SolutionV1['metadata'];
export type DayIndex = SessionAssignment['day'];
export type PeriodIndex = SessionAssignment['period'];
export type { Kind as ConstraintKind, SlotRef };

// parseSolution (ajv) lives in api/contractValidation.ts, which loads lazily

export function isSolvedSolution(sol: SolutionContract): sol is SolvedSolution {
  return sol.status === 'solved';
}

export function isInfeasibleSolution(sol: SolutionContract): sol is InfeasibleSolution {
  return sol.status === 'infeasible';
}

/** The solver's quality block, as displayed. Nothing here is computed in the browser (D34). */
export interface QualityView {
  /** null when no rule was evaluated: the solver's score is then a stand-in, not a measurement. */
  score: number | null;
  /** null: solution.v1 carries no rule-set version. */
  rulesVersion: string | null;
  /** Non-empty means `score` covers only the evaluated rules. */
  notEvaluatedRuleIds: string[];
  rules: QualityRule[];
}

export function toQualityView(sol: SolvedSolution): QualityView {
  const view: QualityView =
    sol.schema_version === 'solution.v2'
      ? {
          score: sol.quality.score,
          rulesVersion: sol.quality.rules_version,
          notEvaluatedRuleIds: sol.quality.not_evaluated_rule_ids,
          rules: sol.quality.breakdown,
        }
      : {
          // solution.v1 has no per-rule status: every listed rule ran
          score: sol.quality.score,
          rulesVersion: null,
          notEvaluatedRuleIds: [],
          rules: sol.quality.breakdown.map((r) => ({ ...r, status: 'evaluated' as const })),
        };
  // A score over zero evaluated rules (the solver's stand-in until S10) is not shown
  return view.rules.some((r) => r.status === 'evaluated') ? view : { ...view, score: null };
}

export interface ConflictView {
  constraint_id: string;
  /** A v2 `Kind`; solution.v1 kinds are free strings. */
  kind: string;
  description: string;
  entity_ids: string[];
  /** Cells on the wall-clock axis; empty when not slot-specific or from solution.v1. */
  slots: SlotRef[];
}

export interface DiagnosisView {
  /** null: solution.v1 does not say how it was diagnosed. */
  method: DiagnosisMethod | null;
  minimal_conflicting_set: ConflictView[];
  suggested_relaxation: {
    constraint_id: string;
    description: string;
    /** null in solution.v1, which has no typed action or verification. */
    action_type: RelaxationV2['action']['action_type'] | null;
    /** The action's params (contracts/solution_v2 params_*); null in solution.v1 */
    action_params: Record<string, unknown> | null;
    verification: RelaxationV2['verification'] | null;
  } | null;
  /** Diagnostic only, never a timetable. null: solution.v1 carries none. */
  partial_placement: Placement[] | null;
  unplaced_session_ids: string[] | null;
}

export function toDiagnosisView(sol: InfeasibleSolution): DiagnosisView {
  if (sol.schema_version === 'solution.v2') {
    const d = sol.diagnosis;
    const r = d.suggested_relaxation;
    return {
      method: d.method,
      minimal_conflicting_set: d.minimal_conflicting_set,
      suggested_relaxation: r
        ? {
            constraint_id: r.constraint_id,
            description: r.description,
            action_type: r.action.action_type,
            action_params: r.action.params as Record<string, unknown>,
            verification: r.verification,
          }
        : null,
      partial_placement: d.partial_placement,
      unplaced_session_ids: d.unplaced_session_ids,
    };
  }
  const d = sol.diagnosis;
  return {
    method: null,
    minimal_conflicting_set: d.minimal_conflicting_set.map((c) => ({ ...c, slots: [] })),
    suggested_relaxation: { ...d.suggested_relaxation, action_type: null, action_params: null, verification: null },
    partial_placement: null,
    unplaced_session_ids: null,
  };
}

/** One session a repair changed against the solution it started from. */
export interface RepairChangeView {
  sessionId: string;
  before: SessionAssignment;
  after: SessionAssignment;
  /** In the contract's `displaced` (its slot changed); else only its room changed */
  slotChanged: boolean;
}

/**
 * A repair's changes (D48): slot changes are the result's `displaced`, as the contract defines it;
 * room-only changes are found by comparing with the solution the repair started from.
 */
export function repairChanges(base: SolvedSolution, result: SolvedSolution): RepairChangeView[] {
  const before = new Map(base.assignment.map((a) => [a.session_id, a]));
  const displaced = new Set(result.displaced);
  return result.assignment.flatMap((after) => {
    const was = before.get(after.session_id);
    const slotChanged = displaced.has(after.session_id);
    if (!was || (!slotChanged && was.room_id === after.room_id && was.sub_room_id === after.sub_room_id)) return [];
    return [{ sessionId: after.session_id, before: was, after, slotChanged }];
  });
}
