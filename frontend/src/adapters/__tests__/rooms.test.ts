import { describe, it, expect } from 'vitest';
import { freeRoomsAt, roomOccupancies } from '../rooms';
import { buildEnrichedSessions, getExampleEdgeList, getSolvedSolutionFixture } from '../timetable';

const edgeList = getExampleEdgeList();
const assignment = getSolvedSolutionFixture().assignment;
const occupancies = roomOccupancies(buildEnrichedSessions(assignment, edgeList), edgeList);
const codes = (day: number, period: number, occ = occupancies) =>
  freeRoomsAt(edgeList, occ, day, period).map((r) => r.code);

describe('room occupancy', () => {
  it('holds a 2-period lab sub-room for both teaching periods it occupies', () => {
    const lab = occupancies.filter((o) => o.sessionId === 'sess-0001');
    expect(lab).toEqual([
      expect.objectContaining({ roomId: 'room-702', subRoomId: 'room-702-a', day: 0, period: 1 }),
      expect.objectContaining({ roomId: 'room-702', subRoomId: 'room-702-a', day: 0, period: 3 }),
    ]);
  });

  it('counts pinned_occupancy rooms as held', () => {
    expect(occupancies).toContainEqual(
      expect.objectContaining({ roomId: 'room-508', subRoomId: null, day: 3, period: 4, label: 'Pinned' })
    );
  });
});

describe('free rooms', () => {
  it('lists only top-level rooms that are free, never sub-rooms', () => {
    // Monday P0: nothing is placed
    expect(codes(0, 0)).toEqual(['002', '508', '509 new CSE', '603', '608', '702']);
  });

  it('drops a room once all its sub-rooms are in use, and a room without sub-rooms once used', () => {
    // Monday P1: 702-A, 702-B, 603-2 and 608 hold the SE-Comp B lab block
    expect(codes(0, 1)).toEqual(['002', '508', '509 new CSE']);
    // ...and the block still holds them at P3, after the P2 break
    expect(codes(0, 3)).toEqual(['002', '508', '509 new CSE']);
    // Wednesday P3: 002 holds SE-Comp C OS; Thursday P4: 508 is pinned
    expect(codes(2, 3)).not.toContain('002');
    expect(codes(3, 4)).not.toContain('508');
  });

  it('lists a partly occupied lab with the batch places still free', () => {
    const without0002 = roomOccupancies(
      buildEnrichedSessions(assignment.filter((a) => a.session_id !== 'sess-0002'), edgeList),
      edgeList
    );
    const lab = freeRoomsAt(edgeList, without0002, 0, 1).find((r) => r.code === '702');
    expect(lab).toMatchObject({ isLab: true, freeSubRoomCodes: ['702-B'], subRoomCount: 2 });
  });

  it('a whole-room use locks every sub-room', () => {
    const whole = [{ roomId: 'room-702', subRoomId: null, day: 0, period: 0, label: 'x', sessionId: null }];
    expect(codes(0, 0, whole)).not.toContain('702');
  });
});
