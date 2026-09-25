import React from 'react';
import { EnrichedSession } from '@/lib/timetableData';
import { Badge } from '@/components/ui/badge';
import { Users, DoorOpen, User, BookOpen, Sparkles } from 'lucide-react';

interface CombinedLectureBlockProps {
  session: EnrichedSession;
  onSelect?: () => void;
}

export const CombinedLectureBlock: React.FC<CombinedLectureBlockProps> = ({
  session,
  onSelect,
}) => {
  return (
    <div
      data-testid="combined-division-lecture"
      data-session-id={session.sessionId}
      data-cohort={session.cohortLabel}
      onClick={onSelect}
      className="group relative flex flex-col justify-between h-full w-full rounded-xl border-2 border-amber-500/40 bg-gradient-to-br from-amber-500/15 via-orange-500/10 to-transparent p-3 shadow-xs transition-all hover:border-amber-500/70 hover:shadow-md cursor-pointer dark:from-amber-950/30 dark:via-orange-950/20 dark:border-amber-500/30"
    >
      {/* Header with Combined Division Badge */}
      <div className="flex items-center justify-between gap-1 mb-1.5">
        <Badge
          variant="warning"
          className="text-[10px] px-2 py-0.5 font-bold uppercase tracking-wide gap-1 bg-amber-500/20 text-amber-900 border-amber-500/40 dark:text-amber-200"
        >
          <Users className="w-3 h-3 text-amber-600 dark:text-amber-400" />
          Combined Lecture
        </Badge>
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
