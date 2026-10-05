import React from 'react';
import { EnrichedLabBlock } from '@/lib/timetableData';
import { Badge } from '@/components/ui/badge';
import { Layers, Clock, DoorOpen, User, BookOpen } from 'lucide-react';

interface ParallelLabBlockProps {
  labBlock: EnrichedLabBlock;
  onSelectSession?: (sessionId: string) => void;
}

export const ParallelLabBlock: React.FC<ParallelLabBlockProps> = ({
  labBlock,
  onSelectSession,
}) => {
  return (
    <div
      data-testid="parallel-lab-block"
      data-block-id={labBlock.blockId}
      data-duration-periods={labBlock.durationPeriods}
      className="relative flex flex-col h-full w-full rounded-xl border-2 border-emerald-500/40 bg-gradient-to-br from-emerald-500/10 via-teal-500/5 to-transparent p-2.5 shadow-sm transition-all hover:border-emerald-500/70 hover:shadow-md dark:from-emerald-950/30 dark:via-teal-950/20 dark:border-emerald-500/30"
    >
      {/* Block Header */}
      <div className="flex items-center justify-between border-b border-emerald-500/20 pb-1.5 mb-2">
        <div className="flex items-center gap-1.5">
          <span className="flex h-5 w-5 items-center justify-center rounded-md bg-emerald-500 text-white shadow-xs">
            <Layers className="h-3 w-3" />
          </span>
          <span className="font-semibold text-xs tracking-tight text-emerald-900 dark:text-emerald-200">
            Parallel Lab Block (Double Period)
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge variant="success" className="text-[10px] px-1.5 py-0 h-4 font-mono font-medium">
            <Clock className="w-2.5 h-2.5 mr-1 inline" />
            2 Periods (10:00 – 12:15)
          </Badge>
          <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 border-emerald-400 text-emerald-800 dark:text-emerald-300">
            4 Batches Parallel
          </Badge>
        </div>
      </div>

      {/* 4 Parallel Batch Sub-rooms Grid */}
      <div
        data-testid="parallel-batches-grid"
        className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 flex-1"
      >
        {labBlock.sessions.map((sess) => (
          <div
            key={sess.sessionId}
            data-testid={`batch-session-${sess.sessionId}`}
            data-batch={sess.batchLabel}
            data-subroom={sess.subRoomCode ?? sess.roomCode}
            onClick={() => onSelectSession?.(sess.sessionId)}
            className="group/batch relative flex flex-col justify-between rounded-lg border border-emerald-500/25 bg-background/80 p-2 shadow-xs backdrop-blur-xs transition-all hover:bg-emerald-500/10 hover:border-emerald-500/50 cursor-pointer"
          >
            {/* Top row: Batch Pill + Room */}
            <div className="flex items-center justify-between gap-1 mb-1">
              <span className="inline-flex items-center rounded-md bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800 dark:bg-emerald-900/60 dark:text-emerald-200">
                {sess.batchLabel ?? "Batch"}
              </span>
              <span
                data-testid={`subroom-badge-${sess.sessionId}`}
                className="inline-flex items-center gap-0.5 rounded border border-emerald-300/40 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-emerald-800 dark:bg-emerald-900/40 dark:border-emerald-700/50 dark:text-emerald-300"
              >
                <DoorOpen className="h-2.5 w-2.5 text-emerald-600 dark:text-emerald-400" />
                {sess.subRoomCode ?? sess.roomCode}
              </span>
            </div>

            {/* Subject Code & Full Name */}
            <div className="flex items-baseline gap-1 my-0.5">
              <BookOpen className="h-3 w-3 text-emerald-600 dark:text-emerald-400 shrink-0 self-center" />
              <span className="text-xs font-bold text-foreground">
                {sess.subjectCode} Lab
              </span>
              <span className="text-[10px] text-muted-foreground truncate hidden lg:inline">
                ({sess.subjectName})
              </span>
            </div>

            {/* Faculty Initials & Full Name */}
            <div className="flex items-center justify-between text-[11px] text-muted-foreground mt-1 pt-1 border-t border-dashed border-emerald-500/15">
              <span className="flex items-center gap-1 font-medium">
                <User className="h-2.5 w-2.5 text-emerald-600 dark:text-emerald-400" />
                <span className="font-semibold text-foreground">{sess.facultyInitials}</span>
                <span className="text-[10px] text-muted-foreground truncate max-w-[90px]">
                  {sess.facultyName}
                </span>
              </span>
              <span className="text-[9px] text-muted-foreground font-mono">
                {sess.cohortSize} studs
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-1 text-[10px] text-emerald-800/80 dark:text-emerald-300/80 text-center font-medium">
        Straddles 11:00 Short Break · Both periods contiguous
      </div>
    </div>
  );
};
