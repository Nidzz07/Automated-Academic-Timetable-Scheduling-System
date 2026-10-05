import React from 'react';
import { EnrichedSession } from '@/lib/timetableData';
import { Badge } from '@/components/ui/badge';
import { Users, DoorOpen, User, BookOpen, Sparkles, GripVertical, Loader2 } from 'lucide-react';

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
      onClick={onSelect}
      {...(isDraggable ? dragAttributes : {})}
      {...(isDraggable ? dragListeners : {})}
      className={`group relative flex flex-col justify-between h-full w-full rounded-xl border-2 border-amber-500/40 bg-gradient-to-br from-amber-500/15 via-orange-500/10 to-transparent p-3 shadow-xs transition-all hover:border-amber-500/70 hover:shadow-md ${
        isDraggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'
      } ${
        isDragging ? 'opacity-40 scale-95 border-dashed border-amber-500' : ''
      } ${
        isSelected ? 'ring-2 ring-primary ring-offset-2' : ''
      } ${
        isProvisional ? 'border-amber-500 bg-amber-500/25 animate-pulse' : ''
      } dark:from-amber-950/30 dark:via-orange-950/20 dark:border-amber-500/30`}
    >
      {/* Header with Combined Division Badge */}
      <div className="flex items-center justify-between gap-1 mb-1.5">
        <div className="flex items-center gap-1">
          {isDraggable && (
            <span
              data-testid={`drag-handle-${session.sessionId}`}
              className="text-amber-800/60 dark:text-amber-300/60 group-hover:text-amber-900 dark:group-hover:text-amber-100 shrink-0 cursor-grab"
              title="Drag to reschedule"
            >
              <GripVertical className="h-3.5 w-3.5" />
            </span>
          )}

          <Badge
            variant="warning"
            className="text-[10px] px-2 py-0.5 font-bold uppercase tracking-wide gap-1 bg-amber-500/20 text-amber-900 border-amber-500/40 dark:text-amber-200"
          >
            <Users className="w-3 h-3 text-amber-600 dark:text-amber-400" />
            Combined Lecture
          </Badge>

          {isProvisional && (
            <Badge variant="warning" className="text-[10px] px-1.5 py-0.5 gap-1 bg-amber-500/30">
              <Loader2 className="w-2.5 h-2.5 animate-spin" />
              Validating...
            </Badge>
          )}
        </div>

        <span className="inline-flex items-center gap-1 rounded border border-amber-400/40 bg-amber-100/60 px-1.5 py-0.5 text-[10px] font-mono font-bold text-amber-900 dark:bg-amber-900/40 dark:border-amber-700/50 dark:text-amber-200">
          <DoorOpen className="h-3 w-3 text-amber-600 dark:text-amber-400" />
          Room {session.roomCode}
        </span>
      </div>

      {/* Main Subject */}
      <div className="my-1">
        <div className="flex items-center gap-1.5">
          <BookOpen className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <span className="font-extrabold text-sm text-foreground">
            {session.subjectCode} — {session.subjectName}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-1.5 text-xs font-semibold text-amber-800 dark:text-amber-300">
          <Sparkles className="h-3 w-3 text-amber-500" />
          <span>Full Union Cohort: {session.cohortLabel}</span>
        </div>
      </div>

      {/* Cohort & Faculty Footer */}
      <div className="mt-2 pt-2 border-t border-dashed border-amber-500/30 flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <User className="h-3 w-3 text-amber-600 dark:text-amber-400" />
          <span className="font-bold text-foreground">{session.facultyInitials}</span>
          <span className="text-[11px] text-muted-foreground">({session.facultyName})</span>
        </div>
        <div className="text-[11px] font-mono font-medium text-amber-800 dark:text-amber-300">
          {session.cohortSize} students
        </div>
      </div>
    </div>
  );
};
