import React, { useMemo, useState } from 'react';
import { AnomalyReport, NEEDS_HUMAN } from '@/adapters/realInstance';
import { Display, EdgeList, Labels, entityName, facultyText, labelsFor } from '@/adapters/timetable';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { displayText } from '@/lib/format';
import { anomalyCategoryLabel } from '@/lib/wording';

type Anomaly = AnomalyReport['anomalies'][number];

/** One category's rows, with the count the report gives for it (undefined when it gives none). */
interface Group {
  category: string;
  rows: Anomaly[];
  reported: number | undefined;
}

/** The report's rows by category, in report order; a category counted but never listed is kept. */
function groupsOf(report: AnomalyReport): Group[] {
  const byCategory = report.counts.by_category;
  const rows = new Map<string, Anomaly[]>();
  report.anomalies.forEach((a) => rows.set(a.category, [...(rows.get(a.category) ?? []), a]));
  Object.keys(byCategory ?? {}).forEach((c) => rows.has(c) || rows.set(c, []));
  return [...rows].map(([category, list]) => ({ category, rows: list, reported: byCategory?.[category] }));
}

/**
 * "Name · id" for each display.json id (faculty, cohort, room or sub-room) or edge-list session that
 * the text names, in order of appearance. The text itself is left as the report gives it.
 */
function namedIds(text: string, display: Display, edgeList: EdgeList | undefined, labels: Labels): string[] {
  const name = (id: string): string | null => {
    if (display.faculty[id]) return facultyText(labels, id);
    if (display.cohorts[id]) return labels.cohort(id);
    if (display.rooms[id]) return `Room ${display.rooms[id]}`;
    if (edgeList?.sessions.some((s) => s.id === id)) return entityName(id, edgeList, labels);
    return null;
  };
  const ids = [...new Set((text.match(/[A-Za-z0-9_.-]+/g) ?? []).map((t) => t.replace(/[.-]+$/, '')))];
  return ids.flatMap((id) => {
    const n = name(id);
    return n ? [`${n} · ${id}`] : [];
  });
}

/** Where a count the report states differs from the rows it lists: both shown, neither adjusted. */
const Mismatch: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span data-testid="anomaly-count-mismatch" className="text-destructive">
    {children}
  </span>
);

/**
 * The ingestion anomaly report (anomalies.json; ROADMAP Phase 2, Track C; S11c): every anomaly as
 * reported, never fixed here, grouped by category with the report's own counts, and the decision
 * that resolves it or "needs human", as the report spells it (CONTEXT §3.5). Ids the report names
 * are shown with their display.json names beside them. Each category is shown in plain words with its
 * code beside it; location and message are shown as reported, period labels and times put in the
 * UI's form for display only (displayText). The report itself is never changed.
 */
export const AnomalyReportPanel: React.FC<{
  /** null when the instance has no report (a 404, or the contract examples) */
  report: AnomalyReport | null;
  /** D41 display sidecar, for names; without it ids stand alone */
  display?: Display | null;
  /** The edge list as served, for session names */
  edgeList?: EdgeList;
}> = ({ report, display, edgeList }) => {
  const [category, setCategory] = useState('all');
  const [needsHumanOnly, setNeedsHumanOnly] = useState(false);

  const groups = useMemo(() => (report ? groupsOf(report) : []), [report]);
  const categories = useMemo(() => groups.map((g) => g.category).sort(), [groups]);
  const labels = useMemo(() => (display ? labelsFor(display) : null), [display]);
  const names = (a: Anomaly) =>
    display && labels ? namedIds(`${a.location} ${a.message}`, display, edgeList, labels) : [];

  const header = (description: React.ReactNode) => (
    <CardHeader className="pb-3">
      <CardTitle>Problems found in the source files</CardTitle>
      <CardDescription data-testid="anomaly-report-status">{description}</CardDescription>
    </CardHeader>
  );

  if (!report) {
    return <Card data-testid="anomaly-report">{header('No anomaly report for this instance.')}</Card>;
  }

  const listedHuman = report.anomalies.filter((a) => a.resolution === NEEDS_HUMAN).length;
  const totalsDiffer = (
    <>
      {report.counts.total !== report.anomalies.length && (
        <Mismatch>
          {' '}
          The report counts {report.counts.total} in total but lists {report.anomalies.length}; they
          differ and neither is adjusted.
        </Mismatch>
      )}
      {report.counts.needs_human !== listedHuman && (
        <Mismatch>
          {' '}
          The report counts {report.counts.needs_human} as needing a human but lists {listedHuman}; they
          differ and neither is adjusted.
        </Mismatch>
      )}
    </>
  );

  if (report.anomalies.length === 0) {
    return (
      <Card data-testid="anomaly-report">
        {header(
          <>
            The report lists no anomalies.
            {totalsDiffer}
          </>
        )}
      </Card>
    );
  }

  const shownIn = (g: Group) =>
    g.rows.filter((a) => !needsHumanOnly || a.resolution === NEEDS_HUMAN);
  const visible = groups.filter(
    (g) =>
      (category === 'all' || g.category === category) &&
      (shownIn(g).length > 0 || (!needsHumanOnly && g.rows.length === 0))
  );
  const shownCount = visible.reduce((n, g) => n + shownIn(g).length, 0);

  return (
    <Card data-testid="anomaly-report">
      <CardHeader className="pb-3">
        <CardTitle>Problems found in the source files</CardTitle>
        <CardDescription>
          {report.counts.total} anomalies in {groups.length} categories, {report.counts.needs_human} need
          a human decision. Reported as found in the source files; none is fixed silently.
          {totalsDiffer}
        </CardDescription>
        <div className="flex flex-wrap items-center gap-3 pt-2">
          <select
            aria-label="Anomaly category"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-md border border-input bg-background px-2 py-1"
          >
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {anomalyCategoryLabel(c)} ({c})
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
          <span data-testid="anomaly-count">
            {shownCount} of {report.counts.total} shown
          </span>
        </div>
      </CardHeader>
      <CardContent className="max-h-[480px] overflow-auto pt-0">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-card">
            <tr className="border-b border-border">
              <th className="p-2">Kind of problem</th>
              <th className="p-2">Source</th>
              <th className="p-2">Location</th>
              <th className="p-2">What was found</th>
              <th className="p-2">Resolved by</th>
            </tr>
          </thead>
          {visible.map((g) => {
            const rows = shownIn(g);
            return (
              <tbody key={g.category} data-testid="anomaly-group" data-category={g.category}>
                <tr className="border-b border-border bg-muted">
                  <th colSpan={5} className="p-2 font-normal">
                    <span className="font-semibold">{anomalyCategoryLabel(g.category)}</span>{' '}
                    <span className="font-mono">{g.category}</span>,{' '}
                    <span data-testid="anomaly-group-count" className="font-semibold">
                      {g.reported ?? g.rows.length}
                    </span>
                    {rows.length !== g.rows.length && <span> · {rows.length} shown</span>}
                    {g.reported === undefined ? (
                      <Mismatch>
                        {' '}
                        The report gives no count for this category; it lists {g.rows.length}.
                      </Mismatch>
                    ) : (
                      g.reported !== g.rows.length && (
                        <Mismatch>
                          {' '}
                          The report counts {g.reported} but lists {g.rows.length}; they differ and
                          neither is adjusted.
                        </Mismatch>
                      )
                    )}
                  </th>
                </tr>
                {rows.map((a, i) => (
                  <tr key={i} data-testid="anomaly-row" className="border-b border-border/40 align-top">
                    <td className="p-2">
                      {anomalyCategoryLabel(a.category)}
                      <div className="font-mono">{a.category}</div>
                    </td>
                    <td className="p-2 break-words">{a.source_file}</td>
                    <td className="p-2">{displayText(a.location)}</td>
                    <td className="p-2">
                      {displayText(a.message)}
                      {names(a).map((n) => (
                        <div key={n} data-testid="anomaly-name">
                          {n}
                        </div>
                      ))}
                    </td>
                    <td className="p-2">
                      <Badge
                        variant={a.resolution === NEEDS_HUMAN ? 'warning' : 'outline'}
                      >
                        {a.resolution}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </CardContent>
    </Card>
  );
};
