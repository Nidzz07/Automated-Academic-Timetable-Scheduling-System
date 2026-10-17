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

interface ContractTypes {
  solution: ChronosSolutionContractV1;
  solution_v2: ChronosSolutionContractV2;
  edge_list: ChronosEdgeListContractV1;
  ingestion: ChronosIngestionContractV1;
}

export type ContractName = keyof ContractTypes;

/** Schema file stem under contracts/ for each contract name. */
const SCHEMA_FILES: { [K in ContractName]: string } = {
  solution: 'solution_v1',
  solution_v2: 'solution_v2',
  edge_list: 'edge_list_v1',
  ingestion: 'ingestion_v1',
};

// strictTypes only lints schema authoring (solution_v2's if/then branches omit `type`); validation is unchanged
const ajv = new Ajv2020({ allErrors: true, allowUnionTypes: true, strictTypes: false });

const validators: { [K in ContractName]: ValidateFunction<ContractTypes[K]> } = {
  solution: ajv.compile<ChronosSolutionContractV1>(solutionSchema),
  solution_v2: ajv.compile<ChronosSolutionContractV2>(solutionV2Schema),
  edge_list: ajv.compile<ChronosEdgeListContractV1>(edgeListSchema),
  ingestion: ajv.compile<ChronosIngestionContractV1>(ingestionSchema),
};

/** Thrown when a payload does not match its contract schema. */
export class ContractValidationError extends Error {
  /** Schema file stem, e.g. 'solution_v2'. */
  readonly schema: string;

  constructor(
    readonly contract: ContractName,
    readonly issues: string[]
  ) {
    super(`Payload does not match ${SCHEMA_FILES[contract]}.schema.json: ${issues.join('; ')}`);
    this.name = 'ContractValidationError';
    this.schema = SCHEMA_FILES[contract];
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
