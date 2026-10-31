import React from 'react';
import { EnrichedSession } from '@/adapters/timetable';
import { Pin, GripVertical, Loader2 } from 'lucide-react';

interface SessionCellProps {
  session: EnrichedSession;
  onSelect?: () => void;
  isDraggable?: boolean;
  isProvisional?: boolean;
  isSelected?: boolean;
  dragAttributes?: Record<string, any>;
  dragListeners?: Record<string, any>;
  dragRef?: (element: HTMLElement | null) => void;
  isDragging?: boolean;
}

export const SessionCell: React.FC<SessionCellProps> = ({
  session,
  onSelect,
  isDraggable = false,
  isProvisional = false,
  isSelected = false,
  dragAttributes,
  dragListeners,
  dragRef,
  isDragging = false,
}) => {
  return (
    <div
      ref={dragRef}
      data-testid={`session-cell-${session.sessionId}`}
      data-session-id={session.sessionId}
      data-draggable={isDraggable ? 'true' : 'false'}
      data-provisional={isProvisional ? 'true' : 'false'}
      data-selected={isSelected ? 'true' : 'false'}
      onClick={onSelect}
      {...(isDraggable ? dragAttributes : {})}
      {...(isDraggable ? dragListeners : {})}
      className={`group relative flex h-full w-full flex-col justify-between rounded-md border border-l-4 p-2.5 ${
        isDraggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'
      } ${isDragging ? 'opacity-40 border-dashed' : ''} ${isSelected ? 'ring-2 ring-primary ring-offset-2' : ''} ${
        isProvisional
          ? 'border-amber-700 bg-amber-50 dark:bg-amber-950/40'
          : session.isPinned
            ? 'border-slate-500 bg-slate-100 dark:bg-slate-900 bg-pinned-pattern'
            : 'border-blue-200 border-l-blue-800 bg-blue-50 hover:border-blue-400 dark:border-blue-900 dark:bg-blue-950/40'
      }`}
    >
      {/* Kind, drag handle, room */}
      <div className="mb-1 flex flex-wrap items-center justify-between gap-x-1">
        <div className="flex items-center gap-1">
          {isDraggable && (
            <span data-testid={`drag-handle-${session.sessionId}`} className="shrink-0 cursor-grab" title="Drag to reschedule">
              <GripVertical className="h-4 w-4" />
            </span>
          )}

          {session.isPinned ? (
            <span className="inline-flex items-center gap-1 font-semibold">
              <Pin aria-hidden="true" className="h-3.5 w-3.5 rotate-45" />
              Fixed Slot
            </span>
          ) : isProvisional ? (
            <span className="inline-flex items-center gap-1 font-semibold">
              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
              Checking…
            </span>
          ) : (
            <span className="font-semibold">Lecture</span>
          )}
        </div>

        <span className="font-semibold">Room {session.subRoomCode ?? session.roomCode}</span>
      </div>

      {/* Subject */}
      <div className="my-1">
        <div className="font-serif text-base font-semibold leading-tight">
          {session.subjectCode} <span className="font-sans text-xs font-normal">{session.subjectName}</span>
        </div>
        <div>{session.cohortLabel}</div>
      </div>

      {/* Faculty and size */}
      <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2 border-t border-dashed border-border pt-1.5">
        <span className="min-w-0" title={session.facultyName}>
          <span className="font-semibold">{session.facultyInitials}</span> {session.facultyName}
        </span>
        <span className="shrink-0">{session.cohortSize} students</span>
      </div>
    </div>
  );
};
