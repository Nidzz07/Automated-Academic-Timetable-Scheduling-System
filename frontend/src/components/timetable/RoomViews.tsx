import React, { useMemo, useState } from 'react';
import { DAY_NAMES, EdgeList, EnrichedSession, buildWeekGrid } from '@/adapters/timetable';
import { freeRoomsAt, roomOccupancies } from '@/adapters/rooms';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { DoorOpen, Search } from 'lucide-react';

interface RoomViewsProps {
  /** Rooms, sub-rooms, grid and pinned occupancy */
  edgeList: EdgeList;
  /** Placed sessions (from the solution); empty when the instance has no solution */
  sessions: EnrichedSession[];
}

const selectClass = 'rounded-md border border-border bg-card px-2 py-1 text-xs font-medium';

/**
 * Weekly timetable of one room (ROADMAP D15). Sub-room use is shown with the sub-room code.
 */
export const RoomTimetable: React.FC<RoomViewsProps> = ({ edgeList, sessions }) => {
  const rooms = edgeList.rooms.filter((r) => r.parent_room_id === null);
  const [roomId, setRoomId] = useState(rooms[0]?.id ?? '');
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
  const occupancies = useMemo(() => roomOccupancies(sessions, edgeList), [sessions, edgeList]);
  const code = new Map(edgeList.rooms.map((r) => [r.id, r.code]));
  const inRoom = occupancies.filter((o) => o.roomId === roomId);

  return (
    <Card data-testid="room-timetable" className="border-border/60 bg-card/60">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base font-bold">
            <DoorOpen className="h-4 w-4 text-primary" /> Room Timetable
          </CardTitle>
          <select
            aria-label="Select room"
            value={roomId}
            onChange={(e) => setRoomId(e.target.value)}
            className={selectClass}
          >
            {rooms.map((r) => (
              <option key={r.id} value={r.id}>
                {r.code} ({r.is_lab ? 'lab' : 'classroom'}, {r.capacity})
              </option>
            ))}
          </select>
        </div>
      </CardHeader>
      <CardContent className="overflow-x-auto pt-0">
        <table className="w-full min-w-[640px] border-collapse text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/60">
              <th className="p-2 text-left">Period</th>
              {grid.days.map((d) => (
                <th key={d} className="p-2 text-left">
                  {DAY_NAMES[d]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border/60">
            {grid.periods.map(({ period, teaching }) => (
              <tr key={period} className={teaching ? '' : 'bg-muted/30 text-muted-foreground'}>
                <td className="p-2 font-mono font-semibold">P{period}</td>
                {grid.days.map((day) => {
                  const here = inRoom.filter((o) => o.day === day && o.period === period);
                  return (
                    <td key={day} data-testid={`room-cell-${day}-${period}`} className="p-2 align-top">
                      {!teaching
                        ? 'Break'
                        : here.map((o, i) => (
                            <div key={i}>
                              {o.label}
                              {o.subRoomId && (
                                <span className="font-mono text-muted-foreground"> ({code.get(o.subRoomId)})</span>
                              )}
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
export const FreeRoomsPanel: React.FC<RoomViewsProps> = ({ edgeList, sessions }) => {
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
  const [day, setDay] = useState(0);
  const [period, setPeriod] = useState(grid.teachingPeriods[0] ?? 0);
  const occupancies = useMemo(() => roomOccupancies(sessions, edgeList), [sessions, edgeList]);
  const free = freeRoomsAt(edgeList, occupancies, day, period);

  return (
    <Card data-testid="free-rooms" className="border-border/60 bg-card/60">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base font-bold">
            <Search className="h-4 w-4 text-primary" /> Free Rooms
          </CardTitle>
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
                  P{p}
                </option>
              ))}
            </select>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {free.length === 0 ? (
          <p className="text-xs text-muted-foreground">No room is free at this time.</p>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {free.map((r) => (
              <li
                key={r.roomId}
                data-testid={`free-room-${r.code}`}
                className="flex flex-wrap items-center gap-2 rounded-md border border-border/50 bg-background/60 p-2"
              >
                <span className="font-mono font-bold">{r.code}</span>
                <Badge variant={r.isLab ? 'success' : 'outline'} className="text-[10px] py-0">
                  {r.isLab ? 'Lab' : 'Classroom'} · capacity {r.capacity}
                </Badge>
                {r.subRoomCount > 0 && (
                  <span data-testid={`batch-places-${r.code}`} className="text-muted-foreground">
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
