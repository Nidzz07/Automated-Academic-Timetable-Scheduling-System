import React, { useState } from 'react';
import { HttpChronosApiClient } from '@/api/chronosApi';
import { useAuditQuery } from '@/api/queries';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

// GET /audit accepts 1..1000 (backend/app/routers.py); 100 is its default
const LIMITS = [25, 100, 500, 1000];

/** The audit log, newest first as the backend returns it (administrator only; S13b). */
export const AuditLog: React.FC<{ client: HttpChronosApiClient }> = ({ client }) => {
  const [limit, setLimit] = useState(100);
  const audit = useAuditQuery(client, limit);

  return (
    <Card data-testid="audit-log">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Audit log</CardTitle>
        <CardDescription>Logins and solves recorded by the backend, newest first.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0 text-xs">
        <label className="flex items-center gap-1.5 font-semibold text-muted-foreground">
          Show
          <select
            aria-label="Audit entries to show"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="rounded-md border border-border bg-transparent px-2 py-1 font-medium text-foreground"
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
          <div className="max-h-96 overflow-auto">
            <table className="w-full text-left">
              <thead className="text-muted-foreground">
                <tr>
                  <th className="py-1 pr-3">Time</th>
                  <th className="py-1 pr-3">Actor</th>
                  <th className="py-1 pr-3">Action</th>
                  <th className="py-1">Detail</th>
                </tr>
              </thead>
              <tbody>
                {audit.data.map((entry) => (
                  <tr key={entry.id} data-testid="audit-row" className="border-t border-border/60 align-top">
                    <td className="py-1 pr-3 font-mono">{new Date(entry.timestamp).toLocaleString()}</td>
                    <td className="py-1 pr-3">{entry.actor}</td>
                    <td className="py-1 pr-3">{entry.action}</td>
                    <td className="py-1 font-mono break-all">{entry.detail ? JSON.stringify(entry.detail) : ''}</td>
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
