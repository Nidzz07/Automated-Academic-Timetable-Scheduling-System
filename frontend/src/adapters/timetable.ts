/**
 * Edge-list / ingestion / solution contracts -> grid view models.
 *
 * The week (days, periods, breaks, lunch), rooms and pinned blocks come from the edge list
 * the solution was solved for; no period, time, break or label of the SPIT grid is
 * restated here. Periods are on the contract's wall-clock axis and shown as P0, P1, ...
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
  /** pins[i] describes pinned_occupancy[i] */
  pins: Array<{ kind: string; label: string; decision?: string }>;
}

/** What the UI shows for an instance's ids. */
export interface Labels {
  faculty(id: string): { initials: string; name: string };
  cohort(id: string): string;
  subject(id: string): { code: string; name: string } | undefined;
  room(room: { id: string; code: string }): string;
  /** Same cohort, or two cohorts that share students */
  overlap(a: string, b: string): boolean;
  /** Kind and label of pinned_occupancy[index]; undefined when the instance has no display sidecar */
  pin(index: number): Display['pins'][number] | undefined;
  /** "09:00–10:00", or null when the instance gives no clock times */
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

/** An instance's labels: from its display sidecar (D41), else the contract examples'. */
export function labelsFor(display: Display | null | undefined): Labels {
  if (!display) return EXAMPLE_LABELS;
  const clock = new Map(display.periods.map((p) => [p.period, `${p.start}–${p.end}`]));
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
    pin: (i) => display.pins[i],
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
