/**
 * Edge-list / ingestion / solution contracts -> grid view models.
 *
 * The week (days, periods, breaks, lunch), rooms and pinned blocks come from the edge list
 * the solution was solved for; no period, time, break or label of the SPIT grid is
 * restated here. Periods are on the contract's wall-clock axis and shown as T0, T1, ... (periodLabel)
 */

import {
  SolvedSolution,
  DayIndex,
  SessionAssignment,
  isSolvedSolution,
} from '@/adapters/solution';
import type { ChronosEdgeListContractV1 } from '@/types/generated/edge_list_v1.schema';
import type { ChronosIngestionContractV1 } from '@/types/generated/ingestion_v1.schema';
import solvedExample from '@contracts/examples/solution_v2.solved.example.json';
import edgeListExample from '@contracts/examples/edge_list_v1.example.json';
import ingestionExample from '@contracts/examples/ingestion_v1.example.json';
import { displayText, formatClockRange, periodLabel, periodSpan } from '@/lib/format';

export type EdgeList = ChronosEdgeListContractV1;
export type EdgeListSession = EdgeList['sessions'][number];

// shortcut: the contract examples' names come from the ingestion example; swap for API-served names at S13
// The bundled contract examples are schema-checked in contractValidation.test.ts, not at page
// load, so ajv stays off the main bundle; API payloads are still validated by the client
const ingestion = ingestionExample as ChronosIngestionContractV1;
const subjects = new Map(ingestion.subjects.map((s) => [s.id, s]));
const faculty = new Map(ingestion.faculty.map((f) => [f.id, f]));
const cohorts = new Map(ingestion.cohorts.map((c) => [c.id, c]));

/** Day names in contract day-index order (schema: Monday=0 .. Friday=4). */
export const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

/** "Wednesday T1" */
export const slotText = (day: number, period: number) => `${DAY_NAMES[day]} ${periodLabel(period)}`;

/** Cells in words, a day's consecutive periods as one run: "Tuesday T5–T9, Friday T0". */
export function slotsText(slots: Array<{ day: number; period: number }>): string {
  const byDay = new Map<number, number[]>();
  slots.forEach((s) => byDay.set(s.day, [...(byDay.get(s.day) ?? []), s.period]));
  return [...byDay]
    .flatMap(([day, periods]) => {
      const runs: Array<[number, number]> = [];
      [...new Set(periods)]
        .sort((a, b) => a - b)
        .forEach((p) => {
          const last = runs[runs.length - 1];
          if (last && p === last[1] + 1) last[1] = p;
          else runs.push([p, p]);
        });
      return runs.map(([a, b]) => `${DAY_NAMES[day]} ${periodSpan(a, b)}`);
    })
    .join(', ');
}

export interface WeekGrid {
  days: DayIndex[];
  /** Every wall-clock period of a day; `teaching: false` is a break for everyone. */
  periods: Array<{ period: number; teaching: boolean }>;
  /** Teaching periods in teaching order. */
  teachingPeriods: number[];
}

export function buildWeekGrid(edgeList: EdgeList): WeekGrid {
  const { days, periods_per_day, teaching_periods } = edgeList.slot_grid;
  return {
    days: Array.from({ length: days }, (_, d) => d),
    periods: Array.from({ length: periods_per_day }, (_, p) => ({
      period: p,
      teaching: teaching_periods.includes(p),
    })),
    teachingPeriods: [...teaching_periods].sort((a, b) => a - b),
  };
}

/** The periods a session starting at `start` occupies: `duration` periods in teaching order. */
export function occupiedPeriods(grid: WeekGrid, start: number, duration: number): number[] {
  const i = grid.teachingPeriods.indexOf(start);
  return i < 0 ? [start] : grid.teachingPeriods.slice(i, i + duration);
}

export function getFaculty(id: string) {
  const f = faculty.get(id);
  // ingestion_v1 allows null initials (UNRESOLVED_FACULTY_INITIALS); never guess them
  return f
    ? { initials: f.initials ?? 'Unresolved', name: f.full_name }
    : { initials: id.replace('fac-', '').toUpperCase(), name: 'Faculty' };
}

export function getCohortLabel(id: string): string {
  return cohorts.get(id)?.label ?? id.replace('coh-', '');
}

/** Same cohort, or two ingestion cohorts that share a batch (division ⊃ batch, combined ⊃ division). */
export function cohortsOverlap(a: string, b: string): boolean {
  if (a === b) return true;
  const ma = cohorts.get(a)?.member_batch_ids;
  const mb = cohorts.get(b)?.member_batch_ids;
  return !!ma && !!mb && ma.some((m) => mb.includes(m));
}

/**
 * D41 display sidecar (data/instances/<instance>/display.json, written by db/export_edge_list.py):
 * names, pin kinds and labels, and period clock times for one edge list. Not a contract.
 */
export interface Display {
  days: string[];
  periods: Array<{ period: number; start: string; end: string; teaching: boolean }>;
  faculty: Record<string, string>;
  /** Faculty initials per year ('SE', 'TE', or 'unscoped' for a manual mapping with no year) */
  initials: Record<string, Record<string, string[]>>;
  /** A batch's `label` is unique ("SE-Comp A batch A"); its `name` is only "A".."D" */
  cohorts: Record<string, { name: string; type: string; years: string[]; label?: string }>;
  /** Each division's batch ids */
  batches: Record<string, string[]>;
  rooms: Record<string, string>;
  subjects: Record<string, { code: string; name: string }>;
  /** pins[i] describes pinned_occupancy[i]; unique_label tells apart blocks that share a label */
  pins: Array<{ kind: string; label: string; decision?: string; unique_label?: string }>;
}

/** What the UI shows for an instance's ids. */
export interface Labels {
  faculty(id: string): { initials: string; name: string };
  cohort(id: string): string;
  subject(id: string): { code: string; name: string } | undefined;
  room(room: { id: string; code: string }): string;
  /** Same cohort, or two cohorts that share students */
  overlap(a: string, b: string): boolean;
  /**
   * Kind and label of pinned_occupancy[index]; ACCEPTED_ROOM_PIN past the sidecar's pins;
   * undefined when the instance has no display sidecar
   */
  pin(index: number): Display['pins'][number] | undefined;
  /** "9:00 AM – 10:00 AM", or null when the instance gives no clock times */
  clock(period: number): string | null;
}

/** The contract examples: names from the ingestion example, no pin kinds, no clock times. */
export const EXAMPLE_LABELS: Labels = {
  faculty: getFaculty,
  cohort: getCohortLabel,
  subject: (id) => subjects.get(id),
  room: (room) => room.code,
  overlap: cohortsOverlap,
  pin: () => undefined,
  clock: () => null,
};

/**
 * A pin past display.json's list. The current edge list and a job's edge list are the committed
 * one plus accepted changes; solver.repair.apply_change appends one pin per slot of a
 * room_unavailable change (D52), so display.json, written for the committed list, has none.
 */
export const ACCEPTED_ROOM_PIN: Display['pins'][number] = {
  kind: 'accepted change',
  label: 'Room made unavailable by an accepted change',
  decision: 'D52',
};

/** An instance's labels: from its display sidecar (D41), else the contract examples'. */
export function labelsFor(display: Display | null | undefined): Labels {
  if (!display) return EXAMPLE_LABELS;
  const clock = new Map(display.periods.map((p) => [p.period, formatClockRange(p.start, p.end)]));
  return {
    faculty: (id) => {
      // every initial the faculty is known by, across years; none is never guessed. Faculty who
      // teach no SE/TE session (only frozen BE/M.Tech items) have none: the name stands alone.
      const initials = [...new Set(Object.values(display.initials[id] ?? {}).flat())];
      return { initials: initials.join('/'), name: display.faculty[id] ?? id };
    },
    cohort: (id) => display.cohorts[id]?.label ?? display.cohorts[id]?.name ?? id,
    subject: (id) => display.subjects[id],
    room: (room) => display.rooms[room.id] ?? room.code,
    // a division and its batches share students; display.json gives elective groups no members
    overlap: (a, b) => a === b || !!display.batches[a]?.includes(b) || !!display.batches[b]?.includes(a),
    pin: (i) => display.pins[i] ?? ACCEPTED_ROOM_PIN,
    clock: (p) => clock.get(p) ?? null,
  };
}

/** Every cohort the edge list names (sessions and pinned occupancy), for filters. */
export function cohortOptions(
  edgeList: EdgeList,
  labels: Labels = EXAMPLE_LABELS
): Array<{ id: string; label: string }> {
  const ids = new Set([
    ...edgeList.sessions.map((s) => s.cohort_id),
    ...edgeList.pinned_occupancy.flatMap((p) => p.cohort_ids),
  ]);
  const options = [...ids].map((id) => ({ id, label: labels.cohort(id) }));
  // two cohorts with one display name (e.g. two "MDM-DBMS" groups): the id tells them apart
  return options
    .map((o) => (options.some((x) => x !== o && x.label === o.label) ? { ...o, label: `${o.label} (${o.id})` } : o))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/**
 * Enriched session item ready for rendering
 */
export interface EnrichedSession {
  sessionId: string;
  day: DayIndex;
  /** Start period on the wall-clock axis */
  wallClockPeriod: number;
  /** Every period the session occupies (start + duration-1 more in teaching order) */
  periods: number[];
  durationPeriods: number;
  roomId: string;
  subRoomId: string | null;
  roomCode: string;
  subRoomCode: string | null;
  subjectCode: string;
  subjectName: string;
  facultyId: string;
  facultyInitials: string;
  facultyName: string;
  cohortId: string;
  cohortLabel: string;
  cohortSize: number;
  sessionType: "theory" | "lab";
  isCombinedDivision: boolean;
  combinedCohortText?: string;
  isPinned: boolean;
  pinnedReason?: string;
  labBlockId?: string;
  batchLabel?: string;
}

/**
 * Unified parallel lab block representation
 */
export interface EnrichedLabBlock {
  blockId: string;
  day: DayIndex;
  /** Periods the block occupies, in teaching order */
  periods: number[];
  /** Non-teaching periods the block straddles (e.g. a break between its two periods) */
  spannedBreaks: number[];
  sessions: EnrichedSession[];
}

/**
 * One pinned_occupancy entry.
 */
export interface EnrichedPin {
  key: string;
  day: DayIndex;
  period: number;
  /**
   * From the display sidecar (lunch, frozen, exam, ...); null when the instance has none.
   * Never inferred from which cohorts, teachers or rooms the pin holds (D41).
   */
  kind: string | null;
  /** The display label: a year's lunch, a frozen item's name, an exam; null without a sidecar */
  label: string | null;
  /** The ROADMAP decision behind the pin (e.g. D24), when the sidecar names one */
  decision: string | null;
  cohortIds: string[];
  cohortLabels: string[];
  roomCodes: string[];
  facultyInitials: string[];
}

export function getExampleEdgeList(): EdgeList {
  return edgeListExample as unknown as EdgeList;
}

/**
 * Returns the solved solution example from contracts/examples (solution.v2)
 */
export function getSolvedSolutionFixture(): SolvedSolution {
  const solution = solvedExample as SolvedSolution;
  if (!isSolvedSolution(solution)) throw new Error('solution_v2.solved.example.json is not solved');
  return solution;
}

/**
 * Build enriched sessions from placements and the edge list they were solved for
 */
export function buildEnrichedSessions(
  assignment: SessionAssignment[],
  edgeList: EdgeList,
  labels: Labels = EXAMPLE_LABELS
): EnrichedSession[] {
  const grid = buildWeekGrid(edgeList);
  const rooms = new Map(edgeList.rooms.map((r) => [r.id, r]));
  const roomName = (id: string) => {
    const room = rooms.get(id);
    // '' is a printed room outside the edge list's room set (real baseline; D10, D29)
    return room ? labels.room(room) : id || 'Room not in edge list';
  };
  const edgeSessions = new Map(edgeList.sessions.map((s) => [s.id, s]));

  return assignment.map((item) => {
    const edgeSession = edgeSessions.get(item.session_id);
    const subject = labels.subject(edgeSession?.subject_id ?? '');
    const fac = labels.faculty(edgeSession?.faculty_id ?? '');
    const cohortId = edgeSession?.cohort_id ?? '';
    const cohortLabel = labels.cohort(cohortId);
    const labBlock = edgeList.lab_blocks.find((lb) => lb.session_ids.includes(item.session_id));

    const isCombined = cohorts.get(cohortId)?.cohort_type === 'combined' || cohortId.includes('comb');
    const isPinned = edgeSession?.fixed_slot !== null && edgeSession?.fixed_slot !== undefined;

    // Extract batch if batch cohort
    let batchLabel: string | undefined;
    if (cohortId.includes('batch')) {
      const parts = cohortId.split('-');
      batchLabel = `Batch ${parts[parts.length - 1].toUpperCase()}`;
    }

    const duration = edgeSession?.duration_periods ?? 1;
    const subRoomCode = item.sub_room_id ? roomName(item.sub_room_id) : null;

    return {
      sessionId: item.session_id,
      day: item.day,
      wallClockPeriod: item.period,
      periods: occupiedPeriods(grid, item.period, duration),
      durationPeriods: duration,
      roomId: item.room_id,
      subRoomId: item.sub_room_id,
      roomCode: subRoomCode ?? roomName(item.room_id),
      subRoomCode,
      subjectCode: subject?.code ?? (edgeSession?.subject_id ?? '').replace('subj-', '').toUpperCase(),
      subjectName: subject?.name ?? 'Subject',
      facultyId: edgeSession?.faculty_id ?? '',
      facultyInitials: fac.initials,
      facultyName: fac.name,
      cohortId,
      cohortLabel,
      cohortSize: edgeSession?.cohort_size ?? 0,
      sessionType: edgeSession?.session_type ?? "theory",
      isCombinedDivision: isCombined,
      combinedCohortText: isCombined ? `${cohortLabel} (${edgeSession?.cohort_size ?? 0} students)` : undefined,
      isPinned,
      pinnedReason: isPinned ? "Fixed slot in the edge list (fixed_slot)" : undefined,
      labBlockId: labBlock?.id,
      batchLabel,
    };
  });
}

/**
 * Returns grouped parallel lab blocks (all members of one edge-list lab block)
 */
export function buildEnrichedLabBlocks(sessions: EnrichedSession[]): EnrichedLabBlock[] {
  const blockMap = new Map<string, EnrichedSession[]>();
  sessions.forEach((sess) => {
    if (sess.labBlockId) blockMap.set(sess.labBlockId, [...(blockMap.get(sess.labBlockId) ?? []), sess]);
  });

  return [...blockMap].map(([blockId, blockSessions]) => {
    const { day, periods } = blockSessions[0];
    const spannedBreaks: number[] = [];
    for (let p = periods[0] + 1; p < periods[periods.length - 1]; p++) {
      if (!periods.includes(p)) spannedBreaks.push(p);
    }
    return { blockId, day, periods, spannedBreaks, sessions: blockSessions };
  });
}

/**
 * Returns the edge list's pinned_occupancy as grid view models
 */
export function buildPins(edgeList: EdgeList, labels: Labels = EXAMPLE_LABELS): EnrichedPin[] {
  const rooms = new Map(edgeList.rooms.map((r) => [r.id, r]));
  return edgeList.pinned_occupancy.map((p, i) => {
    const shown = labels.pin(i);
    return {
      key: `pin-${p.day}-${p.period}-${i}`,
      day: p.day,
      period: p.period,
      kind: shown?.kind ?? null,
      label: shown?.label ?? null,
      decision: shown?.decision ?? null,
      cohortIds: p.cohort_ids,
      cohortLabels: p.cohort_ids.map(labels.cohort),
      roomCodes: p.room_ids.map((id) => {
        const room = rooms.get(id);
        return room ? labels.room(room) : id;
      }),
      // faculty with no initials (they teach only frozen BE/M.Tech items) show their name
      facultyInitials: p.faculty_ids.map((id) => labels.faculty(id).initials || labels.faculty(id).name),
    };
  });
}

/** A teacher's weekly hours as the department counts them (CONTEXT §3.4 "6T+ 8P =14", D11). */
export interface FacultyLoad {
  theory: number;
  practical: number;
  total: number;
}

/** The load of these placed sessions: a lab session's periods are practical hours, any other's theory hours. */
export function facultyLoad(sessions: EnrichedSession[]): FacultyLoad {
  let theory = 0;
  let practical = 0;
  for (const s of sessions) {
    if (s.sessionType === 'lab') practical += s.durationPeriods;
    else theory += s.durationPeriods;
  }
  return { theory, practical, total: theory + practical };
}

/** "6T + 8P = 14" */
export const loadText = (load: FacultyLoad) => `${load.theory}T + ${load.practical}P = ${load.total}`;

/** One faculty member at a slot: free, or engaged with what (sessions by name, pins by label, "unavailable"). */
export interface FacultyAtSlot {
  facultyId: string;
  /** "Name (INITIALS)" */
  name: string;
  engagedWith: string[];
}

/**
 * Who is free and who is engaged at (day, period): every faculty member the edge list names, engaged
 * when a placed session occupies the period, a pinned_occupancy entry there holds them, or the
 * edge list makes them unavailable then. Read-only; the substitute finder is where to act.
 */
export function facultyAtSlot(
  edgeList: EdgeList,
  labels: Labels,
  sessions: EnrichedSession[],
  day: number,
  period: number
): { free: FacultyAtSlot[]; engaged: FacultyAtSlot[] } {
  const ids = new Set([
    ...edgeList.faculty_availability.map((f) => f.faculty_id),
    ...edgeList.sessions.map((s) => s.faculty_id),
    ...edgeList.pinned_occupancy.flatMap((p) => p.faculty_ids),
  ]);
  const engagedWith = new Map<string, string[]>();
  const add = (id: string, what: string) => engagedWith.set(id, [...(engagedWith.get(id) ?? []), what]);
  for (const s of sessions) {
    if (s.day === day && s.periods.includes(period)) add(s.facultyId, `${s.subjectCode} · ${s.cohortLabel} · ${s.roomCode}`);
  }
  edgeList.pinned_occupancy.forEach((p, i) => {
    if (p.day !== day || p.period !== period) return;
    for (const id of p.faculty_ids) add(id, labels.pin(i)?.label ?? 'Pinned occupancy');
  });
  for (const f of edgeList.faculty_availability) {
    if (f.unavailable_slots.some((s) => s.day === day && s.period === period)) add(f.faculty_id, 'unavailable');
  }
  const all = [...ids]
    .map((id) => ({ facultyId: id, name: facultyText(labels, id), engagedWith: engagedWith.get(id) ?? [] }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return { free: all.filter((f) => f.engagedWith.length === 0), engaged: all.filter((f) => f.engagedWith.length > 0) };
}

/** "Name (INITIALS)"; the name alone for faculty with no initials. */
export function facultyText(labels: Labels, id: string): string {
  const f = labels.faculty(id);
  return f.initials ? `${f.name} (${f.initials})` : f.name;
}

/** What the UI calls an id of the edge list: a session, room, faculty member or cohort; else the id. */
export function entityName(id: string, edgeList: EdgeList, labels: Labels = EXAMPLE_LABELS): string {
  const session = edgeList.sessions.find((s) => s.id === id);
  if (session) {
    const code = labels.subject(session.subject_id)?.code ?? session.subject_id;
    return `${code} · ${labels.cohort(session.cohort_id)} · ${facultyText(labels, session.faculty_id)}`;
  }
  const room = edgeList.rooms.find((r) => r.id === id);
  if (room) return `Room ${labels.room(room)}`;
  if (
    edgeList.faculty_availability.some((f) => f.faculty_id === id) ||
    edgeList.pinned_occupancy.some((p) => p.faculty_ids.includes(id))
  ) {
    return facultyText(labels, id);
  }
  const isCohort =
    edgeList.sessions.some((s) => s.cohort_id === id) || edgeList.pinned_occupancy.some((p) => p.cohort_ids.includes(id));
  return isCohort ? labels.cohort(id) : id;
}

/**
 * A diagnosis's `pin.<i>` by display.json pins[i] (D51): "unique_label (pin.<i>)"; null for any other id.
 * Past display.json's pins it is a room an accepted change made unavailable (ACCEPTED_ROOM_PIN).
 */
export function pinName(id: string, edgeList: EdgeList, labels: Labels): string | null {
  const i = id.match(/^pin\.(\d+)$/)?.[1];
  if (i === undefined) return null;
  const pin = edgeList.pinned_occupancy[Number(i)];
  const shown = labels.pin(Number(i));
  const name =
    shown?.unique_label ??
    shown?.label ??
    (pin ? `Pinned occupancy, ${slotText(pin.day, pin.period)}` : ACCEPTED_ROOM_PIN.label);
  // display.json's unique_label names its periods "Mon P0–P1"
  return `${displayText(name)} (${id})`;
}

/** What a dragged session would clash with at its target: in order room, teacher, cohort, fixed item, unavailability. */
export type ClashKind = 'room' | 'teacher' | 'cohort' | 'fixed' | 'unavailable';

export interface Clash {
  kind: ClashKind;
  /** "Room 605 is taken at Wednesday T0 by PCS / A / DN / 605." */
  text: string;
}

export interface MoveCheck {
  /** "Clashes for CE207 (SE-Comp A) at Wednesday T0:", or why the session cannot go there at all */
  heading: string;
  /** Every clash at the target; empty when the heading already says why */
  clashes: Clash[];
}

const CLASH_ORDER: ClashKind[] = ['room', 'teacher', 'cohort', 'fixed', 'unavailable'];

/**
 * Why moving a placed session to (day, period) in its own room breaks a hard rule, in words; null
 * when it breaks none of these: fixed slot, teaching periods, and at the target every clash with
 * placed sessions (room, teacher, shared students), pinned occupancy (a fixed item, named by its
 * display label; one holding the room is a room clash) and faculty unavailability. Only decides
 * whether to offer a repair: the backend's repair is the judge.
 */
export function checkMove(
  edgeList: EdgeList,
  labels: Labels,
  sessions: EnrichedSession[],
  sessionId: string,
  day: number,
  period: number
): MoveCheck | null {
  const session = edgeList.sessions.find((s) => s.id === sessionId);
  const placed = sessions.find((s) => s.sessionId === sessionId);
  const refuse = (heading: string): MoveCheck => ({ heading, clashes: [] });
  if (!session || !placed) return refuse(`Session '${sessionId}' is not in this timetable.`);
  const name = `${placed.subjectCode} (${placed.cohortLabel})`;
  if (session.fixed_slot) return refuse(`${name} is fixed to its slot.`);
  const grid = buildWeekGrid(edgeList);
  const periods = occupiedPeriods(grid, period, session.duration_periods);
  if (!grid.teachingPeriods.includes(period) || periods.length < session.duration_periods) {
    return refuse(`${name} does not fit at ${slotText(day, period)}.`);
  }
  const at = (d: number, p: number) => d === day && periods.includes(p);
  const where = (p: number) => slotText(day, p);
  const teacher = facultyText(labels, session.faculty_id);
  const roomTaken = (p: number, by: string) => `Room ${placed.roomCode} is taken at ${where(p)} by ${by}.`;

  const found: Clash[] = [];
  const add = (kind: ClashKind, text: string) => {
    if (!found.some((c) => c.kind === kind && c.text === text)) found.push({ kind, text });
  };

  // a room in use locks its sub-rooms and a sub-room in use locks the room (ROOM_OCCUPANCY)
  const parentOf = new Map(edgeList.rooms.map((r) => [r.id, r.parent_room_id]));
  const holdsRoom = (id: string) =>
    id === placed.roomId || id === placed.subRoomId || (parentOf.get(id) === placed.roomId && !placed.subRoomId);
  for (const other of sessions) {
    if (other.sessionId === sessionId || other.day !== day) continue;
    const shared = other.periods.find((p) => periods.includes(p));
    if (shared === undefined) continue;
    const what = `${other.subjectCode} · ${other.cohortLabel}`;
    if (other.roomId === placed.roomId && (!other.subRoomId || !placed.subRoomId || other.subRoomId === placed.subRoomId)) {
      add('room', roomTaken(shared, what));
    }
    if (other.facultyId === session.faculty_id) add('teacher', `${teacher} teaches ${what} then.`);
    if (labels.overlap(other.cohortId, session.cohort_id)) add('cohort', `${placed.cohortLabel} has ${what} then.`);
  }

  edgeList.pinned_occupancy.forEach((p, i) => {
    if (!at(p.day, p.period)) return;
    const label = labels.pin(i)?.label ?? 'pinned occupancy';
    if (p.room_ids.some(holdsRoom)) add('room', roomTaken(p.period, label));
    const holds = [
      ...(p.faculty_ids.includes(session.faculty_id) ? [teacher] : []),
      ...(p.cohort_ids.some((c) => labels.overlap(c, session.cohort_id)) ? [placed.cohortLabel] : []),
    ];
    if (holds.length) add('fixed', `${label} holds ${holds.join(' and ')} then.`);
  });

  const blackout = edgeList.faculty_availability
    .find((f) => f.faculty_id === session.faculty_id)
    ?.unavailable_slots.some((s) => at(s.day, s.period));
  if (blackout) add('unavailable', `${teacher} is unavailable then.`);

  if (found.length === 0) return null;
  const span = `${DAY_NAMES[day]} ${periodSpan(periods[0], periods[periods.length - 1])}`;
  return {
    heading: `Clashes for ${name} at ${span}:`,
    clashes: [...found].sort((a, b) => CLASH_ORDER.indexOf(a.kind) - CLASH_ORDER.indexOf(b.kind)),
  };
}

/** checkMove as one line: the heading and every clash; null when there is none. */
export function moveConflict(
  edgeList: EdgeList,
  labels: Labels,
  sessions: EnrichedSession[],
  sessionId: string,
  day: number,
  period: number
): string | null {
  const check = checkMove(edgeList, labels, sessions, sessionId, day, period);
  return check && [check.heading, ...check.clashes.map((c) => c.text)].join(' ');
}
