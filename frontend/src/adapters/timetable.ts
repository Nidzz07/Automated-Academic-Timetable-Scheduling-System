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
  parseSolution,
  isSolvedSolution,
} from '@/adapters/solution';
import { validateContract } from '@/api/contractValidation';
import type { ChronosEdgeListContractV1 } from '@/types/generated/edge_list_v1.schema';
import solvedExample from '@contracts/examples/solution_v2.solved.example.json';
import edgeListExample from '@contracts/examples/edge_list_v1.example.json';
import ingestionExample from '@contracts/examples/ingestion_v1.example.json';

export type EdgeList = ChronosEdgeListContractV1;
export type EdgeListSession = EdgeList['sessions'][number];

// shortcut: names and labels come from the ingestion example; swap for API-served ingestion data at S13
const ingestion = validateContract('ingestion', ingestionExample);
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

/** Every cohort the edge list names (sessions and pinned occupancy), for filters. */
export function cohortOptions(edgeList: EdgeList): Array<{ id: string; label: string }> {
  const ids = new Set([
    ...edgeList.sessions.map((s) => s.cohort_id),
    ...edgeList.pinned_occupancy.flatMap((p) => p.cohort_ids),
  ]);
  return [...ids]
    .map((id) => ({ id, label: getCohortLabel(id) }))
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
   * Holds cohorts only, no teacher and no room. A frozen item holds its teacher and room too
   * (D24), so this is a year's lunch, pinned per division cohort (D6, D31).
   * shortcut: edge_list_v1 pins carry no kind; switch to the kind once a contract carries it.
   */
  isLunch: boolean;
  cohortIds: string[];
  cohortLabels: string[];
  roomCodes: string[];
  facultyInitials: string[];
}

export function getExampleEdgeList(): EdgeList {
  return validateContract('edge_list', edgeListExample);
}

/**
 * Returns the solved solution example from contracts/examples (solution.v2)
 */
export function getSolvedSolutionFixture(): SolvedSolution {
  const solution = parseSolution(solvedExample);
  if (!isSolvedSolution(solution)) throw new Error('solution_v2.solved.example.json is not solved');
  return solution;
}

/**
 * Build enriched sessions from placements and the edge list they were solved for
 */
export function buildEnrichedSessions(
  assignment: SessionAssignment[],
  edgeList: EdgeList
): EnrichedSession[] {
  const grid = buildWeekGrid(edgeList);
  const rooms = new Map(edgeList.rooms.map((r) => [r.id, r]));
  const edgeSessions = new Map(edgeList.sessions.map((s) => [s.id, s]));

  return assignment.map((item) => {
    const edgeSession = edgeSessions.get(item.session_id);
    const subject = subjects.get(edgeSession?.subject_id ?? '');
    const fac = getFaculty(edgeSession?.faculty_id ?? '');
    const cohortId = edgeSession?.cohort_id ?? '';
    const cohortLabel = getCohortLabel(cohortId);
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
    const subRoomCode = item.sub_room_id ? rooms.get(item.sub_room_id)?.code ?? item.sub_room_id : null;

    return {
      sessionId: item.session_id,
      day: item.day,
      wallClockPeriod: item.period,
      periods: occupiedPeriods(grid, item.period, duration),
      durationPeriods: duration,
      roomId: item.room_id,
      subRoomId: item.sub_room_id,
      roomCode: subRoomCode ?? rooms.get(item.room_id)?.code ?? item.room_id,
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
export function buildPins(edgeList: EdgeList): EnrichedPin[] {
  const rooms = new Map(edgeList.rooms.map((r) => [r.id, r.code]));
  return edgeList.pinned_occupancy.map((p, i) => ({
    key: `pin-${p.day}-${p.period}-${i}`,
    day: p.day,
    period: p.period,
    isLunch: p.faculty_ids.length === 0 && p.room_ids.length === 0 && p.cohort_ids.length > 0,
    cohortIds: p.cohort_ids,
    cohortLabels: p.cohort_ids.map(getCohortLabel),
    roomCodes: p.room_ids.map((id) => rooms.get(id) ?? id),
    facultyInitials: p.faculty_ids.map((id) => getFaculty(id).initials),
  }));
}
