import { describe, it, expect } from 'vitest';
import { ContractValidationError, validateContract } from '../contractValidation';
import solvedExample from '@contracts/examples/solution_v1.solved.example.json';
import infeasibleExample from '@contracts/examples/solution_v1.infeasible.example.json';
import edgeListExample from '@contracts/examples/edge_list_v1.example.json';
import ingestionExample from '@contracts/examples/ingestion_v1.example.json';

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
