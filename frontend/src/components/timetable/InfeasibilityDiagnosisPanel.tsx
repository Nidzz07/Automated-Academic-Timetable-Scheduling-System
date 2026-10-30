import React from 'react';
import { InfeasibleSolution, toDiagnosisView } from '@/adapters/solution';
import { EdgeList, Labels, entityName, EXAMPLE_LABELS, pinName, slotText, slotsText } from '@/adapters/timetable';
import { Button } from '@/components/ui/button';
import { formatDuration } from '@/lib/format';
import { constraintKindLabel, readableSolverText, relaxationActionLabel, verificationLabel } from '@/lib/wording';
import { AlertTriangle, Lightbulb, ArrowRight } from 'lucide-react';

type Slot = { day: number; period: number };

/** The ids a relaxation's params name (contracts/solution_v2 params_*), by name; its pin (D51), if any, by unique_label. */
function relaxationTargets(params: Record<string, unknown>, name: (id: string) => string, pin: string | null): string[] {
  const ids = ['session_id', 'faculty_id', 'room_id', 'entity_id'].flatMap((k) =>
    typeof params[k] === 'string' ? [name(params[k] as string)] : []
  );
  const slots = [...((params.slots as Slot[] | undefined) ?? []), ...(params.slot ? [params.slot as Slot] : [])];
  return [...ids, ...(pin ? [`pin ${pin}`] : []), ...(slots.length ? [slotsText(slots)] : [])];
}

interface InfeasibilityDiagnosisPanelProps {
  infeasibleSolution: InfeasibleSolution;
  /** The edge list diagnosed: ids are then shown by name, pins by their unique_label (D41) */
  edgeList?: EdgeList;
  labels?: Labels;
  onApplyRelaxation?: (constraintId: string) => void;
  onSwitchToSolved?: () => void;
}

/**
 * Why no timetable exists: the solver's diagnosis in plain words, each constraint's kind by its
 * meaning with the contract's code beside it. The solver's own sentences are shown as written,
 * with period labels and times put in the UI's form (displayText).
 */
export const InfeasibilityDiagnosisPanel: React.FC<InfeasibilityDiagnosisPanelProps> = ({
  infeasibleSolution,
  edgeList,
  labels = EXAMPLE_LABELS,
  onApplyRelaxation,
  onSwitchToSolved,
}) => {
  const name = (id: string) => (edgeList ? entityName(id, edgeList, labels) : id);
  // the solver's sentences name cohorts and faculty by id: shown by name where the edge list knows them
  const text = (t: string) => readableSolverText(t, edgeList ? (id) => (name(id) === id ? null : name(id)) : undefined);
  // a `pin.<i>` constraint id is pinned_occupancy[i], named by display.json pins[i] (D51)
  const pin = (constraintId: string) => (edgeList ? pinName(constraintId, edgeList, labels) : null);
  const { metadata } = infeasibleSolution;
  const diagnosis = toDiagnosisView(infeasibleSolution);
  const { minimal_conflicting_set, suggested_relaxation, partial_placement, unplaced_session_ids } = diagnosis;
  const method = diagnosis.methodLabel;

  return (
    <section data-testid="infeasibility-panel" className="space-y-4 rounded-lg border-2 border-destructive/60 bg-card p-4 sm:p-6">
      <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
        <div className="flex items-start gap-3">
          <AlertTriangle aria-hidden="true" className="mt-1 h-6 w-6 shrink-0 text-destructive" />
          <div>
            <h2 className="text-xl font-semibold">No timetable is possible</h2>
            <p>{method.text}</p>
            <p className="text-xs">
              Found by: <span data-testid="diagnosis-method">{method.badge}</span>
            </p>
          </div>
        </div>

        {onSwitchToSolved && (
          <Button variant="outline" size="sm" onClick={onSwitchToSolved} className="gap-1">
            <span>View Solved Baseline</span>
            <ArrowRight className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* Solver run statistics */}
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="font-semibold">Method</dt>
          <dd className="truncate" title={metadata.algorithm}>
            {metadata.algorithm}
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Time taken</dt>
          <dd>{formatDuration(metadata.runtime_ms)}</dd>
        </div>
        <div>
          <dt className="font-semibold">Sessions placed before it stopped</dt>
          <dd>
            {metadata.sessions_assigned} / {metadata.sessions_total} sessions placed
          </dd>
        </div>
        <div>
          <dt className="font-semibold">Search backtracks</dt>
          <dd>{metadata.backtracks?.toLocaleString()} backtracks</dd>
        </div>
      </dl>

      {/* Minimal conflicting subset (MUS); empty when the method is search exhaustion */}
      {minimal_conflicting_set.length > 0 && (
        <section className="space-y-2">
          <div>
            <h3 className="text-lg font-semibold">
              Why: these {minimal_conflicting_set.length} rules cannot all hold
            </h3>
            <p className="text-xs">Drop any one of them and a timetable exists.</p>
          </div>
          <ul data-testid="minimal-conflicting-set" className="space-y-2">
            {minimal_conflicting_set.map((constraint) => (
              <li
                key={constraint.constraint_id}
                data-testid={`conflicting-constraint-${constraint.constraint_id}`}
                className="space-y-1 rounded-md border border-border p-3"
              >
                <p data-testid={`constraint-kind-${constraint.kind}`} className="font-semibold">
                  {constraintKindLabel(constraint.kind)}{' '}
                  <span className="font-mono text-xs font-normal">
                    {constraint.kind} · {constraint.constraint_id}
                  </span>
                </p>
                <p>{text(constraint.description)}</p>

                {pin(constraint.constraint_id) && (
                  <p data-testid={`constraint-pins-${constraint.constraint_id}`} className="text-xs">
                    Pinned: {pin(constraint.constraint_id)}
                  </p>
                )}

                {constraint.slots.length > 0 && (
                  <p data-testid={`constraint-slots-${constraint.constraint_id}`} className="text-xs">
                    When: {slotsText(constraint.slots)}
                  </p>
                )}

                <p className="text-xs">
                  Involves:{' '}
                  {constraint.entity_ids.map((id, i) => (
                    <React.Fragment key={id}>
                      {i > 0 && ', '}
                      <span title={id}>{name(id)}</span>
                    </React.Fragment>
                  ))}
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
              Smallest change that would allow it
            </h3>
            <p className="font-semibold">{text(suggested_relaxation.description)}</p>
            {suggested_relaxation.action_type && suggested_relaxation.verification && (
              <p data-testid="relaxation-action" className="text-xs">
                {relaxationActionLabel(suggested_relaxation.action_type)};{' '}
                {verificationLabel(suggested_relaxation.verification.status)}
                {suggested_relaxation.verification.runtime_ms !== null &&
                  ` (${formatDuration(suggested_relaxation.verification.runtime_ms)})`}{' '}
                <span className="font-mono">
                  {suggested_relaxation.action_type}, {suggested_relaxation.verification.status}
                </span>
              </p>
            )}
            {edgeList && suggested_relaxation.action_params && (
              <p data-testid="relaxation-applies-to" className="text-xs">
                Applies to: {relaxationTargets(suggested_relaxation.action_params, name, pin(suggested_relaxation.constraint_id)).join('; ') || 'nothing named'}
              </p>
            )}
            <p data-testid="relaxation-constraint-id" className="font-mono text-xs">
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
              <span>Simulate Relaxation</span>
            </Button>
          )}
        </section>
      )}

      {/* Deepest partial placement: diagnostic only, never a timetable */}
      {partial_placement && unplaced_session_ids && (
        <details data-testid="partial-placement" className="text-xs">
          <summary className="cursor-pointer font-semibold">
            How far the search got (diagnostic only — not a timetable): {partial_placement.length} placed,{' '}
            {unplaced_session_ids.length} unplaced
          </summary>
          <p className="mt-1 font-mono">
            Placed:{' '}
            {partial_placement.map((p) => `${p.session_id} (${slotText(p.day, p.period)})`).join(', ') || 'none'}
          </p>
          <p data-testid="unplaced-sessions" className="font-mono">
            Unplaced: {unplaced_session_ids.join(', ')}
          </p>
        </details>
      )}
    </section>
  );
};
