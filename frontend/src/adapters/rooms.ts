/**
 * Room timetable and free-room views (ROADMAP D15).
 *
 * Rooms and sub-rooms come from the edge list; occupancy comes from the solution's placements
 * (every period each session occupies) plus the edge list's pinned_occupancy. Nothing is
 * scheduled or scored here: this only reads where the solver put things.
 */

import {
  EXAMPLE_LABELS,
  pinWithTeachers,
  sessionTeacher,
  type EdgeList,
  type EnrichedSession,
  type Labels,
} from '@/adapters/timetable';

/** One room or sub-room held in one cell. */
export interface Occupancy {
  /** Top-level room */
  roomId: string;
  /** Sub-room within roomId; null when the whole room is held */
  subRoomId: string | null;
  day: number;
  period: number;
  label: string;
  sessionId: string | null;
}

export function roomOccupancies(
  sessions: EnrichedSession[],
  edgeList: EdgeList,
  labels: Labels = EXAMPLE_LABELS
): Occupancy[] {
  const parentOf = new Map(edgeList.rooms.map((r) => [r.id, r.parent_room_id]));
  const placed = sessions.flatMap((s) =>
    s.periods.map((period) => ({
      roomId: s.roomId,
      subRoomId: s.subRoomId,
      day: s.day,
      period,
      label: `${s.subjectCode} · ${s.cohortLabel} · ${sessionTeacher(s)}`,
      sessionId: s.sessionId,
    }))
  );
  const pinned = edgeList.pinned_occupancy.flatMap((p, i) =>
    p.room_ids.map((id) => {
      const parent = parentOf.get(id) ?? null;
      return {
        roomId: parent ?? id,
        subRoomId: parent ? id : null,
        day: p.day,
        period: p.period,
        label: pinWithTeachers(labels.pin(i)?.label ?? 'Fixed item', p.faculty_ids, labels),
        sessionId: null,
      };
    })
  );
  return [...placed, ...pinned];
}

export interface FreeRoom {
  roomId: string;
  code: string;
  isLab: boolean;
  capacity: number;
  /** Sub-rooms (batch places) not in use; empty for a room without sub-rooms */
  freeSubRoomCodes: string[];
  subRoomCount: number;
}

/**
 * Rooms with room to spare at one cell. A whole-room use locks every sub-room and any
 * sub-room in use locks the whole room (ROOM_OCCUPANCY), so a room with sub-rooms is
 * listed while at least one sub-room is free, with the free ones named.
 */
export function freeRoomsAt(
  edgeList: EdgeList,
  occupancies: Occupancy[],
  day: number,
  period: number,
  labels: Labels = EXAMPLE_LABELS
): FreeRoom[] {
  const here = occupancies.filter((o) => o.day === day && o.period === period);
  return edgeList.rooms
    .filter((r) => r.parent_room_id === null)
    .flatMap((room) => {
      const subRooms = edgeList.rooms.filter((s) => s.parent_room_id === room.id);
      const used = here.filter((o) => o.roomId === room.id);
      if (used.some((o) => o.subRoomId === null)) return [];
      const free = subRooms.filter((s) => !used.some((o) => o.subRoomId === s.id));
      if (subRooms.length > 0 ? free.length === 0 : used.length > 0) return [];
      return [
        {
          roomId: room.id,
          code: labels.room(room),
          isLab: room.is_lab,
          capacity: room.capacity,
          freeSubRoomCodes: free.map((s) => labels.room(s)),
          subRoomCount: subRooms.length,
        },
      ];
    });
}
