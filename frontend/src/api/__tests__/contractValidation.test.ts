import { describe, it, expect } from 'vitest';
import { ContractValidationError, validateContract } from '../contractValidation';
import solvedExample from '@contracts/examples/solution_v1.solved.example.json';
import infeasibleExample from '@contracts/examples/solution_v1.infeasible.example.json';
import edgeListExample from '@contracts/examples/edge_list_v1.example.json';
import ingestionExample from '@contracts/examples/ingestion_v1.example.json';
import solvedV2Example from '@contracts/examples/solution_v2.solved.example.json';
import infeasibleV2Example from '@contracts/examples/solution_v2.infeasible.example.json';
import d6GridExample from '@contracts/examples/edge_list_v1.d6_grid.example.json';

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

function issuesOf(fn: () => unknown): string[] {
  try {
    fn();
  } catch (err) {
    expect(err).toBeInstanceOf(ContractValidationError);
    return (err as ContractValidationError).issues;
  }
  throw new Error('expected a ContractValidationError');
}

describe('validateContract (schemas loaded from contracts/)', () => {
  it('accepts every v1 example payload', () => {
    expect(validateContract('solution', solvedExample).status).toBe('solved');
    expect(validateContract('solution', infeasibleExample).status).toBe('infeasible');
    expect(validateContract('edge_list', edgeListExample).schema_version).toBe('edge_list.v1');
    expect(validateContract('ingestion', ingestionExample).schema_version).toBe('ingestion.v1');
  });

  it('rejects a solved payload that breaks the if/then branch (no quality)', () => {
    const bad = clone(solvedExample) as Record<string, unknown>;
    delete bad.quality;
    expect(issuesOf(() => validateContract('solution', bad))).toContain(
      "/ must have required property 'quality'"
    );
  });

  it('rejects an out-of-range day and an infeasible payload carrying an assignment', () => {
    const badDay = clone(solvedExample);
    badDay.assignment[0].day = 7;
    expect(issuesOf(() => validateContract('solution', badDay))).toContain(
      '/assignment/0/day must be <= 4'
    );

    const badInfeasible = { ...clone(infeasibleExample), assignment: [] };
    expect(issuesOf(() => validateContract('solution', badInfeasible)).join('\n')).toMatch(
      /\/assignment/
    );
  });

  it('rejects extra fields at the top level and in nested objects', () => {
    const topLevel = { ...clone(solvedExample), rules_version: 'v2' };
    expect(issuesOf(() => validateContract('solution', topLevel))).toContain(
      "/ must NOT have additional properties: 'rules_version'"
    );

    const nested = clone(solvedExample);
    Object.assign(nested.assignment[0], { teacher: 'AGN' });
    expect(issuesOf(() => validateContract('solution', nested))).toContain(
      "/assignment/0 must NOT have additional properties: 'teacher'"
    );
  });

  it('names the contract in the error', () => {
    expect(() => validateContract('edge_list', {})).toThrow(
      expect.objectContaining({
        name: 'ContractValidationError',
        contract: 'edge_list',
        message: expect.stringContaining('edge_list_v1.schema.json'),
      })
    );
  });
});

describe('validateContract: solution_v2 and the D6 edge list', () => {
  it('accepts the v2 examples and the D6 grid edge list', () => {
    expect(validateContract('solution_v2', solvedV2Example).status).toBe('solved');
    expect(validateContract('solution_v2', infeasibleV2Example).status).toBe('infeasible');
    expect(validateContract('edge_list', d6GridExample).slot_grid.teaching_periods).toContain(5);
  });

  it('rejects a v1 payload as v2, and names solution_v2 in the error', () => {
    expect(() => validateContract('solution_v2', solvedExample)).toThrow(
      expect.objectContaining({
        schema: 'solution_v2',
        message: expect.stringContaining('solution_v2.schema.json'),
      })
    );
  });

  it('rejects a retired diagnosis kind (the kind enum is closed)', () => {
    const bad = clone(infeasibleV2Example);
    bad.diagnosis.minimal_conflicting_set[0].kind = 'UNSATISFIABLE_DOMAIN';
    expect(issuesOf(() => validateContract('solution_v2', bad)).join('\n')).toMatch(
      /minimal_conflicting_set\/0\/kind must be equal to one of the allowed values/
    );
  });

  it('rejects a not_evaluated rule that carries a number', () => {
    const bad = clone(solvedV2Example);
    Object.assign(bad.quality.breakdown[3], { penalty: 0 });
    expect(issuesOf(() => validateContract('solution_v2', bad)).join('\n')).toMatch(
      /breakdown\/3\/penalty/
    );
  });

  it('rejects search_exhaustion with a relaxation, and an infeasible result with a quality block', () => {
    const exhausted = clone(infeasibleV2Example) as { diagnosis: Record<string, unknown> };
    exhausted.diagnosis.method = 'search_exhaustion';
    expect(() => validateContract('solution_v2', exhausted)).toThrow(ContractValidationError);

    const scored = { ...clone(infeasibleV2Example), quality: clone(solvedV2Example).quality };
    expect(issuesOf(() => validateContract('solution_v2', scored)).join('\n')).toMatch(/\/quality/);
  });
});
