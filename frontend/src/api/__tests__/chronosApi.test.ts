import { describe, it, expect, beforeEach, vi } from 'vitest';
import { MockChronosApiClient, PRINTED_INSTANCE, REAL_INSTANCE } from '../chronosApi';
import { isSolvedSolution, isInfeasibleSolution } from '@/adapters/solution';
import solvedFixture from '@contracts/examples/solution_v2.solved.example.json';
import infeasibleFixture from '@contracts/examples/solution_v2.infeasible.example.json';

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
      expect(timetable.schema_version).toBe('solution.v2');
      expect(timetable.assignment.length).toBe(solvedFixture.assignment.length);
      expect(timetable.quality.score).toBe(99.0);
    }
  });

  it('returns typed infeasible fixture with minimal conflicting subset and suggested relaxation', async () => {
    client.setSimulatedOutcome('infeasible');
    const timetable = await client.getTimetable();
    expect(isInfeasibleSolution(timetable)).toBe(true);
    expect(isSolvedSolution(timetable)).toBe(false);

    if (isInfeasibleSolution(timetable)) {
      expect(timetable.schema_version).toBe('solution.v2');
      expect(timetable.diagnosis.minimal_conflicting_set.length).toBe(
        infeasibleFixture.diagnosis.minimal_conflicting_set.length
      );
      expect(timetable.diagnosis.suggested_relaxation?.constraint_id).toBe(
        infeasibleFixture.diagnosis.suggested_relaxation.constraint_id
      );
      expect(timetable.diagnosis.suggested_relaxation?.description).toBe(
        infeasibleFixture.diagnosis.suggested_relaxation.description
      );
    }
  });

  it('successfully moves an unconstrained session to a free slot', async () => {
    const solved = await client.getSolvedSolution();
    // sess-0006 is OS on Wednesday P3; move it to Monday P6
    const res = await client.moveSession(
      {
        sessionId: 'sess-0006',
        targetDay: 0, // Monday
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
        targetWallClockPeriod: 0,
      },
      solved
    );

    expect(res.success).toBe(false);
    expect(res.rejectionReason).toContain('Cannot move session');
    expect(res.rejectionReason).toContain('pinned');
    expect(res.violatedConstraint?.kind).toBe('PINNED_SESSION');
  });

  it('rejects moving into a slot whose pinned_occupancy holds the session cohort or room', async () => {
    const solved = await client.getSolvedSolution();
    // Wednesday P7 is pinned for SE-Comp C in room 002: sess-0006's cohort and room
    const res = await client.moveSession(
      { sessionId: 'sess-0006', targetDay: 2, targetWallClockPeriod: 7 },
      solved
    );

    expect(res.success).toBe(false);
    expect(res.rejectionReason).toBe(
      'Slot conflict: Wednesday T7 is held by pinned occupancy (SE-Comp C, room 002).'
    );
    expect(res.violatedConstraint?.kind).toBe('PINNED_BLOCK');
  });

  it('allows a slot pinned only for other cohorts and rooms', async () => {
    const solved = await client.getSolvedSolution();
    // Thursday P4 is pinned for SE-Comp B in room 508; sess-0006 is SE-Comp C in room 002
    const res = await client.moveSession(
      { sessionId: 'sess-0006', targetDay: 3, targetWallClockPeriod: 4 },
      solved
    );
    expect(res.success).toBe(true);
  });

  it('serves the example and D6 edge lists from contracts/examples, validated', async () => {
    const example = await client.getEdgeList();
    expect(example.sessions.map((s) => s.id)).toContain('sess-0006');

    const d6 = await client.getEdgeList('d6_grid');
    expect(d6.slot_grid.teaching_periods).toEqual([0, 1, 3, 4, 5, 6, 7, 8, 9]);
    expect(d6.pinned_occupancy).toHaveLength(10);
  });

  it('serves the real EVEN 2025-26 instance from data/instances/even-2025-26/', async () => {
    const real = await client.getEdgeList(REAL_INSTANCE);
    expect(real.sessions).toHaveLength(156);
    expect(real.lab_blocks).toHaveLength(31);

    const display = await client.getDisplay(REAL_INSTANCE);
    expect(display?.pins).toHaveLength(real.pinned_occupancy.length);
    // S12d committed solution.json: validated as solution.v2, placing every session
    const solution = await client.getInstanceSolution(REAL_INSTANCE);
    expect(solution?.schema_version).toBe('solution.v2');
    if (!solution || !isSolvedSolution(solution)) throw new Error('Expected a solved solution.json');
    expect(solution.assignment.map((a) => a.session_id).sort()).toEqual(real.sessions.map((s) => s.id).sort());
  });

  it('returns null for the real instance when solution.json is missing', async () => {
    vi.resetModules();
    // a JSON null is what loadRealEven yields for a file with no loader
    vi.doMock('@instances/even-2025-26/solution.json', () => ({ default: null }));
    try {
      const { MockChronosApiClient: Fresh } = await import('../chronosApi');
      expect(await new Fresh().getInstanceSolution(REAL_INSTANCE)).toBeNull();
    } finally {
      vi.doUnmock('@instances/even-2025-26/solution.json');
      vi.resetModules();
    }
  });

  it('gives the contract examples no display sidecar and no published solution', async () => {
    expect(await client.getDisplay('example')).toBeNull();
    expect(await client.getDisplay('d6_grid')).toBeNull();
    expect(await client.getInstanceSolution('d6_grid')).toBeNull();
    expect(await client.getAnomalies('example')).toBeNull();
    expect(await client.getPrintedBaseline('example')).toBeNull();
  });

  it('serves the real instance’s anomaly report, and the printed baseline on it and its printed view', async () => {
    const report = await client.getAnomalies(REAL_INSTANCE);
    expect(report?.anomalies).toHaveLength(report!.counts.total);
    expect(await client.getPrintedBaseline(REAL_INSTANCE)).toEqual(await client.getPrintedBaseline(PRINTED_INSTANCE));
    const printed = await client.getPrintedBaseline(PRINTED_INSTANCE);
    expect(printed?.assignment).toHaveLength((await client.getEdgeList(PRINTED_INSTANCE)).sessions.length);
    expect(await client.getInstanceSolution(PRINTED_INSTANCE)).toBeNull();
  });

  it('lists the contract examples, the real instance and its printed view, none solvable', async () => {
    expect(await client.listInstances()).toEqual([
      { id: 'example', label: 'Example instance', solvable: false },
      { id: 'd6_grid', label: 'D6 grid example (no solution)', solvable: false },
      { id: REAL_INSTANCE, label: 'EVEN 2025-26 SE+TE (real)', solvable: false },
      { id: PRINTED_INSTANCE, label: 'EVEN 2025-26 printed (real)', solvable: false },
    ]);
  });

  it('exercises the reject-the-move path when rejectMode is explicitly toggled', async () => {
    const solved = await client.getSolvedSolution();
    const customReason = 'Simulated room capacity deficit: Cohort 140 exceeds room capacity 80';
    client.setRejectMode(true, customReason);

    const res = await client.moveSession(
      {
        sessionId: 'sess-0006',
        targetDay: 0,
        targetWallClockPeriod: 6,
      },
      solved
    );

    expect(res.success).toBe(false);
    expect(res.rejectionReason).toBe(customReason);
    expect(res.violatedConstraint?.description).toBe(customReason);
  });
});
