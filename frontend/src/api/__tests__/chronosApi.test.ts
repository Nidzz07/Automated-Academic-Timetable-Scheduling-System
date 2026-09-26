import { describe, it, expect, beforeEach } from 'vitest';
import { MockChronosApiClient } from '../chronosApi';
import { isSolvedSolution, isInfeasibleSolution } from '@/types/solution';
import solvedFixture from '@/fixtures/solution_v1.solved.example.json';
import infeasibleFixture from '@/fixtures/solution_v1.infeasible.example.json';

describe('MockChronosApiClient', () => {
  let client: MockChronosApiClient;

  beforeEach(() => {
    client = new MockChronosApiClient('solved');
  });

  it('implements ChronosApiClient and returns typed solved fixture by default', async () => {
    const timetable = await client.getTimetable();
    expect(isSolvedSolution(timetable)).toBe(true);
    expect(isInfeasibleSolution(timetable)).toBe(false);
    if (isSolvedSolution(timetable)) {
      expect(timetable.schema_version).toBe('solution.v1');
      expect(timetable.assignment.length).toBe(solvedFixture.assignment.length);
      expect(timetable.quality.score).toBe(93.2);
    }
  });

  it('returns typed infeasible fixture with minimal conflicting subset and suggested relaxation', async () => {
    client.setSimulatedOutcome('infeasible');
    const timetable = await client.getTimetable();
    expect(isInfeasibleSolution(timetable)).toBe(true);
    expect(isSolvedSolution(timetable)).toBe(false);

    if (isInfeasibleSolution(timetable)) {
      expect(timetable.schema_version).toBe('solution.v1');
      expect(timetable.diagnosis.minimal_conflicting_set.length).toBe(
        infeasibleFixture.diagnosis.minimal_conflicting_set.length
      );
      expect(timetable.diagnosis.suggested_relaxation.constraint_id).toBe(
        infeasibleFixture.diagnosis.suggested_relaxation.constraint_id
      );
      expect(timetable.diagnosis.suggested_relaxation.description).toBe(
        infeasibleFixture.diagnosis.suggested_relaxation.description
      );
    }
  });

  it('successfully moves an unconstrained session to a free slot', async () => {
    const solved = await client.getSolvedSolution();
    // sess-0006 is DAA on Wednesday period 1
    const res = await client.moveSession(
      {
        sessionId: 'sess-0006',
        targetDay: 0, // Monday
        targetTeachingPeriod: 4, // Period 5 (14:15)
        targetWallClockPeriod: 6,
      },
      solved
    );

    expect(res.success).toBe(true);
    expect(res.solution).toBeDefined();
    if (res.solution) {
      const moved = res.solution.assignment.find((a) => a.session_id === 'sess-0006');
      expect(moved).toBeDefined();
      expect(moved?.day).toBe(0);
      expect(moved?.period).toBe(6);
      expect(res.solution.displaced).toContain('sess-0006');
    }
  });

  it('rejects moving a pinned fixed-slot session (sess-0008)', async () => {
    const solved = await client.getSolvedSolution();
    const res = await client.moveSession(
      {
        sessionId: 'sess-0008',
        targetDay: 1,
        targetTeachingPeriod: 0,
        targetWallClockPeriod: 0,
      },
      solved
    );

    expect(res.success).toBe(false);
    expect(res.rejectionReason).toContain('Cannot move session');
    expect(res.rejectionReason).toContain('pinned');
    expect(res.violatedConstraint?.kind).toBe('PINNED_SESSION');
  });

  it('rejects moving into a slot reserved by a pinned institutional block (Thursday Period 3 MDM)', async () => {
    const solved = await client.getSolvedSolution();
    const res = await client.moveSession(
      {
        sessionId: 'sess-0006',
        targetDay: 3, // Thursday
        targetTeachingPeriod: 3, // Period 4 (12:15 - 13:15, MDM)
        targetWallClockPeriod: 4,
      },
      solved
    );

    expect(res.success).toBe(false);
    expect(res.rejectionReason).toContain("MDM - I THEORY");
    expect(res.violatedConstraint?.kind).toBe('PINNED_BLOCK_CLASH');
  });

  it('exercises the reject-the-move path when rejectMode is explicitly toggled', async () => {
    const solved = await client.getSolvedSolution();
    const customReason = 'Simulated room capacity deficit: Cohort 140 exceeds room capacity 80';
    client.setRejectMode(true, customReason);

    const res = await client.moveSession(
      {
        sessionId: 'sess-0006',
        targetDay: 0,
        targetTeachingPeriod: 4,
        targetWallClockPeriod: 6,
      },
      solved
    );

    expect(res.success).toBe(false);
    expect(res.rejectionReason).toBe(customReason);
    expect(res.violatedConstraint?.description).toBe(customReason);
  });
});
