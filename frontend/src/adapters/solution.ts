/**
 * Solution contract -> view types.
 *
 * Shapes come from src/types/generated (json2ts over contracts/solution_v1.schema.json).
 * json2ts cannot express the schema's `allOf` if/then branches, so the solved /
 * infeasible split is derived here. Components import these, never the generated
 * file, so adopting solution.v2 touches only src/adapters/.
 */

import type { ChronosSolutionContractV1 } from '@/types/generated/solution_v1.schema';
import { validateContract } from '@/api/contractValidation';

/** Drops the `[k: string]: unknown` json2ts emits for the schema's top-level allOf. */
type KnownKeys<T> = { [K in keyof T as string extends K ? never : K]: T[K] };
type SolutionV1 = KnownKeys<ChronosSolutionContractV1>;
type Branch = 'status' | 'assignment' | 'quality' | 'displaced' | 'diagnosis';
type Present<K extends keyof SolutionV1> = { [P in K]-?: NonNullable<SolutionV1[P]> };

export type SolvedSolution = Omit<SolutionV1, Branch> &
  Present<'assignment' | 'quality' | 'displaced'> & { status: 'solved'; diagnosis?: never };

export type InfeasibleSolution = Omit<SolutionV1, Branch> &
  Present<'diagnosis'> &
  Pick<SolutionV1, 'quality' | 'displaced'> & { status: 'infeasible'; assignment?: never };

export type SolutionContract = SolvedSolution | InfeasibleSolution;

export type SessionAssignment = SolvedSolution['assignment'][number];
export type QualityEvaluation = SolvedSolution['quality'];
export type SolutionMetadata = SolutionV1['metadata'];
export type DayIndex = SessionAssignment['day'];
export type PeriodIndex = SessionAssignment['period'];

/** Validates a raw payload against solution_v1 and returns the solved/infeasible view. */
export function parseSolution(payload: unknown): SolutionContract {
  // ajv has enforced the if/then branches the generated type cannot carry
  return validateContract('solution', payload) as SolutionContract;
}

export function isSolvedSolution(sol: SolutionContract): sol is SolvedSolution {
  return sol.status === 'solved';
}

export function isInfeasibleSolution(sol: SolutionContract): sol is InfeasibleSolution {
  return sol.status === 'infeasible';
}
