/**
 * Chronos API Client interface and mock implementation.
 * 
 * Typed directly against contracts/solution_v1.schema.json.
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
} from '@/types/solution';
import solvedFixture from '@/fixtures/solution_v1.solved.example.json';
import infeasibleFixture from '@/fixtures/solution_v1.infeasible.example.json';
import { metadataStore, wallClockToTeachingPeriod } from '@/lib/timetableData';

export interface MoveSessionRequest {
  sessionId: string;
  targetDay: DayIndex;
  targetTeachingPeriod: number; // 0..7
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

  public async generateTimetable(): Promise<SolutionContract> {
    // Simulate brief solver runtime
    await new Promise((resolve) => setTimeout(resolve, 50));
    if (this.simulatedOutcome === 'infeasible') {
      return this.getInfeasibleSolution();
    }
    return this.getSolvedSolution();
  }

  public async getSolvedSolution(): Promise<SolvedSolution> {
    // Return deep clone of solved fixture
    return JSON.parse(JSON.stringify(solvedFixture)) as SolvedSolution;
  }

  public async getInfeasibleSolution(): Promise<InfeasibleSolution> {
    // Return deep clone of infeasible fixture
    return JSON.parse(JSON.stringify(infeasibleFixture)) as InfeasibleSolution;
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

    const edgeSession = metadataStore.getEdgeSession(req.sessionId);

    // 3. Reject if the session itself is fixed / pinned
    if (edgeSession?.fixed_slot !== null && edgeSession?.fixed_slot !== undefined) {
      const reason = `Cannot move session '${req.sessionId}': session is pinned to fixed slot (Faculty availability constraint).`;
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

    // 4. Reject if target slot conflicts with institutional pinned blocks
    // Thursday (day 3) period 3 (12:15) is MDM
    if (req.targetDay === 3 && req.targetTeachingPeriod === 3) {
      const reason = `Slot conflict: Thursday 12:15–13:15 is reserved for pinned institutional block 'MDM - I THEORY'.`;
      return {
        success: false,
        rejectionReason: reason,
        violatedConstraint: {
          constraint_id: 'pin-0001',
          kind: 'PINNED_BLOCK_CLASH',
          description: reason,
          entity_ids: ['pin-0001', req.sessionId],
        },
      };
    }

    // Wednesday (day 2) period 5 (15:15) is HSS II
    if (req.targetDay === 2 && req.targetTeachingPeriod === 5) {
      const reason = `Slot conflict: Wednesday 15:15–16:15 is reserved for pinned institutional block 'HSS II'.`;
      return {
        success: false,
        rejectionReason: reason,
        violatedConstraint: {
          constraint_id: 'pin-0002',
          kind: 'PINNED_BLOCK_CLASH',
          description: reason,
          entity_ids: ['pin-0002', req.sessionId],
        },
      };
    }

    // 5. Reject if moving causes a faculty clash with another session
    const facultyId = edgeSession?.faculty_id;
    if (facultyId) {
      for (const other of currentSolution.assignment) {
        if (other.session_id === req.sessionId) continue;
        const otherEdge = metadataStore.getEdgeSession(other.session_id);
        const otherTeachingPeriod = wallClockToTeachingPeriod(other.period);

        if (
          other.day === req.targetDay &&
          otherTeachingPeriod === req.targetTeachingPeriod &&
          otherEdge?.faculty_id === facultyId
        ) {
          const faculty = metadataStore.getFaculty(facultyId);
          const reason = `Faculty clash: ${faculty.initials} (${faculty.name}) is already scheduled for session '${other.session_id}' on this slot.`;
          return {
            success: false,
            rejectionReason: reason,
            violatedConstraint: {
              constraint_id: `clash.fac.${facultyId}.${req.targetDay}.${req.targetTeachingPeriod}`,
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
      metadata: {
        ...currentSolution.metadata,
        runtime_ms: Number((currentSolution.metadata.runtime_ms + 1.2).toFixed(1)),
      },
    };

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
