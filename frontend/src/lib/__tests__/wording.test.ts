import { describe, it, expect, beforeAll } from 'vitest';
import type { AuditEntry, RepairChange } from '@/api/chronosApi';
import { MockChronosApiClient, REAL_INSTANCE } from '@/api/chronosApi';
import type { QualityRule } from '@/adapters/solution';
import { EdgeList, Labels, labelsFor, slotsText } from '@/adapters/timetable';
import {
  ANOMALY_CATEGORY_LABELS,
  CONSTRAINT_KIND_LABELS,
  RULE_WORDING,
  anomalyCategoryLabel,
  auditActionLabel,
  auditSentence,
  changePhrase,
  constraintKindLabel,
  humanise,
  loadLimitHours,
  overLimitText,
  readableSolverText,
  ruleResult,
  ruleWording,
} from '@/lib/wording';

describe('readableSolverText: the solver’s explanation for reading', () => {
  it('names faculty and cohort ids it knows, keeps the others, and shows periods and times the UI’s way', () => {
    const names: Record<string, string> = { 'fac-jignesh-sisodia': 'Jignesh Sisodia', 'coh-se-b-c': 'SE-Comp B batch C' };
    expect(
      readableSolverText(
        '2 faculty members above 16 h a week - fac-jignesh-sisodia 17 h, fac-someone-else 18 h; coh-se-b-c: Friday 11.15-12.15 at P3.',
        (id) => names[id] ?? null
      )
    ).toBe(
      '2 faculty members above 16 h a week - Jignesh Sisodia 17 h, fac-someone-else 18 h; SE-Comp B batch C: Friday 11:15 AM – 12:15 PM at T3.'
    );
    // without names only displayText applies
    expect(readableSolverText('fac-a at P0')).toBe('fac-a at T0');
  });
});

const evaluated = (rule_id: string, weight: number, raw: number, explanation = 'as written'): Extract<QualityRule, { status: 'evaluated' }> => ({
  rule_id,
  status: 'evaluated',
  weight,
  raw,
  penalty: weight * raw,
  explanation,
});

describe('quality rule wording (D34 ids; numbers are the solver’s)', () => {
  it('has a plain title and an everyday sentence for each of the four rules', () => {
    expect(Object.keys(RULE_WORDING).sort()).toEqual(['FAC_LOAD_IMBALANCE', 'S-B2B', 'S-GAP', 'S-LOAD16']);
    for (const words of Object.values(RULE_WORDING)) {
      expect(words.title).not.toMatch(/[A-Z]{2,}|_/);
      expect(words.meaning).toMatch(/^[A-Z].*\.$/);
    }
    expect(ruleWording('S-GAP').title).toBe("Students' free periods");
  });

  it('says what was found and what it cost, from raw, penalty and weight as given', () => {
    expect(ruleResult(evaluated('S-GAP', 2, 3))).toBe('Found 3 free periods → −6 points (2 points each)');
    expect(ruleResult(evaluated('S-LOAD16', 1, 1))).toBe('Found 1 teacher → −1 point (1 point each)');
    expect(ruleResult(evaluated('FAC_LOAD_IMBALANCE', 0.5, 101))).toBe('Found 101 hours → −50.5 points (0.5 points each)');
    expect(ruleResult(evaluated('S-B2B', 1, 0))).toBe('Found 0 pairs of periods → no points lost');
    // the solver's penalty is shown as it is, never recomputed from weight × raw
    expect(ruleResult({ ...evaluated('S-GAP', 2, 3), penalty: 7 })).toBe('Found 3 free periods → −7 points (2 points each)');
    expect(ruleResult({ rule_id: 'S-LOAD16', status: 'not_evaluated', weight: 1, reason: 'too few sessions' })).toBe(
      'Not checked: too few sessions'
    );
  });

  it('falls back to the id in words for a rule it does not know', () => {
    expect(ruleWording('NEW_RULE').title).toBe('New rule');
    expect(ruleResult(evaluated('NEW_RULE', 1, 2))).toBe('Found 2 cases → −2 points (1 point each)');
  });
});

describe('the weekly load limit, as the solver’s S-LOAD16 states it (D11)', () => {
  it('reads the limit from either of the solver’s sentences', () => {
    expect(loadLimitHours(evaluated('S-LOAD16', 1, 6, '6 faculty members above 16 h a week - fac-a 18 h.'))).toBe(16);
    expect(loadLimitHours(evaluated('S-LOAD16', 1, 0, 'No faculty member teaches more than 16 h a week.'))).toBe(16);
  });

  it('knows no limit when the rule was not evaluated or not reported', () => {
    expect(loadLimitHours(undefined)).toBeNull();
    expect(loadLimitHours({ rule_id: 'S-LOAD16', status: 'not_evaluated', weight: 1, reason: 'the 16 h target' })).toBeNull();
  });

  it('warns in words only above the limit', () => {
    expect(overLimitText(17, 16)).toBe('Over 16 h limit: 17 h');
    expect(overLimitText(16, 16)).toBeNull();
    expect(overLimitText(12, 16)).toBeNull();
    expect(overLimitText(30, null)).toBeNull();
  });
});

describe('code tables: plain words with a fallback', () => {
  let categories: string[] = [];
  beforeAll(async () => {
    const report = await new MockChronosApiClient().getAnomalies(REAL_INSTANCE);
    categories = [...new Set(report!.anomalies.map((a) => a.category))];
  });

  it('names every anomaly category of the real report', () => {
    expect(categories.length).toBe(50);
    expect(categories.filter((c) => !(c in ANOMALY_CATEGORY_LABELS))).toEqual([]);
    expect(anomalyCategoryLabel('excluded_item')).toBe('Item kept fixed, not rescheduled');
    expect(anomalyCategoryLabel('frozen_out_of_scope')).toBe('Other programme’s session blocks a teacher or room');
  });

  it('names each of the contract’s ten constraint kinds', () => {
    expect(Object.keys(CONSTRAINT_KIND_LABELS)).toHaveLength(10);
    expect(constraintKindLabel('PINNED_BLOCK')).toBe('A fixed item already holds this time');
    expect(constraintKindLabel('LAB_CONTIGUITY')).toBe('A lab must take two periods in a row');
    expect(constraintKindLabel('ROOM_OCCUPANCY')).toBe('A room and one of its parts would be used at once');
  });

  it('falls back to the code in words', () => {
    expect(humanise('frozen_out_of_scope')).toBe('Frozen out of scope');
    expect(anomalyCategoryLabel('a_new_category')).toBe('A new category');
    expect(constraintKindLabel('SOMETHING_NEW')).toBe('Something new');
    expect(auditActionLabel('clear_changes')).toBe('Accepted changes cleared');
    expect(auditActionLabel('export_pdf')).toBe('Export pdf');
  });
});

describe('slotsText: a day’s consecutive periods as one run', () => {
  it('groups by day', () => {
    expect(slotsText([{ day: 1, period: 6 }, { day: 1, period: 7 }])).toBe('Tuesday T6–T7');
    expect(slotsText([{ day: 4, period: 6 }, { day: 4, period: 0 }, { day: 1, period: 5 }])).toBe('Friday T0, Friday T6, Tuesday T5');
  });
});

describe('auditSentence: an audit row as a sentence (real names from display.json)', () => {
  let edgeList: EdgeList;
  let labels: Labels;
  beforeAll(async () => {
    const files = new MockChronosApiClient();
    edgeList = await files.getEdgeList(REAL_INSTANCE);
    labels = labelsFor(await files.getDisplay(REAL_INSTANCE));
  });
  const describeChange = (c: RepairChange) => changePhrase(c, edgeList, labels);
  const row = (id: number, action: string, detail: Record<string, unknown> | null, actor = 'Nidhi'): AuditEntry => ({
    id,
    actor,
    action,
    timestamp: '2026-10-27T09:31:36Z',
    detail,
  });
  // backend/app/service.py logs a change's slots as [day, period] pairs
  const repair = row(2, 'repair', {
    instance_id: REAL_INSTANCE,
    job_id: 'job-1',
    change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [[1, 6], [1, 7]] },
    status: 'solved',
  });
  const accept = row(3, 'accept', { instance_id: REAL_INSTANCE, job_id: 'job-1', base: 'committed' });

  it("names an accepted repair's change from its repair row, with the actor's role when known", () => {
    expect(auditSentence(accept, [accept, repair], describeChange, 'Administrator')).toBe(
      "Nidhi (administrator) accepted the repair for Swapnali Kurhade's absence on Tuesday T6–T7."
    );
    expect(auditSentence(accept, [accept], describeChange)).toBe('Nidhi accepted a repair.');
  });

  it('says what a repair asked for and how it ended', () => {
    expect(auditSentence(repair, [repair], describeChange)).toBe(
      "Nidhi asked for a repair for Swapnali Kurhade's absence on Tuesday T6–T7. A timetable was found."
    );
    const move = row(4, 'repair', {
      change: { kind: 'move_session', session_id: 'obs-t0-r1-c3-l0', day: 2, period: 1, room_id: 'room-605' },
      status: 'infeasible',
    });
    expect(auditSentence(move, [move], describeChange)).toBe(
      'Nidhi asked for a repair for moving CE207 · SE-Comp A · Anant Nimkar (AVN) to Wednesday T1. No timetable is possible with it.'
    );
  });

  it('names a substitution by the new teacher and the session, without the teacher it replaces', () => {
    const sub = row(11, 'repair', {
      change: { kind: 'substitute_faculty', session_id: 'obs-t0-r1-c3-l0', faculty_id: 'fac-prasenjit-bhavathankar' },
      status: 'solved',
    });
    expect(auditSentence(sub, [sub], describeChange)).toBe(
      'Nidhi asked for a repair for Prasenjit Bhavathankar teaching CE207 · SE-Comp A instead. A timetable was found.'
    );
  });

  it('writes sign-ins, solves and clears as sentences', () => {
    expect(auditSentence(row(5, 'login', { success: true }), [], describeChange)).toBe('Nidhi signed in.');
    expect(auditSentence(row(6, 'login', { success: false }, 'mallory'), [], describeChange)).toBe('A sign-in as mallory failed.');
    expect(auditSentence(row(7, 'solve', { status: 'timeout', time_limit_s: 300 }), [], describeChange)).toBe(
      'Nidhi asked the solver to generate a timetable. It stopped at its time limit without an answer.'
    );
    expect(auditSentence(row(8, 'solve', { status: 'solved', stale: true }), [], describeChange)).toBe(
      'Nidhi asked the solver to generate a timetable. A timetable was found. It was not made official: the accepted changes changed while it ran.'
    );
    expect(auditSentence(row(9, 'clear_changes', { cleared: 3, official: 'x' }), [], describeChange)).toBe(
      'Nidhi cleared 3 accepted changes; later timetables no longer include them.'
    );
  });

  it('falls back to the action in words for an action it does not know', () => {
    expect(auditSentence(row(10, 'export_pdf', null), [], describeChange)).toBe('Nidhi: Export pdf.');
  });
});
