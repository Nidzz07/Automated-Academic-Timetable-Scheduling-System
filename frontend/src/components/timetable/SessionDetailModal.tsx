import React, { useEffect, useRef } from 'react';
import { EnrichedSession, sessionTeacher } from '@/adapters/timetable';
import { Button } from '@/components/ui/button';
import { periodLabel } from '@/lib/format';
import { FIXED_SESSION_NOTE, sessionKindText, sessionTitle } from '@/lib/wording';
import { X, Pin } from 'lucide-react';

interface SessionDetailModalProps {
  session: EnrichedSession | null;
  onClose: () => void;
  /** Administrator and coordinator on a backend instance: list who may take the session (S14g) */
  onFindSubstitute?: () => void;
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The window itself: mounted only while open, so focus moves in on open and goes back to what had
 * it (the session's card) on close. Tab stays inside; Escape closes.
 */
const SessionDetailDialog: React.FC<{ session: EnrichedSession } & Omit<SessionDetailModalProps, 'session'>> = ({
  session,
  onClose,
  onFindSubstitute,
}) => {
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus();
    return () => before?.focus({ preventScroll: true });
  }, []);

  // on the document, so Escape closes wherever a click left the focus
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !dialog.current) return;
      const inside = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (inside.length === 0) return;
      const first = inside[0];
      const last = inside[inside.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !dialog.current.contains(active))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || !dialog.current.contains(active))) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="session-detail-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
    >
      <div ref={dialog} className="relative w-full max-w-lg rounded-lg border border-border bg-card p-6">
        <button
          ref={closeButton}
          onClick={onClose}
          aria-label="Close details"
          className="absolute top-4 right-4 rounded-md p-1.5 hover:bg-muted"
        >
          <X className="h-5 w-5" />
        </button>

        <p className="mb-1 pr-8 font-semibold">
          {sessionKindText(session)}, {session.subjectCode}
        </p>

        <h2 id="session-detail-title" className="text-xl font-semibold">
          {sessionTitle(session)}
        </h2>

        <dl className="my-4 grid grid-cols-2 gap-x-6 gap-y-3">
          <div>
            <dt className="text-xs font-semibold">Teacher</dt>
            <dd className="font-semibold">{sessionTeacher(session)}</dd>
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
              <strong>Cannot be moved:</strong> {FIXED_SESSION_NOTE}
            </span>
          </p>
        )}

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

export const SessionDetailModal: React.FC<SessionDetailModalProps> = ({ session, ...props }) =>
  session ? <SessionDetailDialog session={session} {...props} /> : null;
