import React from 'react';
import { Lock } from 'lucide-react';

interface PinnedBlockProps {
  id: string;
  label: string;
  /** What kind of fixed item it is, in words (wording.ts pinKindLabel) */
  kind: string;
  /** Teachers by full name */
  teachers?: string;
  roomCode?: string;
  cohortLabel?: string;
  /** Every cohort it holds, on hover: cohortLabel may name only the first few */
  cohortTitle?: string;
  onSelect?: () => void;
}

export const PinnedBlock: React.FC<PinnedBlockProps> = ({ id, label, kind, teachers, roomCode, cohortLabel, cohortTitle, onSelect }) => {
  return (
    <div
      data-testid="pinned-block"
      data-pinned-id={id}
      onClick={onSelect}
      className="relative flex h-full w-full cursor-pointer flex-col justify-between break-words rounded-md border border-l-4 border-slate-400 border-l-slate-700 bg-slate-100 bg-pinned-pattern p-2.5 dark:border-slate-600 dark:bg-slate-900"
    >
      <div data-testid="pinned-kind" className="mb-1 flex items-start gap-1 font-semibold">
        <Lock aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{kind}</span>
      </div>

      <div className="my-1">
        <div className="font-serif text-base font-semibold leading-tight">{label}</div>
        {teachers && <p className="mt-0.5">Teacher: {teachers}</p>}
      </div>

      {(cohortLabel || roomCode) && (
        <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2 border-t border-dashed border-slate-400 pt-1.5">
          {cohortLabel && (
            <span className="min-w-0" title={cohortTitle}>
              Cohort: {cohortLabel}
            </span>
          )}
          {roomCode && <span className="shrink-0 font-semibold">Room {roomCode}</span>}
        </div>
      )}
    </div>
  );
};
