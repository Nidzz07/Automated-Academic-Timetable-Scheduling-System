/**
 * Chronos API Client interface and mock implementation.
 * 
 * Every solution payload is validated against contracts/solution_v1.schema.json or
 * solution_v2.schema.json, and every edge list against edge_list_v1.schema.json
 * (see contractValidation.ts); an invalid one throws ContractValidationError.
 * Swapping in the real backend later is a change of implementation,
 * not of call sites.
 */

import {
  SolutionContract,
  SolvedSolution,
  InfeasibleSolution,
  DayIndex,
  PeriodIndex,
  SessionAssignment,
  parseSolution,
  isSolvedSolution,
  isInfeasibleSolution,
} from '@/adapters/solution';
import { validateContract } from '@/api/contractValidation';
import solvedFixture from '@contracts/examples/solution_v2.solved.example.json';
import infeasibleFixture from '@contracts/examples/solution_v2.infeasible.example.json';
import edgeListExample from '@contracts/examples/edge_list_v1.example.json';
import d6GridEdgeList from '@contracts/examples/edge_list_v1.d6_grid.example.json';
import {
  DAY_NAMES,
  EdgeList,
  cohortsOverlap,
  getCohortLabel,
  getExampleEdgeList,
  getFaculty,
} from '@/adapters/timetable';

/**
 * Edge lists the mock serves. 'example' is the instance the solution examples were solved
 * for; 'd6_grid' shows the D6 grid (per-year lunch as pinned occupancy) and has no solution.
 */
export const EDGE_LIST_INSTANCES = { example: edgeListExample, d6_grid: d6GridEdgeList };
export type EdgeListInstance = keyof typeof EDGE_LIST_INSTANCES;

export interface MoveSessionRequest {
  sessionId: string;
  targetDay: DayIndex;
  targetWallClockPeriod: PeriodIndex;
  targetRoomId?: string;
  targetSubRoomId?: string | null;
}

export interface ViolatedConstraint {
  constraint_id: string;
  kind: string;
  description: string;
  entity_ids: string[];
}

export interface MoveSessionResult {
  success: boolean;
  solution?: SolvedSolution;
  rejectionReason?: string;
  violatedConstraint?: ViolatedConstraint;
}

/**
 * Common API Client interface that both the mock and real HTTP backend client implement.
 */
export interface ChronosApiClient {
  /**
   * Fetch current timetable. Returns either SolvedSolution or InfeasibleSolution.
   */
  getTimetable(id?: string): Promise<SolutionContract>;

  /**
   * Fetch an instance's edge list (grid, rooms, sessions, pinned occupancy).
   */
  getEdgeList(instance?: EdgeListInstance): Promise<EdgeList>;

  /**
   * Request solver to generate a timetable.
   */
  generateTimetable(): Promise<SolutionContract>;

  /**
   * Move a session to a target slot. Validates constraints.
   */
  moveSession(req: MoveSessionRequest, currentSolution: SolvedSolution): Promise<MoveSessionResult>;

  /**
   * Helper to retrieve solved fixture.
   */
  getSolvedSolution(): Promise<SolvedSolution>;

  /**
   * Helper to retrieve infeasible fixture.
   */
  getInfeasibleSolution(): Promise<InfeasibleSolution>;
}

/**
 * Mock Chronos API client for Phase 2 Track C.
 * Provides both solved and infeasible responses and a configurable reject-the-move path.
 */
export class MockChronosApiClient implements ChronosApiClient {
  private simulatedOutcome: 'solved' | 'infeasible' = 'solved';
  private rejectMode: boolean = false;
  private rejectionReason: string = 'Simulated backend rejection: Hard constraint violation (faculty clash)';

  constructor(initialOutcome: 'solved' | 'infeasible' = 'solved') {
    this.simulatedOutcome = initialOutcome;
  }

  /**
   * Configure whether future move operations should be rejected for testing/simulation.
   */
  public setRejectMode(reject: boolean, reason?: string) {
    this.rejectMode = reject;
    if (reason) {
      this.rejectionReason = reason;
    }
  }

  public isRejectMode(): boolean {
    return this.rejectMode;
  }

  /**
   * Set simulated solver outcome ('solved' or 'infeasible').
   */
  public setSimulatedOutcome(outcome: 'solved' | 'infeasible') {
    this.simulatedOutcome = outcome;
  }

  public getSimulatedOutcome(): 'solved' | 'infeasible' {
    return this.simulatedOutcome;
  }

  public async getTimetable(id?: string): Promise<SolutionContract> {
    if (id === 'infeasible' || this.simulatedOutcome === 'infeasible') {
      return this.getInfeasibleSolution();
    }
    return this.getSolvedSolution();
  }

  public async getEdgeList(instance: EdgeListInstance = 'example'): Promise<EdgeList> {
    return validateContract('edge_list', JSON.parse(JSON.stringify(EDGE_LIST_INSTANCES[instance])));
  }

  public async generateTimetable(): Promise<SolutionContract> {
    // Simulate brief solver runtime
    await new Promise((resolve) => setTimeout(resolve, 50));
    if (this.simulatedOutcome === 'infeasible') {
      return this.getInfeasibleSolution();
    }
    return this.getSolvedSolution();
  }

  public async getSolvedSolution(): Promise<SolvedSolution> {
    // Deep clone of the solved example, validated like any API payload
    const solution = parseSolution(JSON.parse(JSON.stringify(solvedFixture)));
    if (!isSolvedSolution(solution)) throw new Error('Expected a solved solution payload');
    return solution;
  }

  public async getInfeasibleSolution(): Promise<InfeasibleSolution> {
    // Deep clone of the infeasible example, validated like any API payload
    const solution = parseSolution(JSON.parse(JSON.stringify(infeasibleFixture)));
    if (!isInfeasibleSolution(solution)) throw new Error('Expected an infeasible solution payload');
    return solution;
  }

  /**
   * Validate and apply session move.
   */
  public async moveSession(
    req: MoveSessionRequest,
    currentSolution: SolvedSolution
  ): Promise<MoveSessionResult> {
    // Simulate network latency (small for test responsiveness)
    await new Promise((resolve) => setTimeout(resolve, 30));

    // 1. Check explicit reject simulation toggle
    if (this.rejectMode) {
      return {
        success: false,
        rejectionReason: this.rejectionReason,
        violatedConstraint: {
          constraint_id: 'mock.simulated-reject',
          kind: 'SIMULATED_REJECTION',
          description: this.rejectionReason,
          entity_ids: [req.sessionId],
        },
      };
    }

    // 2. Validate session existence in current solution
    const sessionIndex = currentSolution.assignment.findIndex(
      (a) => a.session_id === req.sessionId
    );
    if (sessionIndex === -1) {
      return {
        success: false,
        rejectionReason: `Session '${req.sessionId}' not found in current timetable assignment.`,
      };
    }

    // The solution examples were solved for the example instance
    const edgeList = getExampleEdgeList();
    const edgeSession = edgeList.sessions.find((s) => s.id === req.sessionId);
    const slotLabel = `${DAY_NAMES[req.targetDay]} P${req.targetWallClockPeriod}`;

    // 3. Reject if the session itself is fixed / pinned
    if (edgeSession?.fixed_slot !== null && edgeSession?.fixed_slot !== undefined) {
      const reason = `Cannot move session '${req.sessionId}': session is pinned to a fixed slot (fixed_slot in the edge list).`;
      return {
        success: false,
        rejectionReason: reason,
        violatedConstraint: {
          constraint_id: `pin.${req.sessionId}`,
          kind: 'PINNED_SESSION',
          description: reason,
          entity_ids: [req.sessionId],
        },
      };
    }

    // 4. Reject if pinned occupancy at the target holds the session's cohort, teacher or room
    const roomId = currentSolution.assignment[sessionIndex].room_id;
    const pin = edgeList.pinned_occupancy.find(
      (p) =>
        p.day === req.targetDay &&
        p.period === req.targetWallClockPeriod &&
        ((!!edgeSession && p.cohort_ids.some((c) => cohortsOverlap(c, edgeSession.cohort_id))) ||
          (!!edgeSession && p.faculty_ids.includes(edgeSession.faculty_id)) ||
          p.room_ids.includes(roomId))
    );
    if (pin) {
      const held = [
        ...pin.cohort_ids.map(getCohortLabel),
        ...pin.room_ids.map((id) => `room ${edgeList.rooms.find((r) => r.id === id)?.code ?? id}`),
      ].join(', ');
      const reason = `Slot conflict: ${slotLabel} is held by pinned occupancy (${held}).`;
      return {
        success: false,
        rejectionReason: reason,
        violatedConstraint: {
          constraint_id: `pinned.${req.targetDay}.${req.targetWallClockPeriod}`,
          kind: 'PINNED_BLOCK',
          description: reason,
          entity_ids: [...pin.cohort_ids, ...pin.room_ids, ...pin.faculty_ids, req.sessionId],
        },
      };
    }

    // 5. Reject if moving causes a faculty clash with another session
    const facultyId = edgeSession?.faculty_id;
    if (facultyId) {
      for (const other of currentSolution.assignment) {
        if (other.session_id === req.sessionId) continue;
        const otherEdge = edgeList.sessions.find((s) => s.id === other.session_id);

        if (
          other.day === req.targetDay &&
          other.period === req.targetWallClockPeriod &&
          otherEdge?.faculty_id === facultyId
        ) {
          const faculty = getFaculty(facultyId);
          const reason = `Faculty clash: ${faculty.initials} (${faculty.name}) is already scheduled for session '${other.session_id}' on this slot.`;
          return {
            success: false,
            rejectionReason: reason,
            violatedConstraint: {
              constraint_id: `clash.fac.${facultyId}.${req.targetDay}.${req.targetWallClockPeriod}`,
              kind: 'FACULTY_CLASH',
              description: reason,
              entity_ids: [facultyId, req.sessionId, other.session_id],
            },
          };
        }
      }
    }

    // 6. Valid move: apply updated placement
    const updatedAssignment: SessionAssignment[] = currentSolution.assignment.map((a) => {
      if (a.session_id === req.sessionId) {
        return {
          ...a,
          day: req.targetDay,
          period: req.targetWallClockPeriod,
          room_id: req.targetRoomId ?? a.room_id,
          sub_room_id: req.targetSubRoomId !== undefined ? req.targetSubRoomId : a.sub_room_id,
        };
      }
      return a;
    });

    const updatedSolution: SolvedSolution = {
      ...currentSolution,
      assignment: updatedAssignment,
      displaced: Array.from(new Set([...currentSolution.displaced, req.sessionId])),
    };

    parseSolution(updatedSolution);
    return {
      success: true,
      solution: updatedSolution,
    };
  }
}

/**
 * Singleton mock instance for application use.
 */
export const chronosApiClient = new MockChronosApiClient();
