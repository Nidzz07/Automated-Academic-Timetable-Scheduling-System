import { describe, it, expect, beforeAll } from 'vitest';
import { MockChronosApiClient, REAL_INSTANCE } from '@/api/chronosApi';
import { SolvedSolution, isSolvedSolution, repairChanges } from '@/adapters/solution';
import {
  Display,
  EdgeList,
  EnrichedSession,
  Labels,
  buildEnrichedSessions,
  entityName,
  labelsFor,
  moveConflict,
  pinName,
} from '@/adapters/timetable';

// The real EVEN instance (S9 export, D41 display.json) and its committed solution
let edgeList: EdgeList;
let display: Display;
let labels: Labels;
let solution: SolvedSolution;
let sessions: EnrichedSession[];
beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  display = (await files.getDisplay(REAL_INSTANCE))!;
  labels = labelsFor(display);
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  sessions = buildEnrichedSessions(solution.assignment, edgeList, labels);
});

const KURHADE = 'fac-swapnali-kurhade'; // D36: unavailable all Monday in the edge list
const theory = (s: EnrichedSession) => !s.labBlockId && s.durationPeriods === 1;

describe('repairChanges (D48)', () => {
  it('takes slot changes from displaced and finds room-only changes by comparing with the base', () => {
    const [a] = solution.assignment;
    const b = solution.assignment.find((x) => x !== a && x.room_id !== 'room-605')!;
    const result: SolvedSolution = {
      ...solution,
      assignment: solution.assignment.map((x) =>
        x === a ? { ...x, day: (x.day + 1) % 5 } : x === b ? { ...x, room_id: 'room-605', sub_room_id: null } : x
      ),
      displaced: [a.session_id],
    };
    const changes = repairChanges(solution, result);
    expect(changes.map((c) => [c.sessionId, c.slotChanged])).toEqual([
      [a.session_id, true],
      [b.session_id, false],
    ]);
    expect(changes[1].before.room_id).toBe(b.room_id);
    expect(changes[1].after.room_id).toBe('room-605');
    expect(repairChanges(solution, solution)).toEqual([]);
  });
});

describe('entityName and pinName on the real instance (display.json)', () => {
  it('names faculty "Name (INITIALS)", cohorts, rooms and sessions; an unknown id stays an id', () => {
    expect(entityName(KURHADE, edgeList, labels)).toBe('Swapnali Kurhade (SK)');
    expect(entityName('coh-se-a', edgeList, labels)).toBe('SE-Comp A');
    expect(entityName('room-603', edgeList, labels)).toBe('Room 603');
    const s = edgeList.sessions[0];
    expect(entityName(s.id, edgeList, labels)).toBe(
      `${display.subjects[s.subject_id].code} · ${labels.cohort(s.cohort_id)} · ${entityName(s.faculty_id, edgeList, labels)}`
    );
    expect(entityName('no-such-id', edgeList, labels)).toBe('no-such-id');
  });

  it('names pin.<i> by display.json pins[i] (D51); past the edge list a pin is an accepted room unavailability', () => {
    expect(display.pins[0].unique_label).toBe('TE lunch, Mon P4');
    expect(pinName('pin.0', edgeList, labels)).toBe('TE lunch, Mon P4 (pin.0)');
    const last = edgeList.pinned_occupancy.length - 1;
    expect(pinName(`pin.${last}`, edgeList, labels)).toBe(`${display.pins[last].unique_label} (pin.${last})`);
    expect(pinName(`pin.${last + 1}`, edgeList, labels)).toBe(`Room made unavailable by an accepted change (pin.${last + 1})`);
    // the current edge list carries the accepted closure's pin; display.json still stops at `last`
    const current = { ...edgeList, pinned_occupancy: [...edgeList.pinned_occupancy, { day: 0, period: 1, faculty_ids: [], room_ids: ['room-603'], cohort_ids: [] }] };
    expect(pinName(`pin.${last + 1}`, current, labels)).toBe(`Room made unavailable by an accepted change (pin.${last + 1})`);
    expect(pinName('unavailable.fac-swapnali-kurhade.0', edgeList, labels)).toBeNull();
  });
});

describe('moveConflict on the real instance', () => {
  const free = (s: EnrichedSession) =>
    [0, 1, 2, 3, 4].flatMap((day) => [0, 1, 3, 4, 5, 6, 7, 8, 9].map((period) => ({ day, period }))).find(
      ({ day, period }) => moveConflict(edgeList, labels, sessions, s.sessionId, day, period) === null
    );

  it('finds no conflict for a move into a free slot of the committed timetable', () => {
    const s = sessions.find(theory)!;
    expect(free(s)).toBeDefined();
  });

  it('names a cohort clash with the session already there', () => {
    const s = sessions.find(theory)!;
    const other = sessions.find(
      (o) => o.sessionId !== s.sessionId && o.cohortId === s.cohortId && o.facultyId !== s.facultyId && o.roomId !== s.roomId
    )!;
    expect(moveConflict(edgeList, labels, sessions, s.sessionId, other.day, other.wallClockPeriod)).toMatch(
      new RegExp(`^Cohort clash: ${s.cohortLabel} already has ${other.subjectCode}`)
    );
  });

  it('names a faculty clash, a lunch pin by unique_label, a break and faculty unavailability', () => {
    const s = sessions.find((x) => theory(x) && x.cohortId === 'coh-se-a')!;
    const lunch = moveConflict(edgeList, labels, sessions, s.sessionId, 0, 5);
    expect(lunch).toBe('Slot conflict: Monday P5 is held by SE lunch, Mon P5.');
    expect(moveConflict(edgeList, labels, sessions, s.sessionId, 0, 2)).toMatch(/does not fit at Monday P2/);

    const kurhade = sessions.find((x) => theory(x) && x.facultyId === KURHADE)!;
    expect(moveConflict(edgeList, labels, sessions, kurhade.sessionId, 0, 0)).toBe(
      'Swapnali Kurhade (SK) is unavailable on Monday P0.'
    );

    const busy = sessions.find((o) => o.sessionId !== s.sessionId && o.facultyId === s.facultyId)!;
    expect(moveConflict(edgeList, labels, sessions, s.sessionId, busy.day, busy.wallClockPeriod)).toMatch(/^Faculty clash: /);
  });

  it('refuses a fixed session', () => {
    const s = sessions.find(theory)!;
    const fixed: EdgeList = {
      ...edgeList,
      sessions: edgeList.sessions.map((x) =>
        x.id === s.sessionId ? { ...x, fixed_slot: { day: s.day, period: s.wallClockPeriod } } : x
      ),
    };
    expect(moveConflict(fixed, labels, sessions, s.sessionId, 4, 9)).toMatch(/is fixed to its slot/);
  });
});
