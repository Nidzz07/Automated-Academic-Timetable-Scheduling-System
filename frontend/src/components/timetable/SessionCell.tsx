import React from 'react';
import { EnrichedSession } from '@/lib/timetableData';
import { BookOpen, User, DoorOpen, Pin, GripVertical, Loader2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

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
      className={`group relative flex flex-col justify-between h-full w-full rounded-xl border p-3 shadow-xs transition-all ${
        isDraggable ? 'cursor-grab active:cursor-grabbing hover:shadow-md' : 'cursor-pointer hover:shadow-xs'
      } ${
        isDragging ? 'opacity-40 scale-95 border-primary border-dashed' : ''
      } ${
        isSelected ? 'ring-2 ring-primary ring-offset-2' : ''
      } ${
        isProvisional
          ? 'border-amber-500 bg-amber-500/15 animate-pulse'
          : session.isPinned
          ? 'border-slate-400 bg-slate-100/90 dark:bg-slate-900/90 bg-pinned-pattern'
          : 'border-indigo-500/30 bg-gradient-to-br from-indigo-500/10 via-purple-500/5 to-transparent hover:border-indigo-500/60 dark:from-indigo-950/30 dark:border-indigo-500/30'
      }`}
    >
      {/* Header: Type / Pinned Badge + Drag handle + Room */}
      <div className="flex items-center justify-between gap-1 mb-1">
        <div className="flex items-center gap-1">
          {isDraggable && (
            <span
              data-testid={`drag-handle-${session.sessionId}`}
              className="text-muted-foreground/60 group-hover:text-foreground shrink-0 cursor-grab"
              title="Drag to reschedule"
            >
              <GripVertical className="h-3.5 w-3.5" />
            </span>
          )}

          {session.isPinned ? (
            <Badge variant="pinned" className="text-[10px] px-1.5 py-0.5 gap-0.5">
              <Pin className="w-2.5 h-2.5 text-rose-500 fill-rose-500 rotate-45" />
              Fixed Slot
            </Badge>
          ) : isProvisional ? (
            <Badge variant="warning" className="text-[10px] px-1.5 py-0.5 gap-1 bg-amber-500/20 text-amber-900 dark:text-amber-200">
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              Validating...
            </Badge>
          ) : (
            <Badge variant="info" className="text-[10px] px-1.5 py-0.5 font-semibold">
              Lecture
            </Badge>
          )}
        </div>

        <span className="inline-flex items-center gap-0.5 rounded border border-border bg-background/90 px-1.5 py-0.5 text-[10px] font-mono font-bold">
          <DoorOpen className="h-2.5 w-2.5 text-muted-foreground" />
          {session.subRoomCode ?? session.roomCode}
        </span>
      </div>

      {/* Subject Information */}
      <div className="my-1">
        <div className="flex items-center gap-1.5 font-bold text-sm text-foreground">
          <BookOpen className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-400 shrink-0" />
          <span>{session.subjectCode}</span>
          <span className="text-xs font-normal text-muted-foreground truncate">
            {session.subjectName}
          </span>
        </div>
        <div className="text-[11px] font-medium text-muted-foreground mt-0.5">
          {session.cohortLabel}
        </div>
      </div>

      {/* Faculty and Cohort Footer */}
      <div className="mt-2 pt-2 border-t border-dashed border-border/60 flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <User className="h-3 w-3 text-muted-foreground" />
          <span className="font-bold text-foreground">{session.facultyInitials}</span>
          <span className="text-[10px] text-muted-foreground truncate max-w-[85px]">
            {session.facultyName}
          </span>
        </div>
        <div className="text-[10px] font-mono">
          {session.cohortSize} studs
        </div>
      </div>
    </div>
  );
};
