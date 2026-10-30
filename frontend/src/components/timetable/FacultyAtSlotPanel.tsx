import React, { useMemo, useState } from 'react';
import { DAY_NAMES, EdgeList, EnrichedSession, Labels, buildWeekGrid, facultyAtSlot } from '@/adapters/timetable';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { periodLabel } from '@/lib/format';

interface FacultyAtSlotPanelProps {
  /** The current edge list (every accepted change, D52): faculty, unavailability, pinned occupancy */
  edgeList: EdgeList;
  /** The official timetable's sessions on that edge list; never a proposal. Empty when there is none */
  sessions: EnrichedSession[];
  labels: Labels;
  /** False when the instance has no solved official timetable */
  solved: boolean;
}

const selectClass = 'rounded-md border border-input bg-card px-2 py-1 font-medium';

/**
 * The coordinator's dual view (CONTEXT §1): at a chosen day and teaching period, the faculty free
 * then beside the faculty engaged then and with what. Read-only; a substitute is found from a
 * session's details.
 */
export const FacultyAtSlotPanel: React.FC<FacultyAtSlotPanelProps> = ({ edgeList, sessions, labels, solved }) => {
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
  const [day, setDay] = useState(0);
  const [period, setPeriod] = useState(grid.teachingPeriods[0] ?? 0);
  const { free, engaged } = useMemo(
    () => facultyAtSlot(edgeList, labels, sessions, day, period),
    [edgeList, labels, sessions, day, period]
  );

  return (
    <Card data-testid="faculty-at-slot">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>Free and engaged teachers</CardTitle>
            <CardDescription>
              From the official timetable and the accepted changes. To substitute, open a session and use Find
              substitute.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <select aria-label="Faculty at slot day" value={day} onChange={(e) => setDay(Number(e.target.value))} className={selectClass}>
              {grid.days.map((d) => (
                <option key={d} value={d}>
                  {DAY_NAMES[d]}
                </option>
              ))}
            </select>
            <select
              aria-label="Faculty at slot period"
              value={period}
              onChange={(e) => setPeriod(Number(e.target.value))}
              className={selectClass}
            >
              {grid.teachingPeriods.map((p) => (
                <option key={p} value={p}>
                  {periodLabel(p)}
                  {labels.clock(p) && ` (${labels.clock(p)})`}
                </option>
              ))}
            </select>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {!solved && (
          <p data-testid="faculty-at-slot-unsolved">
            No official timetable yet: only pinned occupancy and unavailability are counted.
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <section data-testid="free-faculty">
            <h3 className="mb-1.5 text-lg font-semibold">Free ({free.length})</h3>
            {free.length === 0 ? (
              <p>Nobody is free at this time.</p>
            ) : (
              <ul className="space-y-1">
                {free.map((f) => (
                  <li key={f.facultyId} data-testid={`free-${f.facultyId}`}>
                    {f.name}
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section data-testid="engaged-faculty">
            <h3 className="mb-1.5 text-lg font-semibold">Engaged ({engaged.length})</h3>
            {engaged.length === 0 ? (
              <p>Nobody is engaged at this time.</p>
            ) : (
              <ul className="space-y-1">
                {engaged.map((f) => (
                  <li key={f.facultyId} data-testid={`engaged-${f.facultyId}`}>
                    <span className="font-semibold">{f.name}</span>: {f.engagedWith.join('; ')}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </CardContent>
    </Card>
  );
};
