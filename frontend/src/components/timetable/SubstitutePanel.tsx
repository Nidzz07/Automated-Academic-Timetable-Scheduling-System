import React from 'react';
import { ApiError, HttpChronosApiClient } from '@/api/chronosApi';
import { useSubstitutesQuery } from '@/api/queries';
import { EdgeList, Labels, entityName, facultyText } from '@/adapters/timetable';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { UserRoundCog, X } from 'lucide-react';

interface SubstitutePanelProps {
  client: HttpChronosApiClient;
  instance: string;
  sessionId: string;
  edgeList: EdgeList;
  labels: Labels;
  /** While another repair runs or waits to be accepted or discarded */
  disabled: boolean;
  /** Propose the substitution as a repair */
  onPick: (facultyId: string) => void;
  onClose: () => void;
}

const signed = (d: number) => `${d >= 0 ? '+' : ''}${d.toFixed(1)}`;

/**
 * Who may take a session where it is (S14g): the faculty SPIT's faculty–subject sheets list for
 * it (D53) who are free there, best score change first, and why the others were left out.
 * Chronos suggests; the coordinator decides, and the pick goes through the usual repair flow.
 */
export const SubstitutePanel: React.FC<SubstitutePanelProps> = ({
  client,
  instance,
  sessionId,
  edgeList,
  labels,
  disabled,
  onPick,
  onClose,
}) => {
  const subs = useSubstitutesQuery(client, instance, sessionId);
  const data = subs.data;
  const others = (ids: string[]) =>
    [...new Set(ids.filter((id) => id !== sessionId))].map((id) => entityName(id, edgeList, labels));

  return (
    <Card data-testid="substitute-panel">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle>Find a substitute</CardTitle>
            <CardDescription>
              {entityName(sessionId, edgeList, labels)}. Qualified teachers from SPIT's faculty–subject sheets who are
              free at this slot. Picking one proposes a repair to accept or discard.
            </CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close substitutes">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {subs.isPending && <p role="status">Finding substitutes…</p>}
        {subs.error && (
          <p role="alert">
            {subs.error instanceof ApiError && subs.error.status === 409
              ? 'There is no solved official timetable to substitute in.'
              : `Could not find substitutes: ${subs.error.message}`}
          </p>
        )}
        {data && (
          <>
            {data.candidates.length === 0 ? (
              <p data-testid="no-substitutes">Nobody qualified is free at this slot.</p>
            ) : (
              <ul className="space-y-1">
                {data.candidates.map((c) => (
                  <li key={c.faculty_id} className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1.5"
                      disabled={disabled}
                      onClick={() => onPick(c.faculty_id)}
                      data-testid={`substitute-${c.faculty_id}`}
                    >
                      <UserRoundCog className="h-4 w-4" />
                      {facultyText(labels, c.faculty_id)}
                    </Button>
                    <span data-testid={`substitute-score-${c.faculty_id}`}>quality score {signed(c.score_change)} if picked</span>
                  </li>
                ))}
              </ul>
            )}
            {data.left_out.length > 0 && (
              <div className="space-y-1">
                <p className="font-semibold">Not suggested</p>
                <ul className="space-y-1">
                  {data.left_out.map((o) => {
                    const clashes = others(o.violations.flatMap((v) => (v.kind === 'FACULTY_CLASH' ? v.session_ids : [])));
                    return (
                      <li key={o.faculty_id} data-testid={`left-out-${o.faculty_id}`}>
                        {facultyText(labels, o.faculty_id)}: {o.reasons.join(', ')}
                        {clashes.length > 0 && ` (teaches ${clashes.join('; ')} then)`}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
};
