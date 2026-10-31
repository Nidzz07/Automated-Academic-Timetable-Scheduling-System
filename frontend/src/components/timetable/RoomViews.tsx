import React, { useMemo, useState } from 'react';
import { DAY_NAMES, EXAMPLE_LABELS, EdgeList, EnrichedSession, Labels, buildWeekGrid } from '@/adapters/timetable';
import { freeRoomsAt, roomOccupancies } from '@/adapters/rooms';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { periodLabel } from '@/lib/format';

interface RoomViewsProps {
  /** Rooms, sub-rooms, grid and pinned occupancy */
  edgeList: EdgeList;
  /** Placed sessions (from the solution); empty when the instance has no solution */
  sessions: EnrichedSession[];
  /** Room names, pin labels and clock times; defaults to the contract examples' */
  labels?: Labels;
}

const selectClass = 'rounded-md border border-input bg-card px-2 py-1 font-medium';

/**
 * Weekly timetable of one room (ROADMAP D15). Sub-room use is shown with the sub-room code.
 */
export const RoomTimetable: React.FC<RoomViewsProps> = ({ edgeList, sessions, labels = EXAMPLE_LABELS }) => {
  const rooms = edgeList.rooms.filter((r) => r.parent_room_id === null);
  const [roomId, setRoomId] = useState(rooms[0]?.id ?? '');
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
  const occupancies = useMemo(() => roomOccupancies(sessions, edgeList, labels), [sessions, edgeList, labels]);
  const code = new Map(edgeList.rooms.map((r) => [r.id, labels.room(r)]));
  const inRoom = occupancies.filter((o) => o.roomId === roomId);

  return (
    <Card data-testid="room-timetable">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Room timetable</CardTitle>
          <select
            aria-label="Select room"
            value={roomId}
            onChange={(e) => setRoomId(e.target.value)}
            className={selectClass}
          >
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {labels.room(r)} ({r.is_lab ? 'lab' : 'classroom'}, {r.capacity})
              </option>
            ))}
          </select>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto pt-0">
        {/* Like the main grid: the days share the card's width and the text wraps. Beside another card
            (lg and up) that is the whole fit; alone on a narrow screen the card scrolls below 560 px. */}
        <table className="w-full min-w-[560px] table-fixed border-collapse break-words text-xs lg:min-w-0">
          <thead>
            <tr className="border-b border-border bg-muted">
              <th className="w-20 p-2 text-left">Period</th>
              {grid.days.map((d) => (
                <th key={d} className="p-2 text-left">
                  {DAY_NAMES[d]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {grid.periods.map(({ period, teaching }) => (
              <tr key={period} className={teaching ? '' : 'bg-muted'}>
                <td className="p-2 font-semibold">
                  {periodLabel(period)}
                  {labels.clock(period) && <div className="font-normal">{labels.clock(period)}</div>}
                </td>
                {grid.days.map((day) => {
                  const here = inRoom.filter((o) => o.day === day && o.period === period);
                  return (
                    <td key={day} data-testid={`room-cell-${day}-${period}`} className="p-2 align-top">
                      {!teaching
                        ? 'Break'
                        : here.map((o, i) => (
                            <div key={i}>
                              {o.label}
                              {o.subRoomId && <span>, {code.get(o.subRoomId)}</span>}
                            </div>
                          ))}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
};

/**
 * Rooms free at a chosen day and period; labs list the batch places (sub-rooms) not in use.
 */
export const FreeRoomsPanel: React.FC<RoomViewsProps> = ({ edgeList, sessions, labels = EXAMPLE_LABELS }) => {
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
  const [day, setDay] = useState(0);
  const [period, setPeriod] = useState(grid.teachingPeriods[0] ?? 0);
  const occupancies = useMemo(() => roomOccupancies(sessions, edgeList, labels), [sessions, edgeList, labels]);
  const free = freeRoomsAt(edgeList, occupancies, day, period, labels);

  return (
    <Card data-testid="free-rooms">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Free rooms</CardTitle>
          <div className="flex items-center gap-2">
            <select aria-label="Free rooms day" value={day} onChange={(e) => setDay(Number(e.target.value))} className={selectClass}>
              {grid.days.map((d) => (
                <option key={d} value={d}>
                  {DAY_NAMES[d]}
                </option>
              ))}
            </select>
            <select
              aria-label="Free rooms period"
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
      <CardContent className="pt-0">
        {free.length === 0 ? (
          <p>No room is free at this time.</p>
        ) : (
          <ul className="space-y-1.5">
            {free.map((r) => (
              <li
                key={r.roomId}
                data-testid={`free-room-${r.code}`}
                className="flex flex-wrap items-center gap-2 border-b border-border py-1.5"
              >
                <span className="font-semibold">{r.code}</span>
                <span>
                  {r.isLab ? 'Lab' : 'Classroom'} · capacity {r.capacity}
                </span>
                {r.subRoomCount > 0 && (
                  <span data-testid={`batch-places-${r.code}`}>
                    {r.freeSubRoomCodes.length} of {r.subRoomCount} batch places free (
                    {r.freeSubRoomCodes.join(', ')})
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
};
