/**
 * The contract-validation error, apart from the validators so the UI can catch it without
 * loading ajv and the schemas (those load lazily with contractValidation.ts).
 */

import type { ContractName } from '@/api/contractValidation';

/** Schema file stem under contracts/ for each contract name. */
const SCHEMA_FILES: { [K in ContractName]: string } = {
  solution: 'solution_v1',
  solution_v2: 'solution_v2',
  edge_list: 'edge_list_v1',
  ingestion: 'ingestion_v1',
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
