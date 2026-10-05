import React, { useMemo } from 'react';
import { SolvedSolution } from '@/types/solution';
import {
  DAYS,
  TEACHING_PERIODS,
  PeriodSlot,
  getSolvedSolutionFixture,
  buildEnrichedSessions,
  buildEnrichedLabBlocks,
  getPinnedBlocks,
} from '@/lib/timetableData';
import { ParallelLabBlock } from './ParallelLabBlock';
import { CombinedLectureBlock } from './CombinedLectureBlock';
import { PinnedBlock } from './PinnedBlock';
import { SessionCell } from './SessionCell';
import { Calendar, Clock, Coffee, Utensils } from 'lucide-react';

export interface TimetableGridProps {
  /**
   * The solved solution contract payload.
   * Defaults to contracts/examples/solution_v1.solved.example.json.
   */
  solution?: SolvedSolution;
  /** Optional cohort filter, e.g. 'all' | 'coh-div-se-b' | 'coh-div-se-c' */
  cohortFilter?: string;
  /** Optional click handler when a session card is selected */
  onSelectSession?: (sessionId: string) => void;
  /** Whether to render immovable institutional pinned blocks */
  showPinnedBlocks?: boolean;
}

export const TimetableGrid: React.FC<TimetableGridProps> = ({
  solution = getSolvedSolutionFixture(),
  cohortFilter = 'all',
  onSelectSession,
  showPinnedBlocks = true,
}) => {
  // 1. Build enriched sessions from the solution fixture
  const sessions = useMemo(() => buildEnrichedSessions(solution), [solution]);

  // 2. Extract parallel lab blocks
  const labBlocks = useMemo(() => buildEnrichedLabBlocks(sessions), [sessions]);

  // 3. Extract institutional pinned blocks
  const pinnedBlocks = useMemo(() => getPinnedBlocks(), []);

  // Filter sessions if cohortFilter is active
  const filteredSessions = useMemo(() => {
    if (cohortFilter === 'all') return sessions;
    return sessions.filter((s) => {
      // Include if direct match or combined cohort containing the division
      if (cohortFilter === 'coh-div-se-b') {
        return (
          s.cohortLabel.includes('SE-Comp B') ||
          s.cohortLabel.includes('SE A & B')
        );
      }
      if (cohortFilter === 'coh-div-se-c') {
        return (
          s.cohortLabel.includes('SE-Comp C') ||
          s.cohortLabel.includes('SE C & D')
        );
      }
      return true;
    });
  }, [sessions, cohortFilter]);

  // Filter lab blocks
  const filteredLabBlocks = useMemo(() => {
    if (cohortFilter === 'all') return labBlocks;
    return labBlocks.filter((lb) => {
      if (cohortFilter === 'coh-div-se-b') return lb.divisionLabel.includes('SE-Comp B');
      if (cohortFilter === 'coh-div-se-c') return lb.divisionLabel.includes('SE-Comp C');
      return true;
    });
  }, [labBlocks, cohortFilter]);

  // Filter pinned blocks
  const filteredPinnedBlocks = useMemo(() => {
    if (!showPinnedBlocks) return [];
    if (cohortFilter === 'all') return pinnedBlocks;
    return pinnedBlocks.filter((pb) => {
      if (cohortFilter === 'coh-div-se-b') return pb.cohortLabel.includes('SE-Comp B');
      if (cohortFilter === 'coh-div-se-c') return pb.cohortLabel.includes('SE-Comp C');
      return true;
    });
  }, [pinnedBlocks, cohortFilter, showPinnedBlocks]);

  // Track multi-period occupancy to avoid rendering duplicate cells in covered periods
  // key: `${day}-${period}`
  const coveredSlots = useMemo(() => {
    const set = new Set<string>();
    filteredLabBlocks.forEach((lb) => {
      for (let p = 1; p < lb.durationPeriods; p++) {
        set.add(`${lb.day}-${lb.startTeachingPeriod + p}`);
      }
    });
    return set;
  }, [filteredLabBlocks]);

  return (
    <div
      data-testid="timetable-grid"
      className="w-full overflow-x-auto rounded-2xl border border-border/80 bg-card/70 shadow-lg backdrop-blur-md"
    >
      <table className="w-full border-collapse text-left min-w-[900px]">
        {/* Table Header: Days of the week */}
        <thead>
          <tr className="border-b border-border bg-muted/60">
            <th className="w-36 p-3.5 text-center text-xs font-bold uppercase tracking-wider text-muted-foreground border-r border-border/60">
              <div className="flex items-center justify-center gap-1.5">
                <Clock className="h-4 w-4 text-primary" />
                <span>Period / Time</span>
              </div>
            </th>
            {DAYS.map((d) => (
              <th
                key={d.day}
                data-testid={`day-header-${d.day}`}
                className="p-3.5 text-center text-xs font-bold uppercase tracking-wider text-foreground border-r last:border-r-0 border-border/60"
              >
                <div className="flex items-center justify-center gap-1.5">
                  <Calendar className="h-4 w-4 text-muted-foreground" />
                  <span>{d.label}</span>
                </div>
              </th>
            ))}
          </tr>
        </thead>

        {/* Table Body: 8 Teaching Periods */}
        <tbody className="divide-y divide-border/60">
          {TEACHING_PERIODS.map((period: PeriodSlot) => {
            const hasBreak = !!period.precedingBreak;

            return (
              <React.Fragment key={`period-group-${period.teachingPeriod}`}>
                {/* Preceding Break Banner if applicable */}
                {hasBreak && (
                  <tr
                    key={`break-${period.teachingPeriod}`}
                    data-testid={`break-row-${period.precedingBreak?.label.toLowerCase().replace(/\s+/g, '-')}`}
                    className="bg-muted/30 border-y border-dashed border-border/70"
                  >
                    <td className="p-2 text-center text-[11px] font-mono font-semibold text-muted-foreground border-r border-border/60 bg-muted/40">
                      <span className="inline-flex items-center gap-1">
                        {period.precedingBreak?.label.includes('Short') ? (
                          <Coffee className="h-3 w-3 text-amber-500" />
                        ) : (
                          <Utensils className="h-3 w-3 text-orange-500" />
                        )}
                        {period.precedingBreak?.time}
                      </span>
                    </td>
                    <td
                      colSpan={5}
                      className="p-1.5 text-center text-xs font-medium tracking-wide text-muted-foreground bg-muted/20"
                    >
                      <span className="inline-flex items-center gap-2">
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-500/70" />
                        {period.precedingBreak?.label.toUpperCase()} — (Non-Schedulable Window)
                        <span className="h-1.5 w-1.5 rounded-full bg-amber-500/70" />
                      </span>
                    </td>
                  </tr>
                )}

                {/* Period Row */}
                <tr
                  key={`period-${period.teachingPeriod}`}
                  data-testid={`period-row-${period.teachingPeriod}`}
                  className="hover:bg-muted/10 transition-colors"
                >
                  {/* Period Time Column */}
                  <td className="p-3 text-center border-r border-border/60 bg-muted/20 align-top">
                    <div className="font-bold text-xs text-foreground">
                      Period {period.teachingPeriod + 1}
                    </div>
                    <div className="text-[11px] font-mono text-muted-foreground mt-0.5">
                      {period.timeLabel}
                    </div>
                    <div className="text-[9px] text-muted-foreground/70 font-mono mt-1">
                      Grid slot #{period.teachingPeriod}
                    </div>
                  </td>

                  {/* Day Cells */}
                  {DAYS.map((d) => {
                    const slotKey = `${d.day}-${period.teachingPeriod}`;

                    // If this slot is covered by a multi-period spanning lab block, skip rendering cell
                    if (coveredSlots.has(slotKey)) {
                      return null;
                    }

                    // Check for a parallel lab block starting in this slot
                    const labBlock = filteredLabBlocks.find(
                      (lb) => lb.day === d.day && lb.startTeachingPeriod === period.teachingPeriod
                    );

                    // Check for institutional pinned blocks in this slot
                    const pinnedBlock = filteredPinnedBlocks.find(
                      (pb) => pb.day === d.day && pb.teachingPeriod === period.teachingPeriod
                    );

                    // Check for sessions in this slot (non-lab-block or single sessions)
                    const session = filteredSessions.find(
                      (s) =>
                        s.day === d.day &&
                        s.teachingPeriod === period.teachingPeriod &&
                        !s.labBlockId
                    );

                    return (
                      <td
                        key={slotKey}
                        data-testid={`grid-cell-${d.day}-${period.teachingPeriod}`}
                        rowSpan={labBlock ? labBlock.durationPeriods : 1}
                        data-rowspan={labBlock ? labBlock.durationPeriods : 1}
                        data-spans-adjacent={labBlock ? "true" : "false"}
                        className={`p-2 align-top border-r last:border-r-0 border-border/60 min-h-[90px] transition-colors ${
                          labBlock ? 'bg-emerald-500/5' : ''
                        }`}
                      >
                        {/* 1. Double-period Parallel Lab Block Case */}
                        {labBlock && (
                          <ParallelLabBlock
                            labBlock={labBlock}
                            onSelectSession={onSelectSession}
                          />
                        )}

                        {/* 2. Institutional Pinned Block Case */}
                        {!labBlock && pinnedBlock && (
                          <PinnedBlock
                            id={pinnedBlock.id}
                            label={pinnedBlock.label}
                            kind={pinnedBlock.kind}
                            roomCode={pinnedBlock.roomCode}
                            cohortLabel={pinnedBlock.cohortLabel}
                            description={pinnedBlock.description}
                          />
                        )}

                        {/* 3. Combined-Division Lecture Case */}
                        {!labBlock && !pinnedBlock && session?.isCombinedDivision && (
                          <CombinedLectureBlock
                            session={session}
                            onSelect={() => onSelectSession?.(session.sessionId)}
                          />
                        )}

                        {/* 4. Standard Solver Session / Pinned Slot Case */}
                        {!labBlock && !pinnedBlock && session && !session.isCombinedDivision && (
                          <SessionCell
                            session={session}
                            onSelect={() => onSelectSession?.(session.sessionId)}
                          />
                        )}

                        {/* Empty / Unscheduled Slot */}
                        {!labBlock && !pinnedBlock && !session && (
                          <div className="flex h-16 w-full items-center justify-center rounded-lg border border-dashed border-border/40 text-[10px] text-muted-foreground/40 font-mono select-none">
                            Free Slot
                          </div>
                        )}
                      </td>
                    );
                  })}
                </tr>
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
