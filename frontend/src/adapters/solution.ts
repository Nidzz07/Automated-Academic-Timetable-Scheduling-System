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
import { validateContract } from '@/api/contractValidation';

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

/**
 * Display label per diagnosis.method: the one place a method is named. A new method in the
 * contract is one more line here; ajv still enforces the enum.
 */
export const DIAGNOSIS_METHOD_LABELS = {
  mus: { badge: 'MUS Extraction', text: 'The solver proved no conflict-free assignment exists under the current constraints and isolated a Minimal Unsatisfiable Subset (MUS).' },
  search_exhaustion: { badge: 'Search Exhaustion', text: 'Complete search proved no conflict-free assignment exists under the current constraints, but no explanation was extracted.' },
  // contract row 9 (D43): a pre-solve certificate, proven but not minimal
  presolve: { badge: 'Presolve', text: 'Proved infeasible by a counting check (not minimal)' },
};
/** solution.v1 does not say how it was diagnosed. */
const UNSTATED_METHOD_LABEL = { badge: 'Method not stated (solution.v1)', text: 'The solver reported no conflict-free assignment exists under the current constraints.' };

type DiagnosisMethod = keyof typeof DIAGNOSIS_METHOD_LABELS;

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

/**
 * Validates a raw payload and returns the solved/infeasible view. A payload declaring
 * `solution.v2` is held to solution_v2.schema.json; anything else to solution_v1.
 */
export function parseSolution(payload: unknown): SolutionContract {
  const isV2 = (payload as { schema_version?: unknown } | null)?.schema_version === 'solution.v2';
  // ajv has enforced the if/then branches the generated types cannot carry
  return (
    isV2 ? validateContract('solution_v2', payload) : validateContract('solution', payload)
  ) as SolutionContract;
}

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
  methodLabel: { badge: string; text: string };
  minimal_conflicting_set: ConflictView[];
  suggested_relaxation: {
    constraint_id: string;
    description: string;
    /** null in solution.v1, which has no typed action or verification. */
    action_type: RelaxationV2['action']['action_type'] | null;
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
      methodLabel: DIAGNOSIS_METHOD_LABELS[d.method],
      minimal_conflicting_set: d.minimal_conflicting_set,
      suggested_relaxation: r
        ? {
            constraint_id: r.constraint_id,
            description: r.description,
            action_type: r.action.action_type,
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
    methodLabel: UNSTATED_METHOD_LABEL,
    minimal_conflicting_set: d.minimal_conflicting_set.map((c) => ({ ...c, slots: [] })),
    suggested_relaxation: { ...d.suggested_relaxation, action_type: null, verification: null },
    partial_placement: null,
    unplaced_session_ids: null,
  };
}
