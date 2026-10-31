import React from 'react';
import { EnrichedSession, sessionTeacher } from '@/adapters/timetable';
import { UI } from '@/lib/wording';
import { CARD_FOCUS, cardProps } from './cardKeyboard';
import { Users, GripVertical, Loader2 } from 'lucide-react';

interface CombinedLectureBlockProps {
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

export const CombinedLectureBlock: React.FC<CombinedLectureBlockProps> = ({
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
      data-testid="combined-division-lecture"
      data-session-id={session.sessionId}
      data-cohort={session.cohortLabel}
      data-draggable={isDraggable ? 'true' : 'false'}
      data-provisional={isProvisional ? 'true' : 'false'}
      data-selected={isSelected ? 'true' : 'false'}
      {...cardProps(onSelect, isDraggable, isDragging, dragAttributes, dragListeners)}
      className={`group relative flex h-full w-full flex-col justify-between rounded-md border border-l-4 border-amber-300 border-l-amber-700 bg-amber-50 p-2.5 hover:border-amber-500 dark:border-amber-900 dark:bg-amber-950/40 ${CARD_FOCUS} ${
        isDraggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'
      } ${isDragging ? 'opacity-40 border-dashed' : ''} ${isSelected ? 'ring-2 ring-primary ring-offset-2' : ''} ${
        isProvisional ? 'border-amber-700' : ''
      }`}
    >
      <div className="mb-1 flex flex-wrap items-center justify-between gap-x-1">
        <div className="flex items-center gap-1">
          {isDraggable && (
            <span data-testid={`drag-handle-${session.sessionId}`} className="shrink-0 cursor-grab" title="Drag to reschedule">
              <GripVertical className="h-4 w-4" />
            </span>
          )}
          <span className="inline-flex items-center gap-1 font-semibold">
            <Users aria-hidden="true" className="h-3.5 w-3.5" />
            Combined lecture
          </span>
          {isProvisional && (
            <span className="inline-flex items-center gap-1">
              <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
              Checking…
            </span>
          )}
        </div>
        <span className="font-semibold">Room {session.roomCode}</span>
      </div>

      <div className="my-1">
        <div className="font-serif text-base font-semibold leading-tight">
          {session.subjectCode} — {session.subjectName}
        </div>
        <div className="mt-0.5">{UI.classesTogether}: {session.cohortLabel}</div>
      </div>

      <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2 border-t border-dashed border-amber-400 pt-1.5">
        <span className="min-w-0 font-semibold">{sessionTeacher(session)}</span>
        <span className="shrink-0">{session.cohortSize} students</span>
      </div>
    </div>
  );
};
