import { SolvedSolution, DayIndex, PeriodIndex, SessionAssignment } from '@/types/solution';
import solvedFixture from '@/fixtures/solution_v1.solved.example.json';
import edgeListFixture from '@/fixtures/edge_list_v1.example.json';
import ingestionFixture from '@/fixtures/ingestion_v1.example.json';

export interface PeriodSlot {
  /** Teaching period index: 0..7 */
  teachingPeriod: number;
  /** Wall-clock period index matching contract: 0, 1, 3, 4, 6, 7, 8, 9 */
  wallClockPeriod: number;
  /** Time range label */
  timeLabel: string;
  /** Wall-clock start and end */
  startTime: string;
  endTime: string;
  /** Whether there is a break preceding this period */
  precedingBreak?: {
    label: string;
    time: string;
  };
}

export const TEACHING_PERIODS: PeriodSlot[] = [
  {
    teachingPeriod: 0,
    wallClockPeriod: 0,
    timeLabel: "09:00 – 10:00",
    startTime: "09:00",
    endTime: "10:00",
  },
  {
    teachingPeriod: 1,
    wallClockPeriod: 1,
    timeLabel: "10:00 – 11:00",
    startTime: "10:00",
    endTime: "11:00",
  },
  {
    teachingPeriod: 2,
    wallClockPeriod: 3,
    timeLabel: "11:15 – 12:15",
    startTime: "11:15",
    endTime: "12:15",
    precedingBreak: {
      label: "Short Break",
      time: "11:00 – 11:15",
    },
  },
  {
    teachingPeriod: 3,
    wallClockPeriod: 4,
    timeLabel: "12:15 – 13:15",
    startTime: "12:15",
    endTime: "13:15",
  },
  {
    teachingPeriod: 4,
    wallClockPeriod: 6,
    timeLabel: "14:15 – 15:15",
    startTime: "14:15",
    endTime: "15:15",
    precedingBreak: {
      label: "Lunch Break",
      time: "13:15 – 14:15",
    },
  },
  {
    teachingPeriod: 5,
    wallClockPeriod: 7,
    timeLabel: "15:15 – 16:15",
    startTime: "15:15",
    endTime: "16:15",
  },
  {
    teachingPeriod: 6,
    wallClockPeriod: 8,
    timeLabel: "16:15 – 17:15",
    startTime: "16:15",
    endTime: "17:15",
  },
  {
    teachingPeriod: 7,
    wallClockPeriod: 9,
    timeLabel: "17:15 – 18:15",
    startTime: "17:15",
    endTime: "18:15",
  },
];

export const DAYS: Array<{ day: DayIndex; label: string; short: string }> = [
  { day: 0, label: "Monday", short: "Mon" },
  { day: 1, label: "Tuesday", short: "Tue" },
  { day: 2, label: "Wednesday", short: "Wed" },
  { day: 3, label: "Thursday", short: "Thu" },
  { day: 4, label: "Friday", short: "Fri" },
];

/**
 * Maps wall-clock period to teaching period index (0..7).
 */
export function wallClockToTeachingPeriod(wallClockPeriod: number): number {
  const match = TEACHING_PERIODS.find(p => p.wallClockPeriod === wallClockPeriod);
  if (match) return match.teachingPeriod;
  // Fallback for adjacent period mapping
  if (wallClockPeriod === 2) return 1; // short break adjacent to period 1
  if (wallClockPeriod === 5) return 3; // lunch break adjacent to period 3
  return 0;
}

/**
 * Enriched session item ready for rendering
 */
export interface EnrichedSession {
  sessionId: string;
  day: DayIndex;
  wallClockPeriod: PeriodIndex;
  teachingPeriod: number;
  durationPeriods: number; // e.g. 2 for double lab block
  roomCode: string;
  subRoomCode: string | null;
  subjectCode: string;
  subjectName: string;
  facultyInitials: string;
  facultyName: string;
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
  startTeachingPeriod: number;
  durationPeriods: number; // usually 2
  timeRange: string;
  divisionLabel: string;
  sessions: EnrichedSession[];
}

/**
 * Institutional pinned block representation
 */
export interface EnrichedPinnedBlock {
  id: string;
  label: string;
  kind: string;
  day: DayIndex;
  teachingPeriod: number;
  durationPeriods: number;
  roomCode: string;
  cohortLabel: string;
  description: string;
}

/**
 * Repository of metadata parsed from reference fixtures
 */
class TimetableMetadataStore {
  private subjects = new Map<string, { code: string; name: string }>();
  private faculty = new Map<string, { initials: string; name: string }>();
  private rooms = new Map<string, string>();
  private cohorts = new Map<string, { label: string; isCombined: boolean; description?: string }>();
  private edgeSessions = new Map<string, (typeof edgeListFixture.sessions)[0]>();
  private labBlocks = new Map<string, (typeof edgeListFixture.lab_blocks)[0]>();

  constructor() {
    this.init();
  }

  private init() {
    // Index subjects from ingestion fixture
    ingestionFixture.subjects.forEach(s => {
      this.subjects.set(s.id, { code: s.code, name: s.name });
    });

    // Index faculty from ingestion fixture
    ingestionFixture.faculty.forEach(f => {
      this.faculty.set(f.id, { initials: f.initials, name: f.full_name });
    });

    // Index rooms from edge_list and ingestion
    edgeListFixture.rooms.forEach(r => {
      this.rooms.set(r.id, r.code);
    });

    // Index cohorts
    ingestionFixture.cohorts.forEach(c => {
      this.cohorts.set(c.id, {
        label: c.label,
        isCombined: c.cohort_type === "combined",
        description: c.cohort_type === "combined" ? "Combined Division Cohort" : undefined,
      });
    });

    // Index edge sessions
    edgeListFixture.sessions.forEach(s => {
      this.edgeSessions.set(s.id, s);
    });

    // Index lab blocks
    edgeListFixture.lab_blocks.forEach(lb => {
      this.labBlocks.set(lb.id, lb);
    });
  }

  public getSubject(id: string) {
    return this.subjects.get(id) ?? { code: id.replace('subj-', '').toUpperCase(), name: 'Subject' };
  }

  public getFaculty(id: string) {
    return this.faculty.get(id) ?? { initials: id.replace('fac-', '').toUpperCase(), name: 'Faculty' };
  }

  public getRoomCode(roomId: string, subRoomId: string | null) {
    if (subRoomId) {
      // Look up sub-room code if available, else derive clean label
      const cleanSub = subRoomId.replace('room-', '').toUpperCase();
      return cleanSub;
    }
    return this.rooms.get(roomId) ?? roomId.replace('room-', '');
  }

  public getCohort(id: string) {
    return this.cohorts.get(id) ?? {
      label: id.replace('coh-', ''),
      isCombined: id.includes('comb'),
      description: id.includes('comb') ? 'Combined Division Cohort' : undefined,
    };
  }

  public getEdgeSession(sessionId: string) {
    return this.edgeSessions.get(sessionId);
  }

  public getLabBlockForSession(sessionId: string) {
    for (const lb of this.labBlocks.values()) {
      if (lb.session_ids.includes(sessionId)) {
        return lb;
      }
    }
    return null;
  }
}

export const metadataStore = new TimetableMetadataStore();

/**
 * Returns typed solved solution fixture directly from contracts/examples
 */
export function getSolvedSolutionFixture(): SolvedSolution {
  return solvedFixture as unknown as SolvedSolution;
}

/**
 * Build enriched sessions from the solution contract assignment and metadata
 */
export function buildEnrichedSessions(solution: SolvedSolution = getSolvedSolutionFixture()): EnrichedSession[] {
  return solution.assignment.map((item: SessionAssignment) => {
    const edgeSession = metadataStore.getEdgeSession(item.session_id);
    const subject = metadataStore.getSubject(edgeSession?.subject_id ?? '');
    const faculty = metadataStore.getFaculty(edgeSession?.faculty_id ?? '');
    const cohort = metadataStore.getCohort(edgeSession?.cohort_id ?? '');
    const labBlock = metadataStore.getLabBlockForSession(item.session_id);

    const isCombined = cohort.isCombined || (edgeSession?.cohort_id?.includes('comb') ?? false);
    const isPinned = edgeSession?.fixed_slot !== null && edgeSession?.fixed_slot !== undefined;

    // Extract batch if batch cohort
    let batchLabel: string | undefined;
    if (edgeSession?.cohort_id.includes('batch')) {
      const parts = edgeSession.cohort_id.split('-');
      batchLabel = `Batch ${parts[parts.length - 1].toUpperCase()}`;
    }

    const duration = edgeSession?.duration_periods ?? 1;
    const teachingPeriod = wallClockToTeachingPeriod(item.period);

    return {
      sessionId: item.session_id,
      day: item.day,
      wallClockPeriod: item.period,
      teachingPeriod,
      durationPeriods: duration,
      roomCode: metadataStore.getRoomCode(item.room_id, item.sub_room_id),
      subRoomCode: item.sub_room_id ? metadataStore.getRoomCode(item.room_id, item.sub_room_id) : null,
      subjectCode: subject.code,
      subjectName: subject.name,
      facultyInitials: faculty.initials,
      facultyName: faculty.name,
      cohortLabel: cohort.label,
      cohortSize: edgeSession?.cohort_size ?? 0,
      sessionType: (edgeSession?.session_type as "theory" | "lab") ?? "theory",
      isCombinedDivision: isCombined,
      combinedCohortText: isCombined ? `${cohort.label} (${edgeSession?.cohort_size ?? 0} students)` : undefined,
      isPinned,
      pinnedReason: isPinned ? "Fixed Pre-allocated Slot (Faculty availability constraint)" : undefined,
      labBlockId: labBlock?.id,
      batchLabel,
    };
  });
}

/**
 * Returns grouped parallel lab blocks (e.g. 4 parallel batches in 1 double slot)
 */
export function buildEnrichedLabBlocks(sessions: EnrichedSession[]): EnrichedLabBlock[] {
  const blockMap = new Map<string, EnrichedSession[]>();

  sessions.forEach(sess => {
    if (sess.labBlockId) {
      const existing = blockMap.get(sess.labBlockId) ?? [];
      existing.push(sess);
      blockMap.set(sess.labBlockId, existing);
    }
  });

  const blocks: EnrichedLabBlock[] = [];
  blockMap.forEach((blockSessions, blockId) => {
    const first = blockSessions[0];
    blocks.push({
      blockId,
      day: first.day,
      startTeachingPeriod: first.teachingPeriod,
      durationPeriods: first.durationPeriods,
      timeRange: "10:00 – 12:15 (Spans Short Break)",
      divisionLabel: "SE-Comp B Labs (Batches A, B, C, D)",
      sessions: blockSessions,
    });
  });

  return blocks;
}

/**
 * Returns institutional pinned blocks from contracts (MDM, HSS, etc.)
 */
export function getPinnedBlocks(): EnrichedPinnedBlock[] {
  return [
    {
      id: "pin-0001",
      label: "MDM - I THEORY",
      kind: "Multidisciplinary Minor (MDM)",
      day: 3, // Thursday
      teachingPeriod: 3, // Period 3 (12:15 - 13:15 / wall-clock 4)
      durationPeriods: 1,
      roomCode: "508",
      cohortLabel: "SE-Comp B",
      description: "Immovable Institutional Occupancy — Multidisciplinary Minor",
    },
    {
      id: "pin-0002",
      label: "HSS II",
      kind: "Humanities & Social Sciences (HSS)",
      day: 2, // Wednesday
      teachingPeriod: 5, // Period 5 (15:15 - 16:15 / wall-clock 7)
      durationPeriods: 1,
      roomCode: "002",
      cohortLabel: "SE-Comp C",
      description: "Immovable Institutional Occupancy — Humanities",
    },
  ];
}
