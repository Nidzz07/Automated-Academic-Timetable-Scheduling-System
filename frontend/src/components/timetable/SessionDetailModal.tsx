import React from 'react';
import { EnrichedSession } from '@/adapters/timetable';
import { Button } from '@/components/ui/button';
import { periodLabel } from '@/lib/format';
import { X, Pin } from 'lucide-react';

interface SessionDetailModalProps {
  session: EnrichedSession | null;
  onClose: () => void;
  /** Administrator and coordinator on a backend instance: list who may take the session (S14g) */
  onFindSubstitute?: () => void;
}

export const SessionDetailModal: React.FC<SessionDetailModalProps> = ({
  session,
  onClose,
  onFindSubstitute,
}) => {
  if (!session) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-detail-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div className="relative w-full max-w-lg rounded-lg border border-border bg-card p-6">
        <button onClick={onClose} aria-label="Close details" className="absolute top-4 right-4 rounded-md p-1.5 hover:bg-muted">
          <X className="h-5 w-5" />
        </button>

        <p className="mb-1 pr-8 font-semibold">
          {session.isPinned
            ? 'Pinned, immovable'
            : session.isCombinedDivision
              ? 'Combined division lecture'
              : session.sessionType === 'lab'
                ? 'Lab (practical)'
                : 'Lecture (theory)'}{' '}
          <span className="font-mono text-xs font-normal">{session.sessionId}</span>
        </p>

        <h3 id="session-detail-title" className="text-xl font-semibold">
          {session.subjectCode} — {session.subjectName}
        </h3>

        <dl className="my-4 grid grid-cols-2 gap-x-6 gap-y-3">
          <div>
            <dt className="text-xs font-semibold">Teacher</dt>
            <dd className="font-semibold">{session.facultyName}</dd>
            <dd className="text-xs">Initials: {session.facultyInitials}</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Room</dt>
            <dd className="font-semibold">Room {session.subRoomCode ?? session.roomCode}</dd>
            <dd className="text-xs">
              {session.subRoomCode ? `Part of room ${session.roomCode}` : 'Full room'}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Class</dt>
            <dd className="font-semibold">{session.cohortLabel}</dd>
            <dd className="text-xs">{session.cohortSize} students enrolled</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Length</dt>
            <dd className="font-semibold">
              {session.durationPeriods} teaching period{session.durationPeriods > 1 ? 's' : ''}
            </dd>
            <dd className="text-xs">Starts at {periodLabel(session.wallClockPeriod)}</dd>
          </div>
        </dl>

        {session.isPinned && (
          <p className="mb-4 flex items-center gap-2 rounded-md border border-slate-400 bg-slate-100 p-2.5 text-xs dark:bg-slate-900">
            <Pin aria-hidden="true" className="h-4 w-4 shrink-0" />
            <span>
              <strong>Cannot be moved:</strong> {session.pinnedReason}
            </span>
          </p>
        )}

        {/* The placement as the solution contract stores it */}
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold">Placement record (as stored)</summary>
          <pre className="mt-1 overflow-x-auto rounded border border-border bg-muted p-2 font-mono">
            {JSON.stringify(
              {
                session_id: session.sessionId,
                day: session.day,
                period: session.wallClockPeriod,
                room_id: session.roomCode,
                sub_room_id: session.subRoomCode,
              },
              null,
              2
            )}
          </pre>
        </details>

        <div className="mt-4 flex justify-end gap-2">
          {onFindSubstitute && (
            <Button size="sm" onClick={onFindSubstitute} data-testid="find-substitute">
              Find substitute
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
};
