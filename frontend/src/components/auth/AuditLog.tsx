import React, { useState } from 'react';
import { AuthSession, HttpChronosApiClient } from '@/api/chronosApi';
import { useAuditQuery } from '@/api/queries';
import { EdgeList, Labels } from '@/adapters/timetable';
import { ROLE_CAPABILITIES } from '@/types/roles';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatTimestamp } from '@/lib/format';
import { auditSentence, changePhrase } from '@/lib/wording';

// GET /audit accepts 1..1000 (backend/app/routers.py); 100 is its default
const LIMITS = [25, 100, 500, 1000];

interface AuditLogProps {
  client: HttpChronosApiClient;
  /** For names in the sentences: the edge list and labels on screen */
  edgeList: EdgeList;
  labels: Labels;
  /** Who is signed in: their own rows name their role (the backend logs only the username) */
  session?: AuthSession | null;
}

/** The audit log, newest first as the backend returns it, one sentence per row (administrator only; S13b). */
export const AuditLog: React.FC<AuditLogProps> = ({ client, edgeList, labels, session }) => {
  const [limit, setLimit] = useState(100);
  const audit = useAuditQuery(client, limit);
  const rows = audit.data ?? [];

  return (
    <Card data-testid="audit-log">
      <CardHeader className="pb-3">
        <CardTitle>Audit log</CardTitle>
        <CardDescription>Sign-ins, solves and repairs recorded by the backend, newest first.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <label className="flex items-center gap-1.5 font-semibold">
          Show
          <select
            aria-label="Audit entries to show"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-md border border-input bg-transparent px-2 py-1 font-medium"
          >
            {LIMITS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          entries
        </label>
        {audit.error && <p role="alert">Could not load the audit log: {audit.error.message}</p>}
        {audit.data && (
          <div className="max-h-[32rem] overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-card">
                <tr className="border-b border-border">
                  <th className="py-2 pr-4">When</th>
                  <th className="py-2">What happened</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((entry) => (
                  <tr key={entry.id} data-testid="audit-row" className="border-t border-border align-top">
                    <td className="whitespace-nowrap py-2 pr-4">{formatTimestamp(entry.timestamp)}</td>
                    <td className="py-2">
                      <p data-testid="audit-sentence" className="text-sm">
                        {auditSentence(
                          entry,
                          rows,
                          (change) => changePhrase(change, edgeList, labels),
                          session && entry.actor === session.username ? ROLE_CAPABILITIES[session.role].title : null
                        )}
                      </p>
                      <details className="text-[11px] text-muted-foreground">
                        <summary className="cursor-pointer">
                          Details: <span data-testid="audit-code" className="font-mono">{entry.action}</span>
                        </summary>
                        {entry.detail && (
                          <pre className="mt-1 whitespace-pre-wrap break-all font-mono">{JSON.stringify(entry.detail)}</pre>
                        )}
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
