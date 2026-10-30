import React from 'react';
import { Lock } from 'lucide-react';

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
  kind = 'Fixed institutional occupancy',
  roomCode,
  cohortLabel,
  description = 'Fixed before the solver runs; it cannot be moved',
  onSelect,
}) => {
  return (
    <div
      data-testid="pinned-block"
      data-pinned-id={id}
      onClick={onSelect}
      className="relative flex h-full w-full cursor-pointer flex-col justify-between rounded-md border border-l-4 border-slate-400 border-l-slate-700 bg-slate-100 bg-pinned-pattern p-2.5 dark:border-slate-600 dark:bg-slate-900"
    >
      <div className="mb-1 flex items-center gap-1 font-semibold">
        <Lock aria-hidden="true" className="h-3.5 w-3.5" />
        <span>Pinned block, immovable</span>
      </div>

      <div className="my-1">
        <div className="font-serif text-base font-semibold leading-tight">{label}</div>
        <p className="mt-0.5">{kind}</p>
      </div>

      <div className="mt-1 flex items-center justify-between gap-2 border-t border-dashed border-slate-400 pt-1.5">
        <span className="max-w-[140px] truncate" title={cohortLabel}>
          {cohortLabel ? `Cohort: ${cohortLabel}` : description}
        </span>
        {roomCode && <span className="shrink-0 font-semibold">Room {roomCode}</span>}
      </div>
    </div>
  );
};
