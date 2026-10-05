import React from 'react';
import { EnrichedSession } from '@/lib/timetableData';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { X, BookOpen, User, DoorOpen, Users, Clock, Pin, FileCode } from 'lucide-react';

interface SessionDetailModalProps {
  session: EnrichedSession | null;
  onClose: () => void;
}

export const SessionDetailModal: React.FC<SessionDetailModalProps> = ({
  session,
  onClose,
}) => {
  if (!session) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4"
    >
      <div className="relative w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-150">
        {/* Close Button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <X className="h-5 w-5" />
        </button>

        {/* Header */}
        <div className="flex items-center gap-2 mb-4">
          <Badge variant={session.isPinned ? "pinned" : session.isCombinedDivision ? "warning" : "info"}>
            {session.isPinned
              ? "Pinned / Immovable"
              : session.isCombinedDivision
              ? "Combined Division"
              : session.sessionType.toUpperCase()}
          </Badge>
          <span className="font-mono text-xs text-muted-foreground">
            {session.sessionId}
          </span>
        </div>

        <h3 className="text-xl font-bold text-foreground flex items-center gap-2">
          <BookOpen className="h-5 w-5 text-primary" />
          <span>{session.subjectCode} — {session.subjectName}</span>
        </h3>

        {/* Details Grid */}
        <div className="grid grid-cols-2 gap-3 my-4 text-xs">
          <div className="rounded-lg border border-border/60 bg-muted/30 p-2.5">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <User className="h-3.5 w-3.5 text-primary" />
              <span>Faculty</span>
            </div>
            <div className="font-bold text-foreground">{session.facultyName}</div>
            <div className="text-[11px] font-mono text-muted-foreground">
              Initials: {session.facultyInitials}
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/30 p-2.5">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <DoorOpen className="h-3.5 w-3.5 text-primary" />
              <span>Room Allocation</span>
            </div>
            <div className="font-bold text-foreground">
              Room {session.subRoomCode ?? session.roomCode}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {session.subRoomCode ? `Sub-room partition of Room ${session.roomCode}` : 'Full room'}
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/30 p-2.5">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <Users className="h-3.5 w-3.5 text-primary" />
              <span>Cohort</span>
            </div>
            <div className="font-bold text-foreground">{session.cohortLabel}</div>
            <div className="text-[11px] text-muted-foreground">
              {session.cohortSize} students enrolled
            </div>
          </div>

          <div className="rounded-lg border border-border/60 bg-muted/30 p-2.5">
            <div className="flex items-center gap-1.5 text-muted-foreground mb-1">
              <Clock className="h-3.5 w-3.5 text-primary" />
              <span>Duration</span>
            </div>
            <div className="font-bold text-foreground">
              {session.durationPeriods} teaching period{session.durationPeriods > 1 ? 's' : ''}
            </div>
            <div className="text-[11px] text-muted-foreground font-mono">
              Starting period index: {session.teachingPeriod}
            </div>
          </div>
        </div>

        {/* Pinned Note */}
        {session.isPinned && (
          <div className="flex items-center gap-2 rounded-lg border border-slate-300 bg-slate-100 p-2.5 text-xs text-slate-800 dark:bg-slate-900 dark:border-slate-700 dark:text-slate-300 mb-4">
            <Pin className="h-4 w-4 text-rose-500 fill-rose-500" />
            <div>
              <strong>Immovable Solver Constraint:</strong> {session.pinnedReason}
            </div>
          </div>
        )}

        {/* Contract raw JSON snippet */}
        <div className="rounded-lg border border-border/60 bg-muted/40 p-2.5 text-xs">
          <div className="flex items-center gap-1 text-[11px] font-mono font-semibold text-muted-foreground mb-1">
            <FileCode className="h-3 w-3" />
            <span>Frozen Contract 3 Placement Payload:</span>
          </div>
          <pre className="font-mono text-[10px] text-muted-foreground overflow-x-auto p-1.5 bg-background/80 rounded border">
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
        </div>

        <div className="mt-4 flex justify-end">
          <Button variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>
  );
};
