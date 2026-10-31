import React from 'react';
import { Lock } from 'lucide-react';
import { cohortListParts, moreText } from '@/lib/wording';

interface PinnedBlockProps {
  id: string;
  label: string;
  /** What kind of fixed item it is, in words (wording.ts pinKindLabel) */
  kind: string;
  /** Teachers as "Name (INITIALS)" */
  teachers?: string;
  roomCode?: string;
  /** Every class it holds: the first few show, the whole list on hover and keyboard focus */
  cohorts?: string[];
  /** Few enough to list them all: a division is chosen */
  listAll?: boolean;
  onSelect?: () => void;
}

export const PinnedBlock: React.FC<PinnedBlockProps> = ({ id, label, kind, teachers, roomCode, cohorts = [], listAll = false, onSelect }) => {
  const { listed, more } = cohortListParts(cohorts, listAll);
  return (
    <div
      data-testid="pinned-block"
      data-pinned-id={id}
      onClick={onSelect}
      className={`relative flex h-full w-full flex-col justify-between break-words rounded-md border border-l-4 border-slate-400 border-l-slate-700 bg-slate-100 bg-pinned-pattern p-2.5 dark:border-slate-600 dark:bg-slate-900 ${
        onSelect ? 'cursor-pointer' : ''
      }`}
    >
      <div data-testid="pinned-kind" className="mb-1 flex items-start gap-1 font-semibold">
        <Lock aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{kind}</span>
      </div>

      <div className="my-1">
        <div className="font-serif text-base font-semibold leading-tight">{label}</div>
        {teachers && <p className="mt-0.5">Teacher: {teachers}</p>}
      </div>

      {(listed || roomCode) && (
        <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2 border-t border-dashed border-slate-400 pt-1.5">
          {listed && (
            <span className="min-w-0">
              Class: {listed}
              {more > 0 && (
                <>
                  {' '}
                  <span
                    tabIndex={0}
                    data-testid="pinned-more"
                    aria-label={`All classes: ${cohorts.join(', ')}`}
                    className="group/more relative cursor-help font-semibold underline decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {moreText(more)}
                    <span
                      role="tooltip"
                      data-testid="pinned-more-list"
                      className="absolute bottom-full left-0 z-40 mb-1 hidden w-64 rounded-md border border-border bg-card p-2 font-normal no-underline shadow-lg group-hover/more:block group-focus/more:block"
                    >
                      {cohorts.join(', ')}
                    </span>
                  </span>
                </>
              )}
            </span>
          )}
          {roomCode && <span className="shrink-0 font-semibold">Room {roomCode}</span>}
        </div>
      )}
    </div>
  );
};
