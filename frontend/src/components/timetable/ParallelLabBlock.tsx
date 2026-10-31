import React from 'react';
import { EnrichedLabBlock, sessionTeacher } from '@/adapters/timetable';
import { periodLabel, periodSpan } from '@/lib/format';
import { UI, acrossBreakText } from '@/lib/wording';
import { CARD_FOCUS, cardProps } from './cardKeyboard';

interface ParallelLabBlockProps {
  labBlock: EnrichedLabBlock;
  onSelectSession?: (sessionId: string) => void;
  /** Member sessions outlined as in violation */
  flaggedSessionIds?: ReadonlySet<string>;
  /** The outline: red for a violation, amber for a session a proposed repair changed */
  flagClass?: string;
}

export const ParallelLabBlock: React.FC<ParallelLabBlockProps> = ({
  labBlock,
  onSelectSession,
  flaggedSessionIds,
  flagClass = 'ring-2 ring-destructive',
}) => {
  const first = labBlock.periods[0];
  const last = labBlock.periods[labBlock.periods.length - 1];
  return (
    <div
      data-testid="parallel-lab-block"
      data-block-id={labBlock.blockId}
      data-duration-periods={labBlock.periods.length}
      className="relative flex h-full w-full flex-col rounded-md border border-l-4 border-emerald-300 border-l-emerald-800 bg-emerald-50 p-2 dark:border-emerald-900 dark:bg-emerald-950/40"
    >
      {/* Block header */}
      <div className="mb-2 border-b border-emerald-300 pb-1.5 dark:border-emerald-800">
        <span className="font-semibold">Lab block</span>, {labBlock.periods.length} periods ({periodSpan(first, last)}),{' '}
        <span>
          {labBlock.sessions.length} batch{labBlock.sessions.length === 1 ? '' : 'es'} {UI.atSameTime}
        </span>
      </div>

      {/* The batches, side by side in time */}
      <div data-testid="parallel-batches-grid" className="grid flex-1 grid-cols-1 gap-1.5">
        {labBlock.sessions.map((sess) => (
          <div
            key={sess.sessionId}
            data-testid={`batch-session-${sess.sessionId}`}
            data-batch={sess.cohortLabel}
            data-subroom={sess.subRoomCode ?? sess.roomCode}
            data-flagged={flaggedSessionIds?.has(sess.sessionId) || undefined}
            {...cardProps(onSelectSession && (() => onSelectSession(sess.sessionId)), false, false)}
            className={`cursor-pointer rounded border border-emerald-300 bg-card p-1.5 hover:border-emerald-700 dark:border-emerald-800 ${CARD_FOCUS} ${
              flaggedSessionIds?.has(sess.sessionId) ? flagClass : ''
            }`}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-1">
              <span className="font-semibold">{sess.cohortLabel}</span>
              <span data-testid={`subroom-badge-${sess.sessionId}`} className="font-semibold">
                Room {sess.subRoomCode ?? sess.roomCode}
              </span>
            </div>
            <div className="font-serif font-semibold" title={sess.subjectName}>
              {sess.subjectCode} Lab
            </div>
            <div className="flex flex-wrap items-baseline justify-between gap-x-1">
              <span className="min-w-0 font-semibold">{sessionTeacher(sess)}</span>
              <span className="shrink-0">{sess.cohortSize} students</span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-1 text-center">
        {labBlock.spannedBreaks.length
          ? acrossBreakText(labBlock.spannedBreaks.map(periodLabel).join(', '))
          : UI.consecutivePeriods}
      </div>
    </div>
  );
};
