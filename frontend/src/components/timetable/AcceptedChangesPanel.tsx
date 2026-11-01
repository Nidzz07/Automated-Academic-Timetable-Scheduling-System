import React, { useState } from 'react';
import { HttpChronosApiClient, RepairChange } from '@/api/chronosApi';
import { useChangesQuery, useClearChangesMutation } from '@/api/queries';
import { EdgeList, Labels, entityName, facultyText, sessionWithoutTeacher, slotsText } from '@/adapters/timetable';
import { formatTimestamp } from '@/lib/format';
import { UI, clearChangesText } from '@/lib/wording';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';

/** A change in words, by name. A substitution names the session without its teacher, which it changes. */
export function changeText(change: RepairChange, edgeList: EdgeList, labels: Labels): string {
  const room = (id: string) => entityName(id, edgeList, labels);
  switch (change.kind) {
    case 'faculty_unavailable':
      return `${facultyText(labels, change.faculty_id)} unavailable: ${slotsText(change.slots)}`;
    case 'room_unavailable':
      return `${room(change.room_id)} unavailable: ${slotsText(change.slots)}`;
    case 'move_session':
      return `${entityName(change.session_id, edgeList, labels)} moved to ${slotsText([change])}, ${room(change.sub_room_id ?? change.room_id)}`;
    case 'substitute_faculty':
      return `${sessionWithoutTeacher(change.session_id, edgeList, labels)}: taught by ${facultyText(labels, change.faculty_id)}`;
  }
}

interface AcceptedChangesPanelProps {
  client: HttpChronosApiClient;
  instance: string;
  edgeList: EdgeList;
  labels: Labels;
  /** Administrator only (the backend refuses anyone else) */
  canClear: boolean;
  /** The changes were cleared: the official timetable may have changed (D56) */
  onCleared?: () => void;
}

/**
 * The accepted unavailability changes and substitutions every later solve and repair includes
 * (D52), in acceptance order. An administrator can clear them after a confirm step.
 */
export const AcceptedChangesPanel: React.FC<AcceptedChangesPanelProps> = ({ client, instance, edgeList, labels, canClear, onCleared }) => {
  const changes = useChangesQuery(client, instance, true);
  const clear = useClearChangesMutation(client, instance);
  const [confirming, setConfirming] = useState(false);
  const rows = changes.data ?? [];

  return (
    <Card data-testid="accepted-changes">
      <CardHeader className="pb-3">
        <CardTitle>Accepted changes</CardTitle>
        <CardDescription>{UI.acceptedChangesNote}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {changes.error && <p role="alert">Could not load the accepted changes: {changes.error.message}</p>}
        {changes.data && rows.length === 0 && <p data-testid="no-accepted-changes">No accepted changes.</p>}
        {rows.length > 0 && (
          <table className="w-full text-left text-xs">
            <thead>
              <tr>
                <th className="py-1 pr-3">Accepted</th>
                <th className="py-1 pr-3">Change</th>
                <th className="py-1 pr-3">Requested by</th>
                <th className="py-1">Accepted by</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.job_id} data-testid={`accepted-change-${c.job_id}`} className="border-t border-border/60 align-top">
                  <td className="py-1 pr-3 whitespace-nowrap">{formatTimestamp(c.accepted_at)}</td>
                  <td className="py-1 pr-3">{changeText(c.change, edgeList, labels)}</td>
                  <td className="py-1 pr-3">{c.requested_by}</td>
                  <td className="py-1">{c.accepted_by ?? 'not recorded'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {clear.error && <p role="alert">Could not clear the accepted changes: {clear.error.message}</p>}
        {canClear && rows.length > 0 &&
          (confirming ? (
            <div data-testid="confirm-clear" className="space-y-2 rounded-lg border border-destructive/40 p-3">
              <p>{clearChangesText(rows.length)}</p>
              <div className="flex gap-2">
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={clear.isPending}
                  onClick={() => clear.mutate(undefined, { onSuccess: () => onCleared?.(), onSettled: () => setConfirming(false) })}
                  data-testid="confirm-clear-button"
                >
                  Clear all
                </Button>
                <Button variant="outline" size="sm" onClick={() => setConfirming(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => setConfirming(true)} data-testid="clear-changes">
              Clear accepted changes…
            </Button>
          ))}
      </CardContent>
    </Card>
  );
};
