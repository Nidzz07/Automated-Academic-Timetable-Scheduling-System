import React, { useMemo, useState } from 'react';
import { AnomalyReport, NEEDS_HUMAN } from '@/adapters/realInstance';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

/**
 * The ingestion anomaly report (anomalies.json; ROADMAP Phase 2, Track C): every anomaly as
 * reported, never fixed here, with the decision that resolves it or "needs human".
 */
export const AnomalyReportPanel: React.FC<{ report: AnomalyReport }> = ({ report }) => {
  const [category, setCategory] = useState('all');
  const [needsHumanOnly, setNeedsHumanOnly] = useState(false);

  const categories = useMemo(
    () => [...new Set(report.anomalies.map((a) => a.category))].sort(),
    [report]
  );
  const rows = report.anomalies.filter(
    (a) =>
      (category === 'all' || a.category === category) &&
      (!needsHumanOnly || a.resolution === NEEDS_HUMAN)
  );

  return (
    <Card data-testid="anomaly-report">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Ingestion anomaly report</CardTitle>
        <CardDescription>
          {report.counts.total} anomalies, {report.counts.needs_human} need a human decision. Reported
          as found in the source files; none is fixed silently.
        </CardDescription>
        <div className="flex flex-wrap items-center gap-3 pt-2 text-xs">
          <select
            aria-label="Anomaly category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1"
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={needsHumanOnly}
              onChange={(e) => setNeedsHumanOnly(e.target.checked)}
            />
            Needs human only
          </label>
          <span data-testid="anomaly-count" className="text-muted-foreground">
            {rows.length} of {report.counts.total} shown
          </span>
        </div>
      </CardHeader>
      <CardContent className="max-h-[480px] overflow-auto pt-0">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border">
              <th className="p-2">Category</th>
              <th className="p-2">Source</th>
              <th className="p-2">Location</th>
              <th className="p-2">Message</th>
              <th className="p-2">Resolved by</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((a, i) => (
              <tr key={i} data-testid="anomaly-row" className="border-b border-border/40 align-top">
                <td className="p-2 font-mono">{a.category}</td>
                <td className="p-2">{a.source_file}</td>
                <td className="p-2">{a.location}</td>
                <td className="p-2">{a.message}</td>
                <td className="p-2">
                  {a.resolution === NEEDS_HUMAN ? (
                    <Badge variant="warning">Needs human</Badge>
                  ) : (
                    <Badge variant="outline" className="font-mono">
                      {a.resolution}
                    </Badge>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
};
