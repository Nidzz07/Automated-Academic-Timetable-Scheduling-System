/**
 * Runtime validation of payloads against the frozen v1 contracts.
 *
 * The schemas are imported straight from contracts/ (one source of truth);
 * nothing here restates their shape.
 */

import Ajv2020, { type ValidateFunction } from 'ajv/dist/2020';
import solutionSchema from '@contracts/solution_v1.schema.json';
import edgeListSchema from '@contracts/edge_list_v1.schema.json';
import ingestionSchema from '@contracts/ingestion_v1.schema.json';
import type { ChronosSolutionContractV1 } from '@/types/generated/solution_v1.schema';
import type { ChronosEdgeListContractV1 } from '@/types/generated/edge_list_v1.schema';
import type { ChronosIngestionContractV1 } from '@/types/generated/ingestion_v1.schema';

interface ContractTypes {
  solution: ChronosSolutionContractV1;
  edge_list: ChronosEdgeListContractV1;
  ingestion: ChronosIngestionContractV1;
}

export type ContractName = keyof ContractTypes;

const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true });

const validators: { [K in ContractName]: ValidateFunction<ContractTypes[K]> } = {
  solution: ajv.compile<ChronosSolutionContractV1>(solutionSchema),
  edge_list: ajv.compile<ChronosEdgeListContractV1>(edgeListSchema),
  ingestion: ajv.compile<ChronosIngestionContractV1>(ingestionSchema),
};

/** Thrown when a payload does not match its contract schema. */
export class ContractValidationError extends Error {
  constructor(
    readonly contract: ContractName,
    readonly issues: string[]
  ) {
    super(`Payload does not match ${contract}_v1.schema.json: ${issues.join('; ')}`);
    this.name = 'ContractValidationError';
  }
}

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
