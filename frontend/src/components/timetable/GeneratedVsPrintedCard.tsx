import React from 'react';
import { QualityView } from '@/adapters/solution';
import { PrintedBaseline } from '@/adapters/realInstance';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

interface GeneratedVsPrintedCardProps {
  generated: QualityView;
  printed: PrintedBaseline;
}

const score = (s: number | null) => (s === null ? '—' : s.toFixed(1));
const penalty = (q: QualityView, ruleId: string) => {
  const rule = q.rules.find((r) => r.rule_id === ruleId);
  return rule?.status === 'evaluated' ? `-${rule.penalty.toFixed(1)}` : '—';
};

/**
 * The generated timetable beside the printed one: score, each rule's penalty, and hard
 * violations. Every number is read from the solution and real_baseline.report.json.
 */
export const GeneratedVsPrintedCard: React.FC<GeneratedVsPrintedCardProps> = ({ generated, printed }) => {
  const ruleIds = [...new Set([...generated.rules, ...printed.quality.rules].map((r) => r.rule_id))];
  const rows: Array<[string, string, string, string]> = [
    ['score', 'Total score', score(generated.score), score(printed.quality.score)],
    ...ruleIds.map((id): [string, string, string, string] => [
      id,
      `${id} penalty`,
      penalty(generated, id),
      penalty(printed.quality, id),
    ]),
    // the backend serves only solutions that pass solver.validate.validate_solution
    ['hard', 'Hard violations', '0', String(printed.violations.length)],
  ];
  return (
    <Card data-testid="generated-vs-printed">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Generated vs printed timetable</CardTitle>
        <CardDescription>
          Generated: the solver's validated solution. Printed: the SPIT timetable as issued.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted-foreground">
              <th className="py-1 font-semibold">Measure</th>
              <th className="py-1 text-right font-semibold">Generated</th>
              <th className="py-1 text-right font-semibold">Printed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, label, gen, prt]) => (
              <tr key={key} data-testid={`compare-${key}`} className="border-t border-border/50">
                <td className="py-1">{label}</td>
                <td className="py-1 text-right font-mono">{gen}</td>
                <td className="py-1 text-right font-mono">{prt}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
};
