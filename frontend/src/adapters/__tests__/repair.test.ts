import { describe, it, expect, beforeAll } from 'vitest';
import { MockChronosApiClient, REAL_INSTANCE } from '@/api/chronosApi';
import { SolvedSolution, isSolvedSolution, repairChanges } from '@/adapters/solution';
import { displayText } from '@/lib/format';
import {
  Display,
  EdgeList,
  EnrichedSession,
  Labels,
  DAY_NAMES,
  buildEnrichedSessions,
  checkMove,
  entityName,
  facultyText,
  labelsFor,
  pinName,
} from '@/adapters/timetable';

import solverPinRule from './solver_pin_rule.even-2025-26.json';

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
    // display.json keeps its P-label; the UI shows T4 (displayText)
    expect(pinName('pin.0', edgeList, labels)).toBe('TE lunch, Mon T4');
    const last = edgeList.pinned_occupancy.length - 1;
    expect(pinName(`pin.${last}`, edgeList, labels)).toBe(displayText(display.pins[last].unique_label!));
    expect(pinName(`pin.${last + 1}`, edgeList, labels)).toBe('Room made unavailable by an accepted change');
    // the current edge list carries the accepted closure's pin; display.json still stops at `last`
    const current = { ...edgeList, pinned_occupancy: [...edgeList.pinned_occupancy, { day: 0, period: 1, faculty_ids: [], room_ids: ['room-603'], cohort_ids: [] }] };
    expect(pinName(`pin.${last + 1}`, current, labels)).toBe('Room made unavailable by an accepted change');
    expect(pinName('unavailable.fac-swapnali-kurhade.0', edgeList, labels)).toBeNull();
  });
});

describe('checkMove refuses what the solver refuses at a fixed item (solver/graph.py slot_is_open)', () => {
  /**
   * For a sample of slots fixed items hold: every session the solver's own slot_is_open closes
   * there, over every period the session would occupy. Read from solver/graph.py, not from this
   * project's TypeScript, so the test does not trust the code it checks. Regenerate from the
   * repository root when the committed instance changes:
   *   python -c "import json; from solver.graph import build_conflict_graph as b, slot_is_open as o; d='data/instances/even-2025-26/'; e=json.load(open(d+'edge_list.json')); g=b(e); t=sorted(e['slot_grid']['teaching_periods']); S=sorted({(p['day'],p['period']) for p in [p for p in e['pinned_occupancy'] if p['period'] in t][::14]}); print(json.dumps([{'day':a,'period':p,'closed':sorted(i for i,s in g.sessions.items() if s.fixed_slot is None and len(t[t.index(p):t.index(p)+s.duration_periods])==s.duration_periods and not all(o(g,s,g.grid.slot(a,q)) for q in t[t.index(p):t.index(p)+s.duration_periods]))} for a,p in S],indent=1))"
   */
  const held = (s: { id: string }, slot: { day: number; period: number }) =>
    checkMove(edgeList, labels, sessions, s.id, slot.day, slot.period)?.clashes.some((c) => c.kind === 'fixed' || c.kind === 'unavailable') ?? false;
  const movable = () =>
    edgeList.sessions.filter((s) => !s.fixed_slot && sessions.some((p) => p.sessionId === s.id));
  const fits = (s: { id: string; duration_periods: number }, period: number) => {
    const teaching = [...edgeList.slot_grid.teaching_periods].sort((a, b) => a - b);
    return teaching.indexOf(period) + s.duration_periods <= teaching.length;
  };

  it('for every session at a sample of fixed items: exactly the same refusals', () => {
    expect(solverPinRule.length).toBeGreaterThanOrEqual(15);
    let refused = 0;
    let compared = 0;
    for (const slot of solverPinRule) {
      for (const s of movable()) {
        if (!fits(s, slot.period)) continue;
        compared += 1;
        const closed = slot.closed.includes(s.id);
        if (closed) refused += 1;
        expect(`${s.id} at ${slot.day}-${slot.period}: ${held(s, slot)}`).toBe(`${s.id} at ${slot.day}-${slot.period}: ${closed}`);
      }
    }
    // not an empty comparison: both answers occur
    expect(refused).toBeGreaterThan(100);
    expect(compared - refused).toBeGreaterThan(100);
  });

  it('a pin that names a parent or child cohort alone does not hold a session; the solver agrees', () => {
    const overlapOnly = solverPinRule.flatMap((slot) =>
      movable().flatMap((s) => {
        const pins = edgeList.pinned_occupancy.filter((p) => p.day === slot.day && p.period === slot.period);
        const parentOrChild = pins.some((p) => p.cohort_ids.some((c) => c !== s.cohort_id && labels.overlap(c, s.cohort_id)));
        const named = pins.some((p) => p.cohort_ids.includes(s.cohort_id) || p.faculty_ids.includes(s.faculty_id));
        return parentOrChild && !named && s.duration_periods === 1 && fits(s, slot.period) ? [{ s, slot }] : [];
      })
    );
    for (const { s, slot } of overlapOnly) {
      expect(slot.closed.includes(s.id)).toBe(held(s, slot));
    }
    // the batch sessions the old rule wrongly refused, on the whole committed instance
    const wronglyRefused = movable().filter((s) =>
      [0, 1, 2, 3, 4].some((day) =>
        edgeList.slot_grid.teaching_periods.some((period) => {
          if (!fits(s, period)) return false;
          const pins = edgeList.pinned_occupancy.filter((p) => p.day === day && p.period === period);
          return (
            pins.some((p) => p.cohort_ids.some((c) => labels.overlap(c, s.cohort_id))) &&
            !pins.some((p) => p.cohort_ids.includes(s.cohort_id) || p.faculty_ids.includes(s.faculty_id)) &&
            !checkMove(edgeList, labels, sessions, s.id, day, period)?.clashes.some((c) => c.kind === 'fixed')
          );
        })
      )
    );
    expect(wronglyRefused.length).toBeGreaterThan(0);
  });
});

describe('checkMove on the real instance: every clash at the target and its kind', () => {
  const NIMKAR_SE_A = 'obs-t0-r1-c3-l0'; // CE207 · SE-Comp A, Anant Nimkar (AVN), room 605
  const check = (s: EnrichedSession, day: number, period: number) =>
    checkMove(edgeList, labels, sessions, s.sessionId, day, period);
  const free = (s: EnrichedSession) =>
    [0, 1, 2, 3, 4].flatMap((day) => [0, 1, 3, 4, 5, 6, 7, 8, 9].map((period) => ({ day, period }))).find(
      ({ day, period }) => check(s, day, period) === null
    );

  it('finds no conflict for a move into a free slot of the committed timetable', () => {
    const s = sessions.find(theory)!;
    expect(free(s)).toBeDefined();
  });

  it('a slot with two clashes names both: a fixed item in the room and the teacher elsewhere', () => {
    const s = sessions.find((x) => x.sessionId === NIMKAR_SE_A)!;
    expect(check(s, 2, 1)).toEqual({
      heading: 'Clashes for CE207 (SE-Comp A) at Wednesday T1:',
      clashes: [
        { kind: 'room', text: 'Room 605 is taken at Wednesday T1 by PCS / A / DN / 605, Deepak Nair (DN).' },
        { kind: 'teacher', text: 'Anant Nimkar (AVN) teaches CE207 · SE-Comp B then.' },
      ],
    });
  });

  it('room: a placed session in the room', () => {
    const s = sessions.find((x) => x.sessionId === NIMKAR_SE_A)!;
    const other = sessions.find((o) => o.sessionId !== s.sessionId && o.roomId === s.roomId && o.cohortId !== s.cohortId && theory(o))!;
    expect(check(s, other.day, other.wallClockPeriod)?.clashes).toContainEqual({
      kind: 'room',
      text: `Room 605 is taken at ${DAY_NAMES[other.day]} T${other.wallClockPeriod} by ${other.subjectCode} · ${other.cohortLabel}.`,
    });
  });

  it('cohort: the session already there for the same students', () => {
    const s = sessions.find(theory)!;
    const other = sessions.find(
      (o) => o.sessionId !== s.sessionId && o.cohortId === s.cohortId && o.facultyId !== s.facultyId && o.roomId !== s.roomId
    )!;
    expect(check(s, other.day, other.wallClockPeriod)?.clashes).toContainEqual({
      kind: 'cohort',
      text: `${s.cohortLabel} has ${other.subjectCode} · ${other.cohortLabel} then.`,
    });
  });

  it('fixed item: a lunch pin by its label, beside the room clash at the same slot', () => {
    const s = sessions.find((x) => theory(x) && x.cohortId === 'coh-se-a')!;
    const inRoom = sessions.find((o) => o.day === 0 && o.periods.includes(5) && o.roomId === s.roomId)!;
    expect(check(s, 0, 5)).toEqual({
      heading: `Clashes for ${s.subjectCode} (SE-Comp A) at Monday T5:`,
      clashes: [
        { kind: 'room', text: `Room ${s.roomCode} is taken at Monday T5 by ${inRoom.subjectCode} · ${inRoom.cohortLabel}.` },
        { kind: 'fixed', text: 'SE lunch holds SE-Comp A then.' },
      ],
    });
  });

  it('unavailability, and a break or a fixed session refused outright', () => {
    const kurhade = sessions.find((x) => theory(x) && x.facultyId === KURHADE)!;
    expect(check(kurhade, 0, 0)?.clashes).toContainEqual({ kind: 'unavailable', text: 'Swapnali Kurhade (SK) is unavailable then.' });

    const s = sessions.find(theory)!;
    expect(check(s, 0, 2)).toEqual({ heading: `${s.subjectCode} (${s.cohortLabel}) does not fit at Monday T2.`, clashes: [] });
    const fixed: EdgeList = {
      ...edgeList,
      sessions: edgeList.sessions.map((x) =>
        x.id === s.sessionId ? { ...x, fixed_slot: { day: s.day, period: s.wallClockPeriod } } : x
      ),
    };
    expect(checkMove(fixed, labels, sessions, s.sessionId, 4, 9)?.heading).toMatch(/is fixed to its slot/);
  });

  it('teacher: another session of the same teacher; clashes come in the order room, teacher, cohort, fixed item, unavailability', () => {
    const order = ['room', 'teacher', 'cohort', 'fixed', 'unavailable'];
    for (const s of sessions.filter(theory).slice(0, 20)) {
      for (const day of [0, 1, 2, 3, 4]) {
        for (const period of [0, 1, 3, 4, 5, 6, 7, 8, 9]) {
          const kinds = check(s, day, period)?.clashes.map((c) => order.indexOf(c.kind)) ?? [];
          expect(kinds).toEqual([...kinds].sort((a, b) => a - b));
        }
      }
    }
    const s = sessions.find((x) => theory(x) && x.cohortId === 'coh-se-a')!;
    const busy = sessions.find((o) => o.sessionId !== s.sessionId && o.facultyId === s.facultyId)!;
    expect(check(s, busy.day, busy.wallClockPeriod)?.clashes).toContainEqual({
      kind: 'teacher',
      text: `${facultyText(labels, s.facultyId)} teaches ${busy.subjectCode} · ${busy.cohortLabel} then.`,
    });
  });
});
