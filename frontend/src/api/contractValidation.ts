/**
 * Runtime validation of payloads against the frozen contracts (v1, and solution.v2).
 *
 * The schemas are imported straight from contracts/ (one source of truth);
 * nothing here restates their shape.
 */

import Ajv2020, { type ValidateFunction } from 'ajv/dist/2020';
import solutionSchema from '@contracts/solution_v1.schema.json';
import solutionV2Schema from '@contracts/solution_v2.schema.json';
import edgeListSchema from '@contracts/edge_list_v1.schema.json';
import ingestionSchema from '@contracts/ingestion_v1.schema.json';
import type { ChronosSolutionContractV1 } from '@/types/generated/solution_v1.schema';
import type { ChronosSolutionContractV2 } from '@/types/generated/solution_v2.schema';
import type { ChronosEdgeListContractV1 } from '@/types/generated/edge_list_v1.schema';
import type { ChronosIngestionContractV1 } from '@/types/generated/ingestion_v1.schema';
import type { SolutionContract } from '@/adapters/solution';
import { ContractValidationError } from '@/api/contractError';

interface ContractTypes {
  solution: ChronosSolutionContractV1;
  solution_v2: ChronosSolutionContractV2;
  edge_list: ChronosEdgeListContractV1;
  ingestion: ChronosIngestionContractV1;
}

export type ContractName = keyof ContractTypes;

export { ContractValidationError };

// strictTypes only lints schema authoring (solution_v2's if/then branches omit `type`); validation is unchanged
const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strictTypes: false });

const validators: { [K in ContractName]: ValidateFunction<ContractTypes[K]> } = {
  solution: ajv.compile<ChronosSolutionContractV1>(solutionSchema),
  solution_v2: ajv.compile<ChronosSolutionContractV2>(solutionV2Schema),
  edge_list: ajv.compile<ChronosEdgeListContractV1>(edgeListSchema),
  ingestion: ajv.compile<ChronosIngestionContractV1>(ingestionSchema),
};

export function validateContract<K extends ContractName>(
  contract: K,
  payload: unknown
): ContractTypes[K] {
  const validate = validators[contract];
  if (!validate(payload)) {
    const issues = (validate.errors ?? []).map((e) => {
      const extra = e.keyword === 'additionalProperties' ? `: '${e.params.additionalProperty}'` : '';
      return `${e.instancePath || '/'} ${e.message ?? 'is invalid'}${extra}`;
    });
    throw new ContractValidationError(contract, issues);
  }
  return payload;
}

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
