import React from 'react';
import { Pin, Lock, DoorOpen, ShieldAlert } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

interface PinnedBlockProps {
  id: string;
  label: string;
  kind?: string;
  roomCode?: string;
  cohortLabel?: string;
  description?: string;
  onSelect?: () => void;
}

export const PinnedBlock: React.FC<PinnedBlockProps> = ({
  id,
  label,
  kind = "Fixed Institutional Occupancy",
  roomCode,
  cohortLabel,
  description = "Immovable constraint pre-allocated before solver execution",
  onSelect,
}) => {
  return (
    <div
      data-testid="pinned-block"
      data-pinned-id={id}
      onClick={onSelect}
      className="group relative flex flex-col justify-between h-full w-full rounded-xl border-2 border-slate-400/60 bg-slate-100/90 bg-pinned-pattern p-3 shadow-xs transition-all hover:border-slate-500 hover:shadow-md cursor-pointer dark:bg-slate-900/90 dark:border-slate-600/70"
    >
      {/* Top Bar: Pinned Badge + Lock */}
      <div className="flex items-center justify-between gap-1 mb-1.5">
        <Badge
          variant="pinned"
          className="flex items-center gap-1 bg-slate-300 text-slate-800 dark:bg-slate-800 dark:text-slate-200 border-slate-400/50"
        >
          <Pin className="h-3 w-3 text-rose-500 fill-rose-500 rotate-45" />
          <span>PINNED BLOCK</span>
        </Badge>
        <span className="flex items-center gap-1 text-[10px] font-mono text-slate-600 dark:text-slate-400">
          <Lock className="h-3 w-3 text-slate-500" />
          Immovable
        </span>
      </div>

      {/* Main Content */}
      <div className="my-1">
        <div className="flex items-center gap-1.5 font-bold text-sm text-slate-900 dark:text-slate-100">
          <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <span>{label}</span>
        </div>
        <p className="mt-1 text-[11px] text-slate-600 dark:text-slate-400 font-medium">
          {kind}
        </p>
      </div>

      {/* Footer Info */}
      <div className="mt-2 pt-2 border-t border-dashed border-slate-300 dark:border-slate-700 flex items-center justify-between text-xs text-slate-600 dark:text-slate-400">
        <span className="truncate max-w-[120px] font-semibold">
          {cohortLabel ? `Cohort: ${cohortLabel}` : description}
        </span>
        {roomCode && (
          <span className="inline-flex items-center gap-0.5 rounded bg-slate-200/80 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-800 dark:bg-slate-800 dark:text-slate-200">
            <DoorOpen className="h-2.5 w-2.5 text-slate-500" />
            Room {roomCode}
          </span>
        )}
      </div>
    </div>
  );
};
