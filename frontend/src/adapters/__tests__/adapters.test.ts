import { describe, it, expect } from 'vitest';
import { ContractValidationError, validateContract } from '@/api/contractValidation';
import {
  DIAGNOSIS_METHOD_LABELS,
  InfeasibleSolution,
  isInfeasibleSolution,
  isSolvedSolution,
  parseSolution,
  toDiagnosisView,
  toQualityView,
} from '../solution';
import {
  buildEnrichedLabBlocks,
  buildEnrichedSessions,
  buildPins,
  buildWeekGrid,
  cohortsOverlap,
  getExampleEdgeList,
  getSolvedSolutionFixture,
} from '../timetable';
import solvedExample from '@contracts/examples/solution_v1.solved.example.json';
import infeasibleExample from '@contracts/examples/solution_v1.infeasible.example.json';
import solvedV2Example from '@contracts/examples/solution_v2.solved.example.json';
import infeasibleV2Example from '@contracts/examples/solution_v2.infeasible.example.json';
import d6GridExample from '@contracts/examples/edge_list_v1.d6_grid.example.json';

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

function infeasible(raw: unknown): InfeasibleSolution {
  const sol = parseSolution(raw);
  if (!isInfeasibleSolution(sol)) throw new Error('expected an infeasible payload');
  return sol;
}

describe('solution adapter', () => {
  it('narrows validated v1 and v2 payloads to the solved / infeasible view types', () => {
    expect(isSolvedSolution(parseSolution(solvedExample))).toBe(true);
    expect(isInfeasibleSolution(parseSolution(infeasibleExample))).toBe(true);
    expect(parseSolution(solvedV2Example).schema_version).toBe('solution.v2');
    expect(isInfeasibleSolution(parseSolution(infeasibleV2Example))).toBe(true);
  });

  it('refuses a payload that is not a solution contract', () => {
    expect(() => parseSolution({ status: 'solved' })).toThrow(ContractValidationError);
  });

  it('holds a solution.v2 payload to the v2 schema, not v1', () => {
    // v2 fields are not allowed by v1, so a v2 payload only passes if routed to v2
    const bad = { ...clone(solvedV2Example), quality: { score: 1, breakdown: [] } };
    expect(() => parseSolution(bad)).toThrow(
      expect.objectContaining({ schema: 'solution_v2' })
    );
  });
});

describe('quality view', () => {
  it('maps v2 rules with status evaluated / not_evaluated and the rule-set version', () => {
    const solved = parseSolution(solvedV2Example);
    if (!isSolvedSolution(solved)) throw new Error('expected solved');
    const view = toQualityView(solved);

    expect(view.score).toBe(99.0);
    expect(view.rulesVersion).toBe('1');
    expect(view.notEvaluatedRuleIds).toEqual(['S-LOAD16']);
    expect(view.rules.map((r) => r.rule_id)).toEqual([
      'S-GAP',
      'S-B2B',
      'FAC_LOAD_IMBALANCE',
      'S-LOAD16',
    ]);
    const load = view.rules.find((r) => r.rule_id === 'S-LOAD16');
    expect(load).toMatchObject({ status: 'not_evaluated' });
    expect(load).not.toHaveProperty('penalty');
    expect(load).not.toHaveProperty('raw');
    expect(view.rules.find((r) => r.rule_id === 'FAC_LOAD_IMBALANCE')).toMatchObject({
      status: 'evaluated',
      raw: 2,
      penalty: 1.0,
    });
  });

  it('drops the score when no rule was evaluated (the stand-in until S10)', () => {
    const raw = clone(solvedV2Example) as { quality: Record<string, unknown> };
    raw.quality = {
      score: 100.0,
      rules_version: 'none',
      not_evaluated_rule_ids: ['S-GAP'],
      breakdown: [{ rule_id: 'S-GAP', status: 'not_evaluated', weight: 0.0, reason: 'not loaded' }],
    };
    const solved = parseSolution(raw);
    if (!isSolvedSolution(solved)) throw new Error('expected solved');
    expect(toQualityView(solved)).toMatchObject({ score: null, rulesVersion: 'none' });
  });

  it('marks every v1 rule evaluated, with no rule-set version', () => {
    const solved = parseSolution(solvedExample);
    if (!isSolvedSolution(solved)) throw new Error('expected solved');
    const view = toQualityView(solved);
    expect(view.rulesVersion).toBeNull();
    expect(view.notEvaluatedRuleIds).toEqual([]);
    expect(view.rules.every((r) => r.status === 'evaluated')).toBe(true);
  });
});

describe('diagnosis view', () => {
  it('maps a v2 mus diagnosis: closed kinds, structured slots, typed relaxation, partial placement', () => {
    const view = toDiagnosisView(infeasible(infeasibleV2Example));

    expect(view.method).toBe('mus');
    expect(view.methodLabel).toBe(DIAGNOSIS_METHOD_LABELS.mus);
    expect(view.minimal_conflicting_set.map((c) => c.kind)).toEqual([
      'LAB_CONTIGUITY',
      'ROOM_OCCUPANCY',
      'PINNED_BLOCK',
    ]);
    expect(view.minimal_conflicting_set[1].slots).toEqual([
      { day: 0, period: 1 },
      { day: 0, period: 3 },
    ]);
    expect(view.suggested_relaxation).toMatchObject({
      constraint_id: 'lab-rooms.monday-10.00',
      action_type: 'RECLASSIFY_ROOM',
      verification: { status: 'restored', runtime_ms: 212.4 },
    });
    expect(view.partial_placement?.map((p) => p.session_id)).toEqual([
      'sess-0005',
      'sess-0006',
      'sess-0007',
      'sess-0008',
    ]);
    expect(view.unplaced_session_ids).toEqual(['sess-0001', 'sess-0002', 'sess-0003', 'sess-0004']);
  });

  it('maps a v2 search_exhaustion diagnosis: no conflicting set, no relaxation', () => {
    const raw = clone(infeasibleV2Example) as { diagnosis: Record<string, unknown> };
    raw.diagnosis.method = 'search_exhaustion';
    raw.diagnosis.minimal_conflicting_set = [];
    delete raw.diagnosis.suggested_relaxation;

    const view = toDiagnosisView(infeasible(raw));
    expect(view.method).toBe('search_exhaustion');
    expect(view.methodLabel).toBe(DIAGNOSIS_METHOD_LABELS.search_exhaustion);
    expect(view.minimal_conflicting_set).toEqual([]);
    expect(view.suggested_relaxation).toBeNull();
    expect(view.unplaced_session_ids).toHaveLength(4);
  });

  it('maps a v1 diagnosis with no method, no slots and no partial placement', () => {
    const view = toDiagnosisView(infeasible(infeasibleExample));
    expect(view.method).toBeNull();
    expect(view.methodLabel.badge).toBe('Method not stated (solution.v1)');
    expect(view.minimal_conflicting_set.every((c) => c.slots.length === 0)).toBe(true);
    expect(view.suggested_relaxation).toMatchObject({ action_type: null, verification: null });
    expect(view.partial_placement).toBeNull();
  });
});

describe('timetable adapter', () => {
  const edgeList = getExampleEdgeList();
  const sessions = buildEnrichedSessions(getSolvedSolutionFixture().assignment, edgeList);

  it('maps an assignment plus edge-list and ingestion metadata to a session view model', () => {
    const os = sessions.find((s) => s.sessionId === 'sess-0006');
    expect(os).toMatchObject({
      day: 2,
      wallClockPeriod: 3,
      periods: [3],
      durationPeriods: 1,
      roomCode: '002',
      subRoomCode: null,
      subjectCode: 'OS',
      subjectName: 'Operating Systems',
      cohortLabel: 'SE-Comp C',
      cohortSize: 70,
      sessionType: 'theory',
      isPinned: false,
    });
  });

  it('takes sub-room codes from the edge list and occupies periods in teaching order', () => {
    const os = sessions.find((s) => s.sessionId === 'sess-0001');
    // teaching_periods skip the P2 break, so a 2-period lab at P1 occupies P1 and P3
    expect(os).toMatchObject({ subRoomCode: '702-A', periods: [1, 3] });
  });

  it('groups lab-block members into one parallel lab block that straddles the break', () => {
    const blocks = buildEnrichedLabBlocks(sessions);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ blockId: 'labblk-0001', periods: [1, 3], spannedBreaks: [2] });
    expect(blocks[0].sessions.map((s) => s.sessionId).sort()).toEqual([
      'sess-0001',
      'sess-0002',
      'sess-0003',
      'sess-0004',
    ]);
  });

  it('reads pinned blocks from pinned_occupancy, with no label of its own', () => {
    expect(buildPins(edgeList)).toEqual([
      expect.objectContaining({ day: 3, period: 4, isLunch: false, roomCodes: ['508'], cohortLabels: ['SE-Comp B'] }),
      expect.objectContaining({ day: 2, period: 7, isLunch: false, roomCodes: ['002'], cohortLabels: ['SE-Comp C'] }),
    ]);
  });

  it('matches a division with its batches through the ingestion cohorts', () => {
    expect(cohortsOverlap('coh-div-se-b', 'coh-batch-se-b-a')).toBe(true);
    expect(cohortsOverlap('coh-div-se-b', 'coh-div-se-c')).toBe(false);
  });
});

describe('D6 grid from the edge list', () => {
  const d6 = validateContract('edge_list', d6GridExample);

  it('takes periods and breaks from slot_grid: P2 is a break, P4 and P5 are teaching', () => {
    const grid = buildWeekGrid(d6);
    expect(grid.days).toEqual([0, 1, 2, 3, 4]);
    expect(grid.periods.filter((p) => !p.teaching).map((p) => p.period)).toEqual([2]);
    expect(grid.teachingPeriods).toEqual([0, 1, 3, 4, 5, 6, 7, 8, 9]);
  });

  it('reads each year’s lunch from pinned_occupancy: SE at P5, TE at P4', () => {
    const lunch = buildPins(d6).filter((p) => p.isLunch);
    expect(lunch).toHaveLength(10);
    const se = lunch.filter((p) => p.cohortIds.includes('coh-div-se-a'));
    const te = lunch.filter((p) => p.cohortIds.includes('coh-div-te-a'));
    expect(se.map((p) => [p.day, p.period])).toEqual([[0, 5], [1, 5], [2, 5], [3, 5], [4, 5]]);
    expect(te.map((p) => [p.day, p.period])).toEqual([[0, 4], [1, 4], [2, 4], [3, 4], [4, 4]]);
  });
});
