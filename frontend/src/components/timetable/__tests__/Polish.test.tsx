import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { HttpChronosApiClient, MockChronosApiClient, PRINTED_INSTANCE, REAL_INSTANCE, setSession, storeInstance } from '@/api/chronosApi';
import { SolvedSolution, isSolvedSolution } from '@/adapters/solution';
import { roomOccupancies } from '@/adapters/rooms';
import * as timetable from '@/adapters/timetable';
import { Display, EdgeList, EnrichedSession, buildEnrichedSessions, labelsFor, slotText } from '@/adapters/timetable';
import { formatScore, formatScoreChange } from '@/lib/format';
import { LoginScreen } from '@/components/auth/LoginScreen';
import {
  clearChangesText,
  explanationItems,
  methodText,
  overLimitItem,
  readableItem,
  repairInsteadText,
  repairStatusText,
  ruleResult,
  solveStatusText,
} from '@/lib/wording';
import type { UserRole } from '@/types/roles';

// S14t: the remaining frontend findings of the audit, on the real instance's files
let real: Record<string, unknown>;
let edgeList: EdgeList;
let display: Display;
let solution: SolvedSolution;
let sessions: EnrichedSession[];
beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  display = (await files.getDisplay(REAL_INSTANCE))!;
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  sessions = buildEnrichedSessions(solution.assignment, edgeList, labelsFor(display));
  real = { 'edge-list': edgeList, display, anomalies: await files.getAnomalies(REAL_INSTANCE), solution };
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function mockBackend() {
  const state = { posted: [] as unknown[], substitutes: null as unknown };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
    if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
      state.posted.push(JSON.parse(String(init?.body)));
      return json({ job_id: 'rep-1', status: 'queued' }, 202);
    }
    if (url === '/api/jobs/rep-1') return json({ id: 'rep-1', instance_id: REAL_INSTANCE, kind: 'repair', time_limit_s: 300, status: 'queued' });
    if (url.startsWith('/api/audit')) return json([]);
    if (url === `/api/instances/${REAL_INSTANCE}/changes`) return json([]);
    if (url === `/api/instances/${REAL_INSTANCE}/edge-list/current`) return json(edgeList);
    if (url.startsWith(`/api/instances/${REAL_INSTANCE}/sessions/`)) return json(state.substitutes);
    const file = url.match(new RegExp(`^/api/instances/${REAL_INSTANCE}/(.+)$`))?.[1];
    return file && file in real ? json(real[file]) : json({ detail: 'Not Found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { state, fetchMock };
}

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  setSession(null);
});

const open = async (role: UserRole = 'administrator', link: { facultyId?: string; cohortId?: string } = {}) => {
  const backend = mockBackend();
  setSession({ username: `test-${role}`, token: `token-${role}`, role, ...link });
  render(<App client={new HttpChronosApiClient('/api')} />);
  await screen.findByTestId('period-clock-0');
  return backend;
};

const openStatic = async () => {
  render(<App client={new MockChronosApiClient()} />);
  await screen.findByTestId('timetable-grid');
  fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
  await screen.findByTestId('period-clock-0');
};

const BOTH_MODES = [
  ['static', () => openStatic()],
  ['http', () => open()],
] as const;

const lecture = () => sessions.find((s) => !s.labBlockId && s.durationPeriods === 1 && !s.isPinned && !s.isCombinedDivision)!;
const card = (s: EnrichedSession) => screen.getByTestId(`session-cell-${s.sessionId}`);
const press = (key: string, code = key) => fireEvent.keyDown(document.activeElement ?? document.body, { key, code });

describe('1. the session details window', () => {
  it.each(BOTH_MODES)('%s: focus moves in, Tab stays inside, Escape closes, focus goes back to the card', async (_mode, openIt) => {
    await openIt();
    const s = card(lecture());
    s.focus();
    press('Enter');
    const dialog = await screen.findByRole('dialog');
    expect(dialog.contains(document.activeElement)).toBe(true);
    const buttons = within(dialog).getAllByRole('button');
    const [first, last] = [buttons[0], buttons[buttons.length - 1]];
    expect(first).toHaveFocus();

    press('Tab', 'Tab');
    fireEvent.keyDown(first, { key: 'Tab', code: 'Tab', shiftKey: true });
    expect(last).toHaveFocus();
    fireEvent.keyDown(last, { key: 'Tab', code: 'Tab' });
    expect(first).toHaveFocus();
    // focus somehow outside comes back in
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(document.body, { key: 'Tab', code: 'Tab' });
    expect(dialog.contains(document.activeElement)).toBe(true);

    fireEvent.keyDown(document.activeElement!, { key: 'Escape', code: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(s).toHaveFocus();
  });

  it('a read-only card opens with Enter or Space too, and Close returns the focus', async () => {
    await open('faculty', { facultyId: 'fac-anant-nimkar' });
    const s = sessions.find((x) => x.facultyId === 'fac-anant-nimkar' && !x.labBlockId)!;
    const c = card(s);
    expect(c).toHaveAttribute('tabindex', '0');
    c.focus();
    press(' ', 'Space');
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByText('Close'));
    expect(c).toHaveFocus();
  });
});

describe('2. "Show where" as a list', () => {
  it('splits every form of the solver\'s explanation; a sentence with no list stays one', () => {
    expect(explanationItems('13 idle teaching periods - coh-a: Friday 11.15-12.15; coh-b: Monday 09.00-10.00, Monday 10.00-11.00.')).toEqual([
      'coh-a: Friday 11.15-12.15',
      'coh-b: Monday 09.00-10.00, Monday 10.00-11.00',
    ]);
    expect(explanationItems('2 faculty members above 16 h a week - fac-a 18 h, fac-b 17 h.')).toEqual(['fac-a 18 h', 'fac-b 17 h']);
    // one item with a comma inside: not a comma-separated list
    expect(explanationItems('1 idle teaching periods - coh-a: Friday 11.15-12.15, Friday 12.15-13.15.')).toHaveLength(1);
    expect(explanationItems('Daily load spreads sum to 2 h - fac-a 4 h on Monday, 2 h on Tuesday.')).toEqual(['fac-a 4 h on Monday, 2 h on Tuesday']);
    expect(explanationItems('No faculty member teaches more than 16 h a week.')).toEqual(['No faculty member teaches more than 16 h a week.']);
    expect(overLimitItem('fac-a 18 h')).toEqual({ who: 'fac-a', hours: 18 });
    expect(overLimitItem('fac-a 4 h on Monday, 2 h on Tuesday')).toBeNull();
    expect(readableItem('fac-a Monday 09.00-10.00', () => 'Ana (A)')).toBe('Ana (A): Monday 9:00 AM – 10:00 AM');
  });

  it.each(BOTH_MODES)('%s: first 10, then "Show all N"; a list of 10 or fewer has no button', async (_mode, openIt) => {
    await openIt();
    const uneven = within(screen.getByTestId('quality-rule-FAC_LOAD_IMBALANCE'));
    const rule = solution.quality.breakdown.find((r) => r.rule_id === 'FAC_LOAD_IMBALANCE') as { explanation: string };
    const all = explanationItems(rule.explanation).length;
    expect(all).toBeGreaterThan(10);
    expect(uneven.getAllByTestId('rule-finding')).toHaveLength(10);
    // no ids, and no run-on sentence
    expect(uneven.getByTestId('rule-findings-FAC_LOAD_IMBALANCE').textContent).not.toMatch(/fac-|;/);
    fireEvent.click(uneven.getByText(`Show all ${all}`));
    expect(uneven.getAllByTestId('rule-finding')).toHaveLength(all);
    fireEvent.click(uneven.getByText('Show fewer'));
    expect(uneven.getAllByTestId('rule-finding')).toHaveLength(10);
    expect(within(screen.getByTestId('quality-rule-S-LOAD16')).queryByTestId('rule-findings-toggle-S-LOAD16')).not.toBeInTheDocument();
  });

  it.each(BOTH_MODES)('%s: teachers over 16 h are in red with the over-limit wording, each by name', async (_mode, openIt) => {
    await openIt();
    const items = within(screen.getByTestId('quality-rule-S-LOAD16')).getAllByTestId('rule-finding');
    const rule = solution.quality.breakdown.find((r) => r.rule_id === 'S-LOAD16') as { raw: number };
    expect(items).toHaveLength(rule.raw);
    const nile = items.find((i) => i.textContent?.includes('Amey Ganesh Nile'))!;
    expect(nile).toHaveTextContent('Amey Ganesh Nile (AGN): Over 16 h limit: 18 h');
    expect(within(nile).getByTestId('load-over-limit')).toHaveClass('text-destructive');
  });
});

describe('3. text is never cut', () => {
  it.each(BOTH_MODES)('%s: nothing is cut with an ellipsis; the method wraps in full', async (_mode, openIt) => {
    await openIt();
    expect(document.querySelectorAll('.truncate, .text-ellipsis, [class*="line-clamp"]')).toHaveLength(0);
    expect(screen.getByTestId('quality-method-code')).toHaveTextContent(solution.metadata.algorithm);
    expect(screen.getByTestId('quality-method-code')).toHaveClass('break-normal');
  });

  it.each(BOTH_MODES)('%s: where a card lists only a few classes, the full list shows on hover and keyboard focus', async (_mode, openIt) => {
    await openIt();
    const more = screen.getAllByTestId('pinned-more')[0];
    expect(more).toHaveAttribute('tabindex', '0');
    expect(more).toHaveTextContent(/and \d+ more/);
    const list = within(more).getByTestId('pinned-more-list');
    expect(list).toHaveAttribute('role', 'tooltip');
    expect(list.className).toContain('group-focus/more:block');
    expect(list.className).toContain('group-hover/more:block');
    expect(more.getAttribute('aria-label')).toContain(list.textContent!);
  });
});

describe('4. plain words', () => {
  it('says how a timetable was made in words, for each algorithm string the solver writes', () => {
    expect(methodText('backtracking(forward-checking, mrv) + local-search(simulated-annealing, moves=1000000, seed=0)')).toBe(
      'A step-by-step search that undoes any choice leading to a clash, then improved by trying many small changes'
    );
    expect(methodText('freeze-and-expand(rings=2, freed=4, nodes=9)')).toMatch(/^Repaired around the change/);
    expect(methodText('freeze-and-expand(pre-check) + mus-extraction(deletion-based)')).toMatch(/rules that cannot all hold$/);
    expect(methodText('some-new-method(a=1)')).toBe('Some new method');
  });

  it('job messages and the clear confirmation use no solver words', () => {
    const words = [
      solveStatusText('queued', {}),
      solveStatusText('running', { phase: 'improve' }),
      solveStatusText('running', { phase: 'search' }),
      solveStatusText('infeasible', {}),
      repairStatusText('queued', { accepted: false, waiting: false }),
      repairStatusText('queued', { accepted: false, waiting: true }),
      repairStatusText('infeasible', { accepted: false, waiting: false }),
      clearChangesText(3),
      clearChangesText(1),
    ].join(' ');
    expect(words).not.toMatch(/Running|\(improve\)|Infeasible|worker|committed|solver/);
    expect(solveStatusText('running', { phase: 'improve' })).toBe('Improving the timetable it found.');
    expect(clearChangesText(1)).toContain('Remove the accepted change?');
    expect(clearChangesText(3)).toContain('Remove all 3 accepted changes?');
  });

  it.each(BOTH_MODES)('%s: none of the audit\'s jargon is left on the page; codes stay as small text', async (_mode, openIt) => {
    await openIt();
    const page = document.body.textContent!;
    for (const jargon of [/Time slots used, search backtracks/, /Periods contiguous/, /Running \(/, /Drag-and-Drop Enabled/, /Read-Only View/, /Full Union Cohort/, /Instance:/, /Fixed Slot/]) {
      expect(page).not.toMatch(jargon);
    }
    expect(screen.getByTestId('quality-method')).not.toHaveTextContent('backtracking(');
    expect(screen.getByTestId('quality-method-code')).toHaveClass('text-[11px]');
  });
});

describe('5. one way to write hours, scores and teachers', () => {
  it('a score always has one decimal and a true minus sign', () => {
    expect(formatScore(-15)).toBe('−15.0');
    expect(formatScore(21.5)).toBe('21.5');
    expect(formatScore(-0.04)).toBe('0.0');
    expect(formatScoreChange(1.5)).toBe('+1.5');
    expect(formatScoreChange(-2)).toBe('−2.0');
    expect(formatScoreChange(0)).toBe('+0.0');
  });

  it('points lost have one decimal too; a day-spread rule counts in h', () => {
    const rule = { rule_id: 'FAC_LOAD_IMBALANCE', status: 'evaluated', weight: 0.5, raw: 106, penalty: 53, explanation: '' } as const;
    expect(ruleResult(rule)).toBe('Found 106 h → −53.0 points (0.5 points each)');
  });

  it.each(BOTH_MODES)('%s: the score on the card has one decimal; "hrs/wk" and "hours a week" are gone', async (_mode, openIt) => {
    await openIt();
    expect(screen.getByTestId('quality-score')).toHaveTextContent(/^26\.5$/);
    expect(document.body.textContent).not.toMatch(/hrs\/wk|hours a week/);
  });

  it('a card names its teacher "Name (INITIALS)", the one way everywhere', () => {
    const labels = labelsFor(display);
    expect(timetable.facultyText(labels, 'fac-anant-nimkar')).toBe('Anant Nimkar (AVN)');
    const s = sessions.find((x) => x.facultyId === 'fac-anant-nimkar')!;
    expect(timetable.sessionTeacher(s)).toBe('Anant Nimkar (AVN)');
  });

  it.each(BOTH_MODES)('%s: a session card shows the name first, its initials in brackets', async (_mode, openIt) => {
    await openIt();
    const s = lecture();
    expect(card(s)).toHaveTextContent(timetable.sessionTeacher(s));
  });

  it('SD and SM are never alone: the room timetable and fixed items name the teacher (D38)', () => {
    const labels = labelsFor(display);
    const occupancies = roomOccupancies(sessions, edgeList, labels);
    const sharing = ['fac-sonali-dudhihalli', 'fac-surekha-dholay', 'fac-sudeep-mali', 'fac-suman-m'];
    for (const s of sessions.filter((x) => sharing.includes(x.facultyId))) {
      const row = occupancies.find((o) => o.sessionId === s.sessionId)!;
      expect(row.label).toContain(display.faculty[s.facultyId]);
    }
    // pins whose printed label has SD or SM alone
    let seen = 0;
    edgeList.pinned_occupancy.forEach((p, i) => {
      if (!/\b(SD|SM)\b/.test(display.pins[i].label) || p.faculty_ids.length === 0) return;
      seen += 1;
      for (const id of p.faculty_ids) {
        expect(timetable.pinName(`pin.${i}`, edgeList, labels)).toContain(display.faculty[id]);
      }
    });
    expect(seen).toBeGreaterThan(0);
  });
});

describe('7. a linked account stays on its timetable (D50)', () => {
  it.each([
    ['faculty', { facultyId: 'fac-anant-nimkar' }],
    ['student', { cohortId: 'coh-se-a' }],
  ] as const)('%s: the timetable picker is locked to the real one', async (role, link) => {
    await open(role, link);
    const picker = screen.getByLabelText('Select timetable');
    expect(picker).toBeDisabled();
    expect(picker).toHaveValue(REAL_INSTANCE);
  });

  it('a timetable stored by an earlier session is ignored', async () => {
    storeInstance('example');
    await open('faculty', { facultyId: 'fac-anant-nimkar' });
    expect(screen.getByLabelText('Select timetable')).toHaveValue(REAL_INSTANCE);
  });

  it('an account that is not linked can still switch, and so can static mode, which has no accounts', async () => {
    await open('faculty');
    expect(screen.getByLabelText('Select timetable')).toBeEnabled();
    document.body.innerHTML = '';
    await openStatic();
    expect(screen.getByLabelText('Select timetable')).toBeEnabled();
  });
});

describe('8. outline and keyboard', () => {
  const expectOutline = () => {
    const levels = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].map((h) => Number(h.tagName[1]));
    expect(levels[0]).toBe(1);
    expect(levels.filter((l) => l === 1)).toHaveLength(1);
    levels.forEach((level, i) => {
      if (i > 0) expect(level - levels[i - 1]).toBeLessThanOrEqual(1);
    });
  };

  it.each(BOTH_MODES)('%s: one h1, and headings never jump a level', async (_mode, openIt) => {
    await openIt();
    expectOutline();
  });

  it.each(['coordinator', 'faculty', 'student'] as const)('http, %s: the same', async (role) => {
    await open(role);
    expectOutline();
  });

  it('the login screen has its h1', () => {
    render(<LoginScreen client={new HttpChronosApiClient('/api')} expired={false} />);
    expect(screen.getByRole('heading', { level: 1, name: 'Chronos' })).toBeInTheDocument();
  });

  it('the details window keeps the outline', async () => {
    await openStatic();
    fireEvent.click(card(lecture()));
    expect(within(await screen.findByRole('dialog')).getByRole('heading', { level: 2 })).toBeInTheDocument();
  });

  it.each(BOTH_MODES)('%s: no empty-cell drop button unless a drag is on; a skip link comes first', async (_mode, openIt) => {
    await openIt();
    expect(screen.queryAllByTestId(/^drop-slot-/)).toHaveLength(0);
    const skip = screen.getByTestId('skip-to-timetable');
    expect(skip).toHaveAttribute('href', '#timetable');
    expect(document.getElementById('timetable')?.tagName).toBe('MAIN');
    expect(screen.getByTestId('skip-past-timetable')).toHaveAttribute('href', '#after-timetable');
    expect(document.getElementById('after-timetable')).toBeInTheDocument();
    const focusable = [...document.querySelectorAll<HTMLElement>('a[href], button, select, input, [tabindex="0"]')].filter((e) => !e.hasAttribute('disabled'));
    // the first tab stop of the page, before Log out in http mode
    expect(focusable[0]).toBe(skip);
  });

  it.each(['administrator', 'coordinator'] as const)('http, %s: Space picks a session up, a cell takes the focus, Enter sends the move', async (role) => {
    const { state } = await open(role);
    const s = lecture();
    const c = card(s);
    c.focus();
    fireEvent.keyDown(c, { key: ' ', code: 'Space' });
    const target = await screen.findByTestId('drop-slot-4-9');
    expect(screen.getAllByTestId(/^drop-slot-/).length).toBeGreaterThan(0);
    // during the drag only the dragged card and the drop targets are in the grid's tab order
    const inOrder = [...screen.getByTestId('timetable-grid').querySelectorAll('[tabindex="0"]')].filter((e) => !e.closest('[inert]'));
    expect(inOrder).toEqual([c]);
    act(() => target.focus());
    fireEvent.keyDown(target, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(screen.queryAllByTestId(/^drop-slot-/)).toHaveLength(0));
    // no clash at the target: posted as a repair; a clash: the refusal says why and nothing is posted
    await waitFor(() => expect(state.posted.length > 0 || !!screen.queryByTestId('rejection-alert')).toBe(true));
    if (state.posted.length) {
      expect(state.posted[0]).toMatchObject({ change: { kind: 'move_session', session_id: s.sessionId, day: 4, period: 9 } });
    }
  });

  it('static, the example: the same keys move a session; Escape cancels', async () => {
    render(<App client={new MockChronosApiClient()} />);
    await screen.findByTestId('timetable-grid');
    const draggable = screen.getAllByTestId(/^drag-handle-/)[0].closest<HTMLElement>('[data-session-id]')!;
    draggable.focus();
    fireEvent.keyDown(draggable, { key: ' ', code: 'Space' });
    await screen.findAllByTestId(/^drop-slot-/);
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });
    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' });
    await waitFor(() => expect(screen.queryAllByTestId(/^drop-slot-/)).toHaveLength(0));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('Enter opens the details instead of starting a drag', async () => {
    await open();
    const c = card(lecture());
    c.focus();
    fireEvent.keyDown(c, { key: 'Enter', code: 'Enter' });
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.queryAllByTestId(/^drop-slot-/)).toHaveLength(0);
  });
});

describe('9. "Nobody qualified is free" is not a dead end', () => {
  const openNoSubstitutes = async () => {
    const backend = await open();
    const s = lecture();
    backend.state.substitutes = { session_id: s.sessionId, faculty_id: s.facultyId, candidates: [], left_out: [] };
    fireEvent.click(card(s));
    fireEvent.click(within(await screen.findByRole('dialog')).getByTestId('find-substitute'));
    await screen.findByTestId('no-substitutes');
    return { ...backend, s };
  };

  it('offers the repair path, names the teacher, and fills in the form without sending anything', async () => {
    const { state, s } = await openNoSubstitutes();
    const offer = screen.getByTestId('repair-instead');
    expect(offer).toHaveTextContent(repairInsteadText(timetable.sessionTeacher(s)));
    fireEvent.click(offer);

    expect(screen.queryByTestId('substitute-panel')).not.toBeInTheDocument();
    const panel = within(screen.getByTestId('repair-panel'));
    expect(panel.getByLabelText('Unavailable teacher')).toHaveValue(s.facultyId);
    for (const period of s.periods) {
      expect(panel.getByLabelText(slotText(s.day, period))).toBeChecked();
    }
    const checked = screen.getByTestId('mark-unavailable').querySelectorAll('input[type="checkbox"]:checked');
    expect(checked).toHaveLength(s.periods.length);
    expect(state.posted).toHaveLength(0);
    expect(screen.getByTestId('mark-unavailable-button')).toHaveFocus();

    // it is one click from there, through the usual repair flow
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));
    await waitFor(() => expect(state.posted).toHaveLength(1));
    expect(state.posted[0]).toEqual({
      change: { kind: 'faculty_unavailable', faculty_id: s.facultyId, slots: s.periods.map((period) => ({ day: s.day, period })) },
    });
  });

  it('is not offered when someone qualified is free', async () => {
    const backend = await open();
    const s = lecture();
    backend.state.substitutes = {
      session_id: s.sessionId,
      faculty_id: s.facultyId,
      candidates: [{ faculty_id: 'fac-nataasha-raul', score_change: -2 }],
      left_out: [{ faculty_id: 'fac-sudhir-dhage', reasons: ['busy'], violations: [] }],
    };
    fireEvent.click(card(s));
    fireEvent.click(within(await screen.findByRole('dialog')).getByTestId('find-substitute'));
    await screen.findByTestId('substitute-fac-nataasha-raul');
    expect(screen.queryByTestId('repair-instead')).not.toBeInTheDocument();
    expect(screen.getByTestId('left-out-fac-sudhir-dhage')).toHaveTextContent('teaching then');
    expect(screen.getByTestId('substitute-panel')).toHaveFocus();
  });

  it('static mode has no substitute finder at all: it needs the backend', async () => {
    await openStatic();
    fireEvent.click(card(lecture()));
    expect(within(await screen.findByRole('dialog')).queryByTestId('find-substitute')).not.toBeInTheDocument();
  });
});

describe('10. generated types are LF', () => {
  const generated = resolve('src/types/generated');

  it('every generated file is LF and git is told to keep it so', () => {
    const files = readdirSync(generated);
    expect(files).toHaveLength(5);
    for (const f of files) expect(readFileSync(resolve(generated, f), 'utf8')).not.toContain('\r');
    expect(existsSync(resolve('../.gitattributes'))).toBe(true);
    expect(readFileSync(resolve('../.gitattributes'), 'utf8')).toMatch(/^frontend\/src\/types\/generated\/\*\* text eol=lf$/m);
  });

  it('the generator is asked for LF', () => {
    const pkg = JSON.parse(readFileSync(resolve('package.json'), 'utf8')) as { scripts: Record<string, string> };
    expect(pkg.scripts['gen:types']).toContain('--style.endOfLine lf');
  });
});

describe('11. dead code, clients and fetches', () => {
  it('the dead exports are gone', () => {
    expect('moveConflict' in timetable).toBe(false);
    const source = readFileSync(resolve('src/adapters/timetable.ts'), 'utf8');
    expect(source).not.toContain('EdgeListSession');
    expect(source).not.toContain('moveConflict');
  });

  it('the http client does not inherit the mock\'s methods', () => {
    const http = new HttpChronosApiClient('/api');
    expect(http).not.toBeInstanceOf(MockChronosApiClient);
    for (const name of ['setRejectMode', 'isRejectMode', 'setSimulatedOutcome', 'getSimulatedOutcome', 'generateTimetable', 'getSolvedSolution', 'getInfeasibleSolution']) {
      expect(name in http).toBe(false);
      expect(name in new MockChronosApiClient()).toBe(true);
    }
  });

  it('/edge-list is fetched once per page load, also through the printed view and back', async () => {
    const { fetchMock } = await open();
    const edgeListFetches = () => fetchMock.mock.calls.filter(([url]) => url === `/api/instances/${REAL_INSTANCE}/edge-list`);
    expect(edgeListFetches()).toHaveLength(1);
    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: PRINTED_INSTANCE } });
    await screen.findByTestId('printed-violations');
    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('generated-vs-printed');
    expect(edgeListFetches()).toHaveLength(1);
  });

  it('the mark-unavailable grid shows which periods the teacher teaches; the checkbox keeps its name', async () => {
    await open();
    const teacher = 'fac-anant-nimkar';
    const panel = within(screen.getByTestId('repair-panel'));
    expect(screen.queryByTestId('taught-key')).not.toBeInTheDocument();
    fireEvent.change(panel.getByLabelText('Unavailable teacher'), { target: { value: teacher } });

    const own = sessions.filter((s) => s.facultyId === teacher);
    expect(own.length).toBeGreaterThan(0);
    for (const s of own) {
      for (const period of s.periods) {
        expect(screen.getByTestId(`taught-${s.day}-${period}`)).toHaveTextContent('●');
        expect(panel.getByLabelText(slotText(s.day, period))).toHaveAccessibleDescription(expect.stringContaining(s.subjectCode));
      }
    }
    const pins = edgeList.pinned_occupancy.filter((p) => p.faculty_ids.includes(teacher));
    const taughtCells = new Set([
      ...own.flatMap((s) => s.periods.map((p) => `${s.day}-${p}`)),
      ...pins.map((p) => `${p.day}-${p.period}`),
    ]);
    expect(screen.getAllByTestId(/^taught-\d-\d$/)).toHaveLength(taughtCells.size);
    expect(screen.getByTestId('taught-key')).toHaveTextContent('teaches at this time');

    fireEvent.change(panel.getByLabelText('Unavailable kind'), { target: { value: 'room' } });
    expect(screen.queryAllByTestId(/^taught-\d-\d$/)).toHaveLength(0);
  });

  it('the browser bundle\'s fast-uri is past the advisories', () => {
    const lock = JSON.parse(readFileSync(resolve('package-lock.json'), 'utf8')) as { packages: Record<string, { version: string }> };
    const [major, minor, patch] = lock.packages['node_modules/fast-uri'].version.split('.').map(Number);
    expect(major * 1e6 + minor * 1e3 + patch).toBeGreaterThanOrEqual(3 * 1e6 + 1 * 1e3 + 9);
  });
});
