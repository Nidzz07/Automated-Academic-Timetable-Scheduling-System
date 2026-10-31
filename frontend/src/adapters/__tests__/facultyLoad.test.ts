import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { MockChronosApiClient, PRINTED_INSTANCE, REAL_INSTANCE } from '@/api/chronosApi';
import { isSolvedSolution, SolvedSolution, toQualityView } from '@/adapters/solution';
import { PrintedBaseline } from '@/adapters/realInstance';
import { EdgeList, EnrichedSession, buildEnrichedSessions, facultyLoad, hardRuleViolations, labelsFor } from '@/adapters/timetable';
import { loadLimitHours } from '@/lib/wording';
/**
 * Every teacher's hours as solver/scoring.py counts them on the committed solution: its `taught`
 * map, read from `_timetable` and not from this project's TypeScript, so the test does not trust
 * the code it checks. Regenerate from the repository root when the committed instance changes:
 *   python -c "import json; from solver.scoring import _timetable; from solver.slots import SlotId; d='data/instances/even-2025-26/'; s=json.load(open(d+'solution.json')); t=_timetable(json.load(open(d+'edge_list.json')), {a['session_id']: SlotId(a['day'], a['period']) for a in s['assignment']}); print(json.dumps({f: {'scheduled': sum(1 for x in v.values() if x), 'fixed': sum(1 for x in v.values() if x is None), 'total': len(v)} for f, v in sorted(t.taught.items())}, indent=2))"
 */
import solverHours from './solver_faculty_hours.even-2025-26.json';

let edgeList: EdgeList;
let solution: SolvedSolution;
let sessions: EnrichedSession[];
let printed: PrintedBaseline;
let printedSessions: EnrichedSession[];
beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  const labels = labelsFor(await files.getDisplay(REAL_INSTANCE));
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  sessions = buildEnrichedSessions(solution.assignment, edgeList, labels);
  printed = (await files.getPrintedBaseline(PRINTED_INSTANCE))!;
  printedSessions = buildEnrichedSessions(printed.assignment, edgeList, labels);
});

/** "6 faculty members above 16 h a week - fac-a 18 h, fac-b 17 h.": who the solver flags, and at what. */
function flagged(explanation: string): Record<string, number> {
  const list = explanation.split(' - ')[1] ?? '';
  return Object.fromEntries([...list.matchAll(/(fac-[a-z0-9-]+) (\d+) h/g)].map((m) => [m[1], Number(m[2])]));
}
const loadRule = (rules: ReturnType<typeof toQualityView>['rules']) => {
  const rule = rules.find((r) => r.rule_id === 'S-LOAD16');
  if (rule?.status !== 'evaluated') throw new Error('S-LOAD16 not evaluated');
  return rule;
};

describe('facultyLoad counts as the solver’s S-LOAD16 counts (committed even-2025-26 files)', () => {
  it('gives every teacher the solver’s hours, in both parts', () => {
    const teachers = Object.keys(solverHours) as Array<keyof typeof solverHours>;
    expect(teachers).toHaveLength(37);
    for (const id of teachers) {
      const { scheduled, fixed, total } = facultyLoad(id, sessions, edgeList);
      expect({ id, scheduled, fixed, total }).toEqual({ id, ...solverHours[id] });
    }
  });

  it('matches the teachers and hours solution.json flags, and only those', () => {
    const rule = loadRule(toQualityView(solution).rules);
    const limit = loadLimitHours(rule)!;
    const hours = flagged(rule.explanation);
    expect(Object.keys(hours)).toHaveLength(rule.raw);
    const over = Object.keys(solverHours).filter((id) => facultyLoad(id, sessions, edgeList).total > limit);
    expect(over.sort()).toEqual(Object.keys(hours).sort());
    for (const id of over) expect(facultyLoad(id, sessions, edgeList).total).toBe(hours[id]);
  });

  it('Azman Qureshi: 6 h scheduled + 12 h fixed items = 18 h', () => {
    expect(facultyLoad('fac-azman-qureshi', sessions, edgeList)).toMatchObject({ scheduled: 6, fixed: 12, total: 18 });
  });

  it('counts a slot once: the printed timetable flags who its report flags, though clashing sessions overlap', () => {
    const rule = loadRule(printed.quality.rules);
    const hours = flagged(rule.explanation);
    const limit = loadLimitHours(rule)!;
    const over = Object.keys(solverHours).filter((id) => facultyLoad(id, printedSessions, edgeList).total > limit);
    expect(over.sort()).toEqual(Object.keys(hours).sort());
    // Kailas Devadkar's two printed OS lectures share a slot: 2 theory periods, 1 teaching hour
    const clash = facultyLoad('fac-kailas-devadkar', printedSessions, edgeList);
    expect(clash.theory + clash.practical).toBeGreaterThan(clash.scheduled);
  });

  it('a pin on a non-teaching period, or on a slot a session holds too, adds nothing', () => {
    const s = sessions.find((x) => x.facultyId === 'fac-azman-qureshi')!;
    const pins = [
      { day: 0, period: 2, faculty_ids: [s.facultyId], room_ids: [], cohort_ids: [] },
      { day: s.day, period: s.wallClockPeriod, faculty_ids: [s.facultyId], room_ids: [], cohort_ids: [] },
    ];
    const noPins = { ...edgeList, pinned_occupancy: [] };
    const before = facultyLoad(s.facultyId, sessions, noPins);
    expect(before.fixed).toBe(0);
    expect(facultyLoad(s.facultyId, sessions, { ...noPins, pinned_occupancy: pins })).toEqual(before);
  });
});

describe('the weekly limit is read from the solver’s sentence (no contract field carries it)', () => {
  it('reads the limit from the committed solution.json and printed report: a change of wording fails here', () => {
    // solver/rules/quality_rules.yaml holds the value; the frontend cannot read it, the test can
    const yaml = readFileSync(resolve(__dirname, '../../../../solver/rules/quality_rules.yaml'), 'utf8');
    const threshold = Number(yaml.match(/threshold_hours:\s*(\d+(?:\.\d+)?)/)?.[1]);
    expect(threshold).toBe(16);
    expect(loadLimitHours(loadRule(toQualityView(solution).rules))).toBe(threshold);
    expect(loadLimitHours(loadRule(printed.quality.rules))).toBe(threshold);
  });
});

describe('hardRuleViolations: the count solver.validate.validate_slot_placements gives', () => {
  it('gives the printed timetable the report’s number and the committed solution none', () => {
    expect(printed.violations.length).toBe(36);
    expect(hardRuleViolations(printed.assignment, edgeList)).toBe(printed.violations.length);
    expect(hardRuleViolations(solution.assignment, edgeList)).toBe(0);
  });

  it('counts a placement that breaks a rule', () => {
    const lecture = edgeList.sessions.find((s) => s.duration_periods === 1 && !edgeList.lab_blocks.some((b) => b.session_ids.includes(s.id)))!;
    const neighbour = edgeList.edges.find((e) => e.u === lecture.id)!.v;
    const at = solution.assignment.find((a) => a.session_id === neighbour)!;
    const clashing = solution.assignment.map((a) => (a.session_id === lecture.id ? { ...a, day: at.day, period: at.period } : a));
    expect(hardRuleViolations(clashing, edgeList)).toBeGreaterThan(0);
  });
});
