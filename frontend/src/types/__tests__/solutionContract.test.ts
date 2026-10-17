import { describe, it, expect } from 'vitest';
import solvedFixture from '@contracts/examples/solution_v1.solved.example.json';
import infeasibleFixture from '@contracts/examples/solution_v1.infeasible.example.json';
import solvedV2Fixture from '@contracts/examples/solution_v2.solved.example.json';
import infeasibleV2Fixture from '@contracts/examples/solution_v2.infeasible.example.json';
import {
  SolvedSolution,
  InfeasibleSolution,
  SolutionContract,
  isSolvedSolution,
  isInfeasibleSolution,
  parseSolution,
} from '@/adapters/solution';

function parseSolved(raw: unknown): SolvedSolution {
  const sol = parseSolution(raw);
  if (!isSolvedSolution(sol)) throw new Error('expected a solved payload');
  return sol;
}

function parseInfeasible(raw: unknown): InfeasibleSolution {
  const sol = parseSolution(raw);
  if (!isInfeasibleSolution(sol)) throw new Error('expected an infeasible payload');
  return sol;
}

describe('Solution Contract v1 TypeScript Typing', () => {
  it('correctly types and validates the solved fixture', () => {
    const solved: SolvedSolution = parseSolved(solvedFixture);
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
    const infeasible: InfeasibleSolution = parseInfeasible(infeasibleFixture);
    expect(isInfeasibleSolution(infeasible)).toBe(true);
    expect(isSolvedSolution(infeasible)).toBe(false);

    // Verify diagnosis fields
    expect(infeasible.schema_version).toBe('solution.v1');
    expect(infeasible.status).toBe('infeasible');
    expect(infeasible.diagnosis.minimal_conflicting_set.length).toBe(3);
    expect(infeasible.diagnosis.suggested_relaxation?.constraint_id).toBe('lab-rooms.monday-10.00');
    expect(infeasible.metadata.algorithm).toBeDefined();
  });

  it('types and validates the solution.v2 fixtures', () => {
    const solved = parseSolved(solvedV2Fixture);
    const infeasible = parseInfeasible(infeasibleV2Fixture);
    expect(solved.schema_version).toBe('solution.v2');
    expect(infeasible.schema_version).toBe('solution.v2');
    if (infeasible.schema_version === 'solution.v2') {
      expect(infeasible.diagnosis.method).toBe('mus');
      expect(infeasible.diagnosis.unplaced_session_ids).toHaveLength(4);
    }
  });

  it('enforces discriminated union exhaustiveness', () => {
    const payloads: SolutionContract[] = [
      parseSolved(solvedFixture),
      parseInfeasible(infeasibleFixture),
      parseSolved(solvedV2Fixture),
      parseInfeasible(infeasibleV2Fixture),
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
