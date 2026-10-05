import { describe, it, expect } from 'vitest';
import solvedFixture from '@/fixtures/solution_v1.solved.example.json';
import infeasibleFixture from '@/fixtures/solution_v1.infeasible.example.json';
import {
  SolvedSolution,
  InfeasibleSolution,
  SolutionContract,
  isSolvedSolution,
  isInfeasibleSolution,
} from '../solution';

describe('Solution Contract v1 TypeScript Typing', () => {
  it('correctly types and validates the solved fixture', () => {
    const solved: SolvedSolution = solvedFixture as unknown as SolvedSolution;
    expect(isSolvedSolution(solved)).toBe(true);
    expect(isInfeasibleSolution(solved)).toBe(false);

    // Verify fields
    expect(solved.schema_version).toBe('solution.v1');
    expect(solved.status).toBe('solved');
    expect(solved.assignment.length).toBeGreaterThan(0);
    expect(solved.quality.score).toBe(93.2);
    expect(solved.quality.breakdown.length).toBe(2);
    expect(Array.isArray(solved.displaced)).toBe(true);
    expect(solved.metadata.algorithm).toBeDefined();
  });

  it('correctly types and validates the infeasible fixture', () => {
    const infeasible: InfeasibleSolution = infeasibleFixture as unknown as InfeasibleSolution;
    expect(isInfeasibleSolution(infeasible)).toBe(true);
    expect(isSolvedSolution(infeasible)).toBe(false);

    // Verify diagnosis fields
    expect(infeasible.schema_version).toBe('solution.v1');
    expect(infeasible.status).toBe('infeasible');
    expect(infeasible.diagnosis.minimal_conflicting_set.length).toBe(3);
    expect(infeasible.diagnosis.suggested_relaxation.constraint_id).toBe('lab-rooms.monday-10.00');
    expect(infeasible.metadata.algorithm).toBeDefined();
  });

  it('enforces discriminated union exhaustiveness', () => {
    const payloads: SolutionContract[] = [
      solvedFixture as unknown as SolvedSolution,
      infeasibleFixture as unknown as InfeasibleSolution,
    ];

    payloads.forEach((payload) => {
      switch (payload.status) {
        case 'solved':
          expect(payload.assignment).toBeDefined();
          expect(payload.quality).toBeDefined();
          break;
        case 'infeasible':
          expect(payload.diagnosis).toBeDefined();
          expect(payload.diagnosis.minimal_conflicting_set).toBeDefined();
          break;
        default: {
          // Exhaustive check compile check
          const _exhaustive: never = payload;
          throw new Error(`Unhandled case: ${_exhaustive}`);
        }
      }
    });
  });
});
