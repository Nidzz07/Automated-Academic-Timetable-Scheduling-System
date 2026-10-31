import React from 'react';
import { InfeasibleSolution, toDiagnosisView } from '@/adapters/solution';
import { EdgeList, Labels, diagnosisName, entityName, EXAMPLE_LABELS, pinName, slotText, slotsText } from '@/adapters/timetable';
import { Button } from '@/components/ui/button';
import { formatDuration } from '@/lib/format';
import {
  REPAIR_NOT_APPLIED,
  UI,
  constraintKindLabel,
  diagnosisHeadings,
  diagnosisMethodLabel,
  methodText,
  partialPlacementText,
  readableDiagnosisText,
  readableSolverText,
  relaxationActionLabel,
  searchStepsText,
  verificationLabel,
} from '@/lib/wording';
import { MethodDetails } from './MethodDetails';
import { AlertTriangle, Lightbulb, ArrowRight } from 'lucide-react';

type Slot = { day: number; period: number };

/** How many of a constraint's entities "Involves" lists by name before "and N more". */
const LISTED_ENTITIES = 8;

/** The contract's codes and ids: small secondary text beside the words, never the main text. */
const CODE_CLASS = 'font-mono text-[11px] font-normal text-muted-foreground';

/** The ids a relaxation's params name (contracts/solution_v2 params_*), by name; its pin (D51), if any, by unique_label. */
function relaxationTargets(params: Record<string, unknown>, name: (id: string) => string, pin: string | null): string[] {
  const ids = ['session_id', 'faculty_id', 'room_id', 'entity_id'].flatMap((k) =>
    typeof params[k] === 'string' ? [name(params[k] as string)] : []
  );
  const slots = [...((params.slots as Slot[] | undefined) ?? []), ...(params.slot ? [params.slot as Slot] : [])];
  return [...ids, ...(pin ? [`fixed item ${pin}`] : []), ...(slots.length ? [slotsText(slots)] : [])];
}

interface InfeasibilityDiagnosisPanelProps {
  infeasibleSolution: InfeasibleSolution;
  /** The edge list diagnosed: ids are then shown by name, pins by their unique_label (D41) */
  edgeList?: EdgeList;
  labels?: Labels;
  /** The diagnosis of a repair: the change is what is impossible, and the official timetable stays */
  forRepair?: boolean;
  onApplyRelaxation?: (constraintId: string) => void;
  onSwitchToSolved?: () => void;
}

/**
 * Why no timetable exists: the solver's diagnosis in plain words, every id by name (D51), each
 * constraint's kind by its meaning with the contract's code as small text beside it.
 */
export const InfeasibilityDiagnosisPanel: React.FC<InfeasibilityDiagnosisPanelProps> = ({
  infeasibleSolution,
  edgeList,
  labels = EXAMPLE_LABELS,
  forRepair = false,
  onApplyRelaxation,
  onSwitchToSolved,
}) => {
  const name = (id: string) => (edgeList ? entityName(id, edgeList, labels) : id);
  // the solver's sentences name everything by id: by name where the edge list knows them
  const text = (t: string) =>
    edgeList ? readableDiagnosisText(t, (id) => diagnosisName(id, edgeList, labels)) : readableSolverText(t);
  // a `pin.<i>` constraint id is pinned_occupancy[i], named by display.json pins[i] (D51)
  const pin = (constraintId: string) => (edgeList ? pinName(constraintId, edgeList, labels) : null);
  const { metadata } = infeasibleSolution;
  const diagnosis = toDiagnosisView(infeasibleSolution);
  const { minimal_conflicting_set, suggested_relaxation, partial_placement, unplaced_session_ids } = diagnosis;
  const method = diagnosisMethodLabel(diagnosis.method);
  const headings = diagnosisHeadings(forRepair);

  return (
    <section data-testid="infeasibility-panel" className="space-y-4 rounded-lg border-2 border-destructive/60 bg-card p-4 sm:p-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div className="flex items-start gap-3">
          <AlertTriangle aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-destructive" />
          <div>
            <h2 className="text-xl font-semibold">{headings.title}</h2>
            <p>{method.text}</p>
            <p className={CODE_CLASS}>
              <span data-testid="diagnosis-method">{method.badge}</span>
            </p>
          </div>
        </div>

        {onSwitchToSolved && (
          <Button variant="outline" size="sm" onClick={onSwitchToSolved} className="gap-1">
            <span>{UI.showSolved}</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Solver run statistics */}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="font-semibold">{UI.howChecked}</dt>
          <dd>{methodText(metadata.algorithm)}</dd>
          <dd>
            <MethodDetails algorithm={metadata.algorithm} />
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Time taken</dt>
          <dd>{formatDuration(metadata.runtime_ms)}</dd>
        </div>
        {forRepair ? (
          <div data-testid="repair-not-applied">
            <dt className="font-semibold">Official timetable</dt>
            <dd>Unchanged. {REPAIR_NOT_APPLIED}</dd>
          </div>
        ) : (
          <div>
            <dt className="font-semibold">Sessions placed before it stopped</dt>
            <dd>
              {metadata.sessions_assigned} / {metadata.sessions_total} sessions placed
            </dd>
          </div>
        )}
        <div>
          <dt className="font-semibold">{UI.searchEffort}</dt>
          <dd>{searchStepsText(metadata.backtracks)}</dd>
        </div>
      </dl>

      {/* The conflicting rules; empty when the method is search exhaustion */}
      {minimal_conflicting_set.length > 0 && (
        <section className="space-y-2">
          <div>
            <h3 className="text-lg font-semibold">{headings.why}</h3>
            <p className="text-xs">
              These {minimal_conflicting_set.length} rules cannot all hold.
              {diagnosis.method !== 'presolve' && ' Drop any one of them and a timetable exists.'}
            </p>
          </div>
          <ul data-testid="minimal-conflicting-set" className="space-y-2">
            {minimal_conflicting_set.map((constraint) => (
              <li
                key={constraint.constraint_id}
                data-testid={`conflicting-constraint-${constraint.constraint_id}`}
                className="space-y-1 rounded-md border border-border p-3"
              >
                <p data-testid={`constraint-kind-${constraint.kind}`} className="font-semibold">
                  {constraint.constraint_id === 'change' ? 'The change you asked for' : constraintKindLabel(constraint.kind)}
                  <span className={`block ${CODE_CLASS}`}>
                    {constraint.kind} · {constraint.constraint_id}
                  </span>
                </p>
                <p>{text(constraint.description)}</p>

                {pin(constraint.constraint_id) && (
                  <p data-testid={`constraint-pins-${constraint.constraint_id}`} className="text-xs">
                    Fixed item: {pin(constraint.constraint_id)}
                  </p>
                )}

                {constraint.slots.length > 0 && (
                  <p data-testid={`constraint-slots-${constraint.constraint_id}`} className="text-xs">
                    When: {slotsText(constraint.slots)}
                  </p>
                )}

                <p className="text-xs">
                  Involves:{' '}
                  {constraint.entity_ids.slice(0, LISTED_ENTITIES).map((id, i) => (
                    <React.Fragment key={id}>
                      {i > 0 && ', '}
                      <span title={id}>{name(id)}</span>
                    </React.Fragment>
                  ))}
                  {constraint.entity_ids.length > LISTED_ENTITIES && ` and ${constraint.entity_ids.length - LISTED_ENTITIES} more`}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Suggested relaxation (absent when the method is search exhaustion) */}
      {suggested_relaxation && (
        <section
          data-testid="suggested-relaxation"
          className="flex flex-col justify-between gap-3 rounded-md border-2 border-emerald-700/50 bg-emerald-50 p-4 dark:bg-emerald-950/40 sm:flex-row sm:items-center"
        >
          <div className="space-y-1">
            <h3 className="flex items-center gap-2 text-lg font-semibold">
              <Lightbulb aria-hidden="true" className="h-5 w-5 text-emerald-800 dark:text-emerald-300" />
              {headings.fix}
            </h3>
            <p className="font-semibold">{text(suggested_relaxation.description)}</p>
            {suggested_relaxation.action_type && suggested_relaxation.verification && (
              <p data-testid="relaxation-action" className="text-xs">
                {relaxationActionLabel(suggested_relaxation.action_type)};{' '}
                {verificationLabel(suggested_relaxation.verification.status)}
                {suggested_relaxation.verification.runtime_ms !== null &&
                  ` (${formatDuration(suggested_relaxation.verification.runtime_ms)})`}{' '}
                <span className={CODE_CLASS}>
                  {suggested_relaxation.action_type}, {suggested_relaxation.verification.status}
                </span>
              </p>
            )}
            {edgeList && suggested_relaxation.action_params && (
              <p data-testid="relaxation-applies-to" className="text-xs">
                Applies to: {relaxationTargets(suggested_relaxation.action_params, name, pin(suggested_relaxation.constraint_id)).join('; ') || 'nothing named'}
              </p>
            )}
            <p data-testid="relaxation-constraint-id" className={CODE_CLASS}>
              Constraint {suggested_relaxation.constraint_id}
            </p>
          </div>

          {onApplyRelaxation && (
            <Button
              size="sm"
              onClick={() => onApplyRelaxation(suggested_relaxation.constraint_id)}
              className="shrink-0 gap-1.5 bg-emerald-800 text-white hover:bg-emerald-900"
            >
              <Lightbulb className="h-4 w-4" />
              <span>{UI.tryThisFix}</span>
            </Button>
          )}
        </section>
      )}

      {/* Deepest partial placement: diagnostic only, never a timetable */}
      {partial_placement && unplaced_session_ids && (
        <details data-testid="partial-placement" className="text-xs">
          <summary className="cursor-pointer font-semibold">
            {partialPlacementText(partial_placement.length, unplaced_session_ids.length)}
          </summary>
          <p className="mt-1">
            Placed:{' '}
            {partial_placement.map((p) => `${name(p.session_id)} (${slotText(p.day, p.period)})`).join(', ') || 'none'}
          </p>
          <p data-testid="unplaced-sessions">{UI.notPlaced}: {unplaced_session_ids.map(name).join(', ')}</p>
        </details>
      )}
    </section>
  );
};
