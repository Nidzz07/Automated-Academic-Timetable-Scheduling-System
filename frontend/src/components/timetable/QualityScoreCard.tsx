import React, { useState } from 'react';
import { QualityRule, QualityView, SolutionMetadata } from '@/adapters/solution';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { formatDuration, formatScore } from '@/lib/format';
import {
  LISTED_FINDINGS,
  SHOW_FEWER,
  UI,
  backtracksText,
  explanationItems,
  loadLimitHours,
  methodText,
  overLimitItem,
  partialRulesText,
  readableItem,
  readableSolverText,
  ruleResult,
  ruleWording,
  showAllText,
  slotsUsedText,
} from '@/lib/wording';
import { OverLimitWarning } from './OverLimitWarning';

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

/**
 * What a rule found, one finding per line: the first LISTED_FINDINGS, then all of them on request.
 * A teacher above the weekly limit is in red with the over-limit wording (D11).
 */
const RuleFindings: React.FC<{
  rule: Extract<QualityRule, { status: 'evaluated' }>;
  nameOf?: (id: string) => string | null;
}> = ({ rule, nameOf }) => {
  const [showAll, setShowAll] = useState(false);
  const items = explanationItems(rule.explanation);
  // a sentence that lists nothing ("No faculty member teaches more than 16 h a week.")
  if (items.length === 1 && items[0] === rule.explanation) {
    return <p className="mt-1">{readableSolverText(rule.explanation, nameOf)}</p>;
  }
  const limit = rule.rule_id === 'S-LOAD16' ? loadLimitHours(rule) : null;
  const shown = showAll ? items : items.slice(0, LISTED_FINDINGS);
  return (
    <div className="mt-1 space-y-1">
      <ul data-testid={`rule-findings-${rule.rule_id}`} className="list-disc space-y-0.5 pl-5">
        {shown.map((item) => {
          const over = limit === null ? null : overLimitItem(item);
          return (
            <li key={item} data-testid="rule-finding">
              {over ? (
                <span className="inline-flex flex-wrap items-center gap-x-1.5 font-semibold text-destructive dark:text-red-300">
                  <span>{nameOf?.(over.who) ?? over.who}:</span>{' '}
                  <OverLimitWarning hours={over.hours} limit={limit} />
                </span>
              ) : (
                readableItem(item, nameOf)
              )}
            </li>
          );
        })}
      </ul>
      {items.length > LISTED_FINDINGS && (
        <button
          type="button"
          onClick={() => setShowAll((all) => !all)}
          aria-expanded={showAll}
          data-testid={`rule-findings-toggle-${rule.rule_id}`}
          className="font-semibold text-primary underline-offset-2 hover:underline"
        >
          {showAll ? SHOW_FEWER : showAllText(items.length)}
        </button>
      )}
    </div>
  );
};

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
                  {formatScore(quality.score)}
                </span>
              </p>
            )}
            {quality.score !== null && quality.notEvaluatedRuleIds.length > 0 && (
              <p data-testid="quality-partial" className="text-xs font-semibold text-amber-900 dark:text-amber-200">
                {partialRulesText(quality.notEvaluatedRuleIds)}
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
              <dt className="font-semibold">{UI.howMade}</dt>
              <dd data-testid="quality-method">{methodText(metadata.algorithm)}</dd>
              <dd data-testid="quality-method-code" className="break-all font-mono text-[11px] text-muted-foreground">
                {metadata.algorithm}
              </dd>
            </div>
            <div>
              <dt className="font-semibold">{UI.timeTaken}</dt>
              <dd>{formatDuration(metadata.runtime_ms)}</dd>
            </div>
            <div>
              <dt className="font-semibold">Sessions placed</dt>
              <dd>
                {metadata.sessions_assigned} / {metadata.sessions_total}
              </dd>
            </div>
            <div>
              <dt className="font-semibold">{UI.timeSlotsUsed}</dt>
              <dd>{slotsUsedText(metadata.slots_used)}</dd>
              <dd className="text-muted-foreground">{backtracksText(metadata.backtracks)} on the way</dd>
            </div>
          </dl>
        )}

        <section>
          <h3 className="mb-1 text-lg font-semibold">Where points were lost</h3>
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
                      <RuleFindings rule={item} nameOf={nameOf} />
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
