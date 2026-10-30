import React from 'react';
import { QualityView, SolutionMetadata } from '@/adapters/solution';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { formatDuration } from '@/lib/format';
import { readableSolverText, ruleResult, ruleWording } from '@/lib/wording';

/**
 * The solver's quality flags (S-GAP, S-B2B, S-LOAD16, FAC_LOAD_IMBALANCE; ROADMAP D34), each in
 * plain words with what was found and what it cost. Every number is the solver's; nothing is
 * computed here.
 */
interface QualityScoreCardProps {
  quality: QualityView;
  /** Solver run statistics; absent for a timetable the solver did not make (the printed one) */
  metadata?: SolutionMetadata;
  title?: string;
  /** A faculty or cohort id the solver's explanation names, by name; null keeps the id */
  nameOf?: (id: string) => string | null;
}

export const QualityScoreCard: React.FC<QualityScoreCardProps> = ({
  quality,
  metadata,
  title = 'Timetable quality',
  nameOf,
}) => {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>{title}</CardTitle>
            <CardDescription>
              A timetable starts at 100 points; each preference it misses takes points off. Computed by the
              solver{quality.rulesVersion !== null && ` (rules version ${quality.rulesVersion})`}.
            </CardDescription>
          </div>

          <div className="text-right">
            {quality.score === null ? (
              <p data-testid="quality-score-unavailable" className="font-semibold">
                Score not available until rules are evaluated
              </p>
            ) : (
              <p>
                Score{' '}
                <span data-testid="quality-score" className="font-serif text-2xl font-bold">
                  {quality.score}
                </span>
              </p>
            )}
            {quality.score !== null && quality.notEvaluatedRuleIds.length > 0 && (
              <p data-testid="quality-partial" className="text-xs font-semibold text-amber-900 dark:text-amber-200">
                Partial: {quality.notEvaluatedRuleIds.join(', ')} not evaluated
              </p>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 pt-0">
        {/* Run statistics */}
        {metadata && (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-4">
            <div>
              <dt className="font-semibold">Method</dt>
              <dd className="truncate" title={metadata.algorithm}>
                {metadata.algorithm}
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Time to solve</dt>
              <dd>{formatDuration(metadata.runtime_ms)}</dd>
            </div>
            <div>
              <dt className="font-semibold">Sessions placed</dt>
              <dd>
                {metadata.sessions_assigned} / {metadata.sessions_total}
              </dd>
            </div>
            <div>
              <dt className="font-semibold">Time slots used, search backtracks</dt>
              <dd>
                {metadata.slots_used ?? 'N/A'} slots, {metadata.backtracks ?? 0} backtracks
              </dd>
            </div>
          </dl>
        )}

        <section>
          <h4 className="mb-1 text-lg font-semibold">Where points were lost</h4>
          <ul className="divide-y divide-border border-y border-border">
            {quality.rules.map((item) => {
              const words = ruleWording(item.rule_id);
              return (
                <li key={item.rule_id} data-testid={`quality-rule-${item.rule_id}`} className="space-y-1 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-base font-semibold">{words.title}</span>
                    <span className="font-mono text-xs">{item.rule_id}</span>
                  </div>
                  <p>{words.meaning}</p>
                  <p
                    data-testid={item.status === 'evaluated' ? 'rule-penalty' : 'rule-not-evaluated'}
                    className="font-semibold"
                  >
                    {ruleResult(item)}
                  </p>
                  {/* The solver names the affected faculty, divisions and slots here */}
                  {item.status === 'evaluated' && (
                    <details className="text-xs">
                      <summary className="cursor-pointer font-semibold text-primary">Show where</summary>
                      <p className="mt-1">{readableSolverText(item.explanation, nameOf)}</p>
                    </details>
                  )}
                </li>
              );
            })}
          </ul>
        </section>
      </CardContent>
    </Card>
  );
};
