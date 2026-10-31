import React from 'react';
import { QualityView } from '@/adapters/solution';
import { PrintedBaseline } from '@/adapters/realInstance';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatScore } from '@/lib/format';
import { UI, comparisonSentence, ruleWording } from '@/lib/wording';

interface GeneratedVsPrintedCardProps {
  generated: QualityView;
  /** Hard rules the generated timetable breaks: hardRuleViolations, the check the printed count comes from */
  generatedHard: number;
  printed: PrintedBaseline;
}

const score = (s: number | null) => (s === null ? '—' : formatScore(s));
const penalty = (q: QualityView, ruleId: string) => {
  const rule = q.rules.find((r) => r.rule_id === ruleId);
  return rule?.status === 'evaluated' ? formatScore(-rule.penalty) : '—';
};

/**
 * The generated timetable beside the printed one: hard-rule violations first, then score and each
 * rule's penalty. Every number is read from the data (the solution, the edge list and
 * real_baseline.report.json), none is changed (D34).
 */
export const GeneratedVsPrintedCard: React.FC<GeneratedVsPrintedCardProps> = ({ generated, generatedHard, printed }) => {
  const ruleIds = [...new Set([...generated.rules, ...printed.quality.rules].map((r) => r.rule_id))];
  const printedHard = printed.violations.length;
  const rows: Array<[string, string, string, string]> = [
    ['hard', 'Hard-rule violations (rules that must hold)', String(generatedHard), String(printedHard)],
    ['score', 'Quality points (soft rules)', score(generated.score), score(printed.quality.score)],
    ...ruleIds.map((id): [string, string, string, string] => [
      id,
      `${ruleWording(id).title} (${id}), points lost`,
      penalty(generated, id),
      penalty(printed.quality, id),
    ]),
  ];
  return (
    <Card data-testid="generated-vs-printed">
      <CardHeader className="pb-3">
        <CardTitle>Generated and printed timetables compared</CardTitle>
        <CardDescription>{UI.comparisonNote}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2 pt-0">
        <p data-testid="compare-sentence" className="font-semibold">
          {comparisonSentence(generatedHard, printedHard, generated.score, printed.quality.score)}
        </p>
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="py-1 font-semibold">Measure</th>
              <th className="py-1 text-right font-semibold">Generated</th>
              <th className="py-1 text-right font-semibold">Printed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, label, gen, prt]) => (
              <tr key={key} data-testid={`compare-${key}`} className={`border-t border-border/50 ${key === 'hard' ? 'font-semibold' : ''}`}>
                <td className="py-1">{label}</td>
                <td className="py-1 text-right tabular-nums">{gen}</td>
                <td className="py-1 text-right tabular-nums">{prt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
};
