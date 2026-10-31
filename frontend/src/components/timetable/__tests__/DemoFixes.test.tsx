import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { GeneratedVsPrintedCard } from '../GeneratedVsPrintedCard';
import { SessionDetailModal } from '../SessionDetailModal';
import { TimetableGrid } from '../TimetableGrid';
import { HttpChronosApiClient, MockChronosApiClient, PRINTED_INSTANCE, REAL_INSTANCE, setSession, storedInstance } from '@/api/chronosApi';
import type { AuditEntry } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { SolvedSolution, isSolvedSolution, toQualityView } from '@/adapters/solution';
import { PrintedBaseline } from '@/adapters/realInstance';
import {
  Display,
  EdgeList,
  EnrichedSession,
  buildEnrichedSessions,
  checkMove,
  cohortOptions,
  hardRuleViolations,
  labelsFor,
} from '@/adapters/timetable';
import { parseSolution } from '@/api/contractValidation';
import { cohortListText, comparisonSentence, pinKindLabel, readableDiagnosisText, repairSummary } from '@/lib/wording';

// S14q: what an audit found would break or embarrass the demo. The real instance's files, as the backend serves them
let real: Record<string, unknown>;
let edgeList: EdgeList;
let display: Display;
let solution: SolvedSolution;
let sessions: EnrichedSession[];
let printed: PrintedBaseline;
beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  display = (await files.getDisplay(REAL_INSTANCE))!;
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  sessions = buildEnrichedSessions(solution.assignment, edgeList, labelsFor(display));
  printed = (await files.getPrintedBaseline(PRINTED_INSTANCE))!;
  real = { 'edge-list': edgeList, display, anomalies: await files.getAnomalies(REAL_INSTANCE), solution };
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const job = (fields: Record<string, unknown>) => ({
  id: 'rep-1',
  instance_id: REAL_INSTANCE,
  kind: 'repair',
  time_limit_s: 300,
  base: 'committed',
  status: 'queued',
  ...fields,
});

/** The backend with one repair job; the test sets what it says next. */
function mockBackend() {
  const state = {
    job: job({}) as Record<string, unknown>,
    solveJob: null as Record<string, unknown> | null,
    jobFails: false,
    repairFails: false,
    changes: [] as unknown[],
    audit: [] as AuditEntry[],
    substitutes: null as unknown,
    jobEdgeList: null as EdgeList | null,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
      if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
        return state.repairFails ? json({ detail: 'already unavailable then' }, 422) : json({ job_id: 'rep-1', status: 'queued' }, 202);
      }
      if (url === `/api/instances/${REAL_INSTANCE}/solve`) return json({ job_id: 'solve-1', status: 'queued' }, 202);
      if (url.startsWith('/api/audit')) return json(state.audit);
      if (url === `/api/instances/${REAL_INSTANCE}/changes`) {
        if (init?.method !== 'DELETE') return json(state.changes);
        const cleared = state.changes;
        state.changes = [];
        return json(cleared);
      }
      if (url === `/api/instances/${REAL_INSTANCE}/edge-list/current`) return json(edgeList);
      if (url === `/api/instances/${REAL_INSTANCE}/solution`) return json(solution);
      if (url.startsWith(`/api/instances/${REAL_INSTANCE}/sessions/`)) return json(state.substitutes);
      if (url === '/api/jobs/rep-1/accept') return json({ ...state.job, accepted_at: '2026-10-31T10:00:00Z' });
      if (url === '/api/jobs/rep-1/base-solution') return json(solution);
      if (url === '/api/jobs/rep-1/edge-list') return json(state.jobEdgeList ?? edgeList);
      if (url === '/api/jobs/rep-1') return state.jobFails ? json({ detail: 'gone' }, 404) : json(state.job);
      if (url === '/api/jobs/solve-1') return json(state.solveJob);
      const file = url.match(new RegExp(`^/api/instances/${REAL_INSTANCE}/(.+)$`))?.[1];
      return file && file in real ? json(real[file]) : json({ detail: 'Not Found' }, 404);
    })
  );
  return state;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});

const logIn = (role: UserRole) => setSession({ username: `test-${role}`, token: `token-${role}`, role });

const open = async (role: UserRole = 'administrator') => {
  const backend = mockBackend();
  logIn(role);
  render(<App client={new HttpChronosApiClient('/api')} />);
  await screen.findByTestId('period-clock-0');
  return backend;
};

const openStatic = async () => {
  render(<App client={new MockChronosApiClient()} />);
  await screen.findByTestId('timetable-grid');
  fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
  await screen.findByTestId('period-clock-0');
};

const BOTH_MODES = [
  ['static', () => openStatic()],
  ['http', () => open()],
] as const;

const status = () => screen.getByTestId('repair-status');
const form = () => screen.getByTestId('mark-unavailable') as HTMLFieldSetElement;

const markKurhade = () => {
  const panel = screen.getByTestId('repair-panel');
  fireEvent.change(within(panel).getByLabelText('Unavailable faculty member'), { target: { value: 'fac-swapnali-kurhade' } });
  fireEvent.click(within(panel).getByLabelText('Friday T0'));
  fireEvent.click(screen.getByTestId('mark-unavailable-button'));
};

/** The panel as it opens: no message, every control live, nothing picked. */
const expectAtStart = () => {
  expect(screen.queryByTestId('repair-status')).not.toBeInTheDocument();
  expect(screen.queryByTestId('discard-repair')).not.toBeInTheDocument();
  expect(screen.queryByTestId('infeasibility-panel')).not.toBeInTheDocument();
  expect(form()).toBeEnabled();
  expect(screen.getByLabelText('Unavailable faculty member')).toHaveValue('');
  expect(within(form()).getByLabelText('Friday T0')).not.toBeChecked();
  expect(screen.getByTestId('mark-unavailable-button')).toHaveTextContent('Mark unavailable and repair');
};

const infeasible = (sessionId: string, pin: number) =>
  parseSolution({
    schema_version: 'solution.v2',
    status: 'infeasible',
    diagnosis: {
      method: 'mus',
      minimal_conflicting_set: [
        {
          constraint_id: 'change',
          kind: 'FIXED_SLOT',
          description: `The change: ${sessionId} is moved to Mon P0 in room-601.`,
          entity_ids: [sessionId, 'room-601'],
          slots: [{ day: 0, period: 0 }],
        },
        {
          constraint_id: `pin.${pin}`,
          kind: 'PINNED_BLOCK',
          description: `Pinned occupancy ${pin} holds coh-se-a at Mon P0. Without it a timetable exists that uses it for coh-se-a.`,
          entity_ids: ['coh-se-a'],
          slots: [{ day: 0, period: 0 }],
        },
      ],
      suggested_relaxation: {
        constraint_id: `pin.${pin}`,
        description: 'Free cohort coh-se-a from the pinned occupancy at Mon P0.',
        action: { action_type: 'RELAX_PINNED_BLOCK', params: { slot: { day: 0, period: 0 }, entity_kind: 'cohort', entity_id: 'coh-se-a' } },
        verification: { status: 'restored', runtime_ms: 12 },
      },
      partial_placement: [],
      unplaced_session_ids: [sessionId],
    },
    metadata: { algorithm: 'freeze-and-expand(pre-check)', runtime_ms: 40, sessions_total: 156, sessions_assigned: 0, slots_used: null, backtracks: 0 },
  });

describe('X1, M7: every way a repair ends leaves the panel usable (http mode; static mode has no repairs)', () => {
  it('Discard of a proposal: back at the start, and a new repair polls again', async () => {
    const backend = await open();
    backend.job = job({ status: 'solved', solution: { ...solution, displaced: [] } });
    markKurhade();
    fireEvent.click(await screen.findByTestId('discard-repair'));
    await waitFor(expectAtStart);

    backend.job = job({ status: 'running', phase: 'repair' });
    markKurhade();
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'running'));
    backend.job = job({ status: 'timeout' });
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'timeout'), { timeout: 3000 });
  });

  it('infeasible: the diagnosis has a Discard, which returns the panel to its start', async () => {
    const backend = await open();
    backend.job = job({ status: 'infeasible', solution: infeasible(sessions[0].sessionId, 0) });
    markKurhade();
    await screen.findByTestId('infeasibility-panel');
    expect(form()).toBeEnabled();
    fireEvent.click(screen.getByTestId('discard-repair'));
    await waitFor(expectAtStart);
  });

  it('timeout: a Discard too (D33: still no diagnosis)', async () => {
    const backend = await open();
    backend.job = job({ status: 'timeout' });
    markKurhade();
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'timeout'));
    expect(screen.queryByTestId('infeasibility-panel')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('discard-repair'));
    await waitFor(expectAtStart);
  });

  it('a refused POST: the message and a Discard; the controls stay live', async () => {
    const backend = await open();
    backend.repairFails = true;
    markKurhade();
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'error'));
    expect(form()).toBeEnabled();
    fireEvent.click(screen.getByTestId('discard-repair'));
    await waitFor(expectAtStart);
  });

  it('a job that can no longer be read: the grid can be dragged again', async () => {
    const backend = await open();
    backend.jobFails = true;
    markKurhade();
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'error'));
    expect(form()).toBeEnabled();
    expect(screen.getAllByTestId(/^drop-slot-/).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId('discard-repair'));
    await waitFor(expectAtStart);
  });

  it('accept: the controls are live and nothing is left picked', async () => {
    const backend = await open();
    backend.job = job({ status: 'solved', solution: { ...solution, displaced: [] } });
    markKurhade();
    await screen.findByTestId('repair-summary');
    fireEvent.click(screen.getByTestId('accept-repair'));
    await waitFor(() => expect(status()).toHaveTextContent('Accepted: the repaired timetable is now the official one.'));
    expect(form()).toBeEnabled();
    expect(within(form()).getByLabelText('Friday T0')).not.toBeChecked();
    expect(screen.getByTestId('mark-unavailable-button')).toHaveTextContent('Mark unavailable and repair');
  });
});

describe('S3: "Accepted" holds only until the official timetable changes', () => {
  const acceptOne = async (backend: ReturnType<typeof mockBackend>) => {
    backend.job = job({ status: 'solved', solution: { ...solution, displaced: [] } });
    markKurhade();
    await screen.findByTestId('repair-summary');
    fireEvent.click(screen.getByTestId('accept-repair'));
    await waitFor(() => expect(status()).toHaveTextContent('Accepted:'));
  };

  it('Clear accepted changes removes it and leaves the panel usable', async () => {
    const backend = await open();
    backend.changes = [
      {
        job_id: 'rep-0',
        change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 4, period: 1 }] },
        requested_by: 'a',
        accepted_by: 'a',
        accepted_at: '2026-10-31T09:00:00Z',
      },
    ];
    await acceptOne(backend);
    fireEvent.click(await screen.findByTestId('clear-changes'));
    fireEvent.click(screen.getByTestId('confirm-clear-button'));
    await waitFor(expectAtStart);
  });

  it('a finished solve removes it', async () => {
    const backend = await open();
    await acceptOne(backend);
    backend.solveJob = { id: 'solve-1', instance_id: REAL_INSTANCE, kind: 'solve', time_limit_s: 300, status: 'solved', solution };
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'solved'));
    await waitFor(expectAtStart);
  });

  it('a stale solve, which changes nothing official, keeps it', async () => {
    const backend = await open();
    await acceptOne(backend);
    backend.solveJob = { id: 'solve-1', instance_id: REAL_INSTANCE, kind: 'solve', time_limit_s: 300, status: 'solved', solution, stale: true };
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-stale', 'true'));
    expect(status()).toHaveTextContent('Accepted:');
  });
});

describe('M1: a refused drop shows where the user is looking', () => {
  const dropRefused = () => {
    for (const s of sessions.filter((x) => !x.labBlockId && x.durationPeriods === 1)) {
      for (const day of [0, 1, 2, 3, 4]) {
        for (const period of [0, 1, 3, 4, 6, 7, 8, 9]) {
          const check = checkMove(edgeList, labelsFor(display), sessions, s.sessionId, day, period);
          const cell = screen.queryByTestId(`grid-cell-${day}-${period}`);
          if (check?.clashes.length && cell && !(day === s.day && period === s.wallClockPeriod)) {
            fireEvent.drop(cell, { dataTransfer: { getData: () => s.sessionId } });
            return;
          }
        }
      }
    }
    throw new Error('no refused move in the real timetable');
  };

  it('http: right above the grid, stuck to the window, announced and focused; Dismiss gives the focus back', async () => {
    await open();
    const before = screen.getByLabelText('Select instance');
    before.focus();
    dropRefused();
    const alert = await screen.findByTestId('rejection-alert');
    expect(alert).toHaveAttribute('role', 'alert');
    expect(document.activeElement).toBe(alert);
    expect(alert.className).toContain('sticky');
    expect(alert.nextElementSibling).toBe(screen.getByTestId('timetable-grid'));
    fireEvent.click(within(alert).getByText('Dismiss'));
    expect(screen.queryByTestId('rejection-alert')).not.toBeInTheDocument();
    expect(document.activeElement).toBe(before);
  });

  it('static: the same, on the example', async () => {
    render(<App client={new MockChronosApiClient()} />);
    await screen.findByTestId('timetable-grid');
    fireEvent.click(screen.getByTestId('toggle-reject-mode-button'));
    fireEvent.drop(screen.getByTestId('grid-cell-0-6'), { dataTransfer: { getData: () => 'sess-0006' } });
    const alert = await screen.findByTestId('rejection-alert');
    expect(document.activeElement).toBe(alert);
    expect(alert.nextElementSibling).toBe(screen.getByTestId('timetable-grid'));
  });
});

describe('M2: the workload card in the app', () => {
  const flagged = () => {
    const rule = toQualityView(solution).rules.find((r) => r.rule_id === 'S-LOAD16');
    if (rule?.status !== 'evaluated') throw new Error('S-LOAD16 not evaluated');
    return [...rule.explanation.matchAll(/(fac-[a-z0-9-]+) (\d+) h/g)].map((m) => [m[1], m[2]] as const);
  };
  const expectEveryFlaggedWarned = () => {
    expect(flagged()).toHaveLength(6);
    for (const [id, hours] of flagged()) {
      fireEvent.change(screen.getByLabelText('Select faculty persona'), { target: { value: id } });
      const warning = within(screen.getByTestId('faculty-workload-card')).getByTestId('load-over-limit');
      expect(warning).toHaveTextContent(`Over 16 h limit: ${hours} h`);
      expect(warning.className).toContain('text-destructive');
    }
  };

  it('static: every teacher the solution flags gets the red warning; Azman Qureshi shows both parts', async () => {
    await openStatic();
    fireEvent.click(screen.getByTestId('role-button-faculty'));
    expectEveryFlaggedWarned();
    fireEvent.change(screen.getByLabelText('Select faculty persona'), { target: { value: 'fac-azman-qureshi' } });
    expect(screen.getByTestId('workload-parts')).toHaveTextContent('18 h: 6 h scheduled + 12 h fixed items');
    expect(screen.getByTestId('workload-formula-badge')).toHaveTextContent('0T + 6P + 12 fixed = 18 hrs/wk');
  });

  it('a teacher’s own grid shows the fixed items the card counts, and no one else’s', async () => {
    await open('faculty');
    fireEvent.change(screen.getByLabelText('Select faculty persona'), { target: { value: 'fac-azman-qureshi' } });
    const cards = screen.getAllByTestId('pinned-block');
    expect(cards).toHaveLength(12);
    for (const card of cards) expect(card).toHaveTextContent('Teacher: ');
    expect(cards[0].textContent).toContain(display.faculty['fac-azman-qureshi']);
    expect(screen.queryAllByTestId(/^lunch-cell-/)).toHaveLength(0);
    fireEvent.change(screen.getByLabelText('Select faculty persona'), { target: { value: 'fac-anant-nimkar' } });
    expect(screen.queryAllByTestId('pinned-block')).toHaveLength(0);
  });

  it('http: the same; a teacher within the limit gets none', async () => {
    await open('faculty');
    expectEveryFlaggedWarned();
    fireEvent.change(screen.getByLabelText('Select faculty persona'), { target: { value: 'fac-anant-nimkar' } });
    expect(screen.getByTestId('workload-parts')).toHaveTextContent('14 h: 14 h scheduled + 0 h fixed items');
    expect(screen.queryByTestId('load-over-limit')).not.toBeInTheDocument();
  });

  it('a substitution proposal warns by the same count', async () => {
    const backend = await open('coordinator');
    const lecture = sessions.find((s) => s.facultyId === 'fac-jignesh-sisodia' && !s.labBlockId)!;
    backend.substitutes = { session_id: lecture.sessionId, faculty_id: lecture.facultyId, candidates: [{ faculty_id: 'fac-anant-nimkar', score_change: 0 }], left_out: [] };
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: lecture.cohortId } });
    fireEvent.click(screen.getByTestId(`session-cell-${lecture.sessionId}`));
    fireEvent.click(screen.getByTestId('find-substitute'));
    backend.job = job({ status: 'solved', change: { kind: 'substitute_faculty', session_id: lecture.sessionId, faculty_id: 'fac-anant-nimkar' }, solution: { ...solution, displaced: [] } });
    const after: EdgeList = JSON.parse(JSON.stringify(edgeList));
    after.sessions.find((s) => s.id === lecture.sessionId)!.faculty_id = 'fac-anant-nimkar';
    backend.jobEdgeList = after;
    fireEvent.click(await screen.findByTestId('substitute-fac-anant-nimkar'));
    const row = await screen.findByTestId('substitution-load-fac-jignesh-sisodia');
    expect(row).toHaveTextContent('+ 1 fixed = 17');
    expect(within(row).getAllByTestId('load-over-limit')[0]).toHaveTextContent('Over 16 h limit: 17 h');
  });
});

describe('M3: a lab batch card names its batch', () => {
  it.each(BOTH_MODES)('%s: SE-Comp A’s labs by display.json’s label', async (_mode, openIt) => {
    await openIt();
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: 'coh-se-a' } });
    const cards = screen.getAllByTestId(/^batch-session-/);
    expect(cards.length).toBeGreaterThan(0);
    expect(new Set(cards.map((c) => c.getAttribute('data-batch')))).toEqual(
      new Set(['SE-Comp A batch A', 'SE-Comp A batch B', 'SE-Comp A batch C', 'SE-Comp A batch D'])
    );
    expect(within(cards[0]).getByText(cards[0].getAttribute('data-batch')!)).toBeInTheDocument();
    expect(screen.queryByText('Batch')).not.toBeInTheDocument();
  });
});

describe('M4: all five days fit; a narrower window keeps its headers (measured at 1366 px in the browser check)', () => {
  it.each(BOTH_MODES)('%s: full width, a fixed layout that shares the width, text that wraps', async (_mode, openIt) => {
    await openIt();
    const grid = screen.getByTestId('timetable-grid');
    const table = grid.querySelector('table')!;
    expect(table.className).toContain('table-fixed');
    expect(table.className).toContain('w-full');
    expect(document.querySelector('.max-w-7xl')).toBeNull();
    expect(grid.querySelector('.whitespace-nowrap, .truncate')).toBeNull();
  });

  it('day headers and the period column are sticky; a narrow box scrolls by itself, a wide one with the page', () => {
    render(<TimetableGrid edgeList={edgeList} labels={labelsFor(display)} solution={null} />);
    expect(screen.getByTestId('day-header-4').className).toContain('sticky');
    expect(screen.getByTestId('day-header-4').className).toContain('top-0');
    expect(screen.getByTestId('period-cell-0').className).toContain('sticky');
    expect(screen.getByTestId('period-cell-0').className).toContain('left-0');
    const box = screen.getByTestId('timetable-grid').className;
    expect(box).toContain('overflow-auto');
    expect(box).toContain('max-h-[85vh]');
    expect(box).toContain('min-[1100px]:overflow-visible');
  });
});

describe('M5: fixed-item cards in plain words, in every role', () => {
  const INTERNAL = /\bD\d{2}\b|out_of_scope|\bfrozen\b|\bmdm\b|\bllc\b|\bhss\b/;

  it('words every kind in the real data, never a decision id or a raw kind', () => {
    for (const pin of display.pins) {
      if (pin.kind === 'lunch') continue; // lunch has its own cell
      const words = pinKindLabel(pin.kind, pin.decision);
      expect(words).toMatch(/^Fixed: /);
      expect(words).not.toMatch(INTERNAL);
    }
    expect(pinKindLabel('frozen', 'D44')).toBe('Fixed: taught by another department');
    expect(pinKindLabel('mdm')).toBe('Fixed: multidisciplinary minor course');
    expect(pinKindLabel('out_of_scope')).toBe('Fixed: session of another programme');
    expect(pinKindLabel('some_new_kind')).toBe('Fixed: some new kind');
    expect(pinKindLabel(null)).toBe('Fixed: cannot be moved');
  });

  it.each(['administrator', 'student'] as const)('%s, http: the PCS card has its kind and full teacher name', async (role) => {
    await open(role);
    fireEvent.change(screen.getByLabelText(role === 'student' ? 'Select student division' : 'Filter timetable by division'), {
      target: { value: 'coh-se-a' },
    });
    const cards = screen.getAllByTestId('pinned-block');
    const pcs = cards.find((c) => c.textContent?.includes('PCS / DN / 002'))!;
    expect(pcs).toHaveTextContent('Fixed: taught by another department');
    expect(pcs).toHaveTextContent(`Teacher: ${display.faculty['fac-deepak-nair']}`);
    for (const card of cards) {
      expect(within(card).getByTestId('pinned-kind').textContent).toMatch(/^Fixed: /);
      expect(card.textContent).not.toMatch(INTERNAL);
    }
  });

  it('static: the same words', async () => {
    await openStatic();
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: 'coh-se-a' } });
    const pcs = screen.getAllByTestId('pinned-block').find((c) => c.textContent?.includes('PCS / DN / 002'))!;
    expect(pcs).toHaveTextContent(`Teacher: ${display.faculty['fac-deepak-nair']}`);
    expect(pcs).not.toHaveTextContent('D44');
  });

  it('a card names a few cohorts, those in view first, and keeps the full list on hover', () => {
    expect(cohortListText(['a', 'b', 'c'])).toBe('a, b, c');
    expect(cohortListText(['a', 'b', 'c', 'd', 'e'])).toBe('a, b, c and 2 more');
    render(<TimetableGrid edgeList={edgeList} labels={labelsFor(display)} solution={null} cohortFilter="coh-se-a" />);
    const pcs = screen.getAllByTestId('pinned-block').find((c) => c.textContent?.includes('PCS / DN / 002'))!;
    expect(pcs).toHaveTextContent('Cohort: SE-Comp A, SE-Comp A batch A, SE-Comp A batch B and 2 more');
    expect(within(pcs).getByText(/^Cohort:/).getAttribute('title')).toContain('MDM-DBMS');
  });

  it('a teacher display.json has no name for shows by initials, never an id', () => {
    const noName = JSON.parse(JSON.stringify(display)) as Display;
    delete noName.faculty['fac-deepak-nair'];
    noName.initials['fac-deepak-nair'] = { SE: ['DN'] };
    render(<TimetableGrid edgeList={edgeList} labels={labelsFor(noName)} solution={null} cohortFilter="coh-se-a" />);
    const pcs = screen.getAllByTestId('pinned-block').find((c) => c.textContent?.includes('PCS / DN / 002'))!;
    expect(pcs).toHaveTextContent('Teacher: DN');
    expect(pcs).not.toHaveTextContent('fac-deepak-nair');
  });
});

describe('M6: the diagnosis is written with names', () => {
  const NAMES: Record<string, string> = {
    'obs-1': 'Operating Systems for SE-Comp A (Kailas Devadkar)',
    'room-601': 'room 601',
    'coh-se-a': 'SE-Comp A',
    'fac-a': 'Swapnali Kurhade (SK)',
    'pin.238': 'MDM-I lab /A /603-7',
  };
  const say = (text: string) => readableDiagnosisText(text, (id) => NAMES[id] ?? null);

  it('puts each sentence of solver/mus.py in words', () => {
    expect(say('The change: obs-1 is moved to Mon P0 in room-601.')).toBe('Operating Systems for SE-Comp A (Kailas Devadkar) moved to Monday T0 in room 601.');
    expect(say('The change: fac-a is unavailable at Fri P0, Fri P6.')).toBe('Swapnali Kurhade (SK) is unavailable at Friday T0, Friday T6.');
    expect(say('The change: room room-601 is closed at Mon P0.')).toBe('Room 601 is closed at Monday T0.');
    expect(say('Pinned occupancy 238 holds coh-se-a at Mon P0.')).toBe('MDM-I lab /A /603-7 holds SE-Comp A at Monday T0.');
    expect(say('Free cohort coh-se-a from the pinned occupancy at Mon P0.')).toBe('Free SE-Comp A from the fixed item at Monday T0.');
    expect(say('Make fac-a available at Fri P0.')).toBe('Make Swapnali Kurhade (SK) available at Friday T0.');
    expect(say('Room room-601 seats 40.')).toBe('Room 601 seats 40.');
    expect(say('Classify room room-601 as a lab.')).toBe('Classify room 601 as a lab.');
    expect(say('Sessions taught by fac-a and fac-a may not overlap.')).toBe('Sessions taught by Swapnali Kurhade (SK) and Swapnali Kurhade (SK) may not overlap.');
    expect(say('Lab block lab-1: obs-1 start together and run over the same contiguous periods.')).toBe(
      'These lab sessions start together and run over the same consecutive periods: Operating Systems for SE-Comp A (Kailas Devadkar).'
    );
    expect(say('Protected, never relaxed: pin.238.')).toBe('Protected, never relaxed: MDM-I lab /A /603-7.');
    expect(say('Swapnali Kurhade is unavailable all Tuesday.')).toBe('Swapnali Kurhade is unavailable all Tuesday.');
  });

  it('shortens a long list: a lunch holding 41 cohorts does not print 41 names', () => {
    const ids = Array.from({ length: 41 }, () => 'coh-se-a').join(', ');
    expect(say(`Pinned occupancy 238 holds ${ids} at Mon P4.`)).toBe(
      `MDM-I lab /A /603-7 holds ${Array(6).fill('SE-Comp A').join(', ')} and 35 more at Monday T4.`
    );
  });

  const openDiagnosis = async () => {
    const backend = await open();
    const s = sessions[0];
    backend.job = job({ status: 'infeasible', solution: infeasible(s.sessionId, 238) });
    markKurhade();
    return { panel: await screen.findByTestId('infeasibility-panel'), s };
  };

  it('in the app: names as main text, plain headings, codes only as small secondary text', async () => {
    const { panel, s } = await openDiagnosis();
    const subject = display.subjects[edgeList.sessions.find((x) => x.id === s.sessionId)!.subject_id].name;
    const change = within(panel).getByTestId('conflicting-constraint-change');
    const moved = `${subject} for ${s.cohortLabel} (${s.facultyName}) moved to Monday T0 in room 601.`;
    expect(within(change).getByText(moved)).toBeInTheDocument();
    expect(within(change).getByTestId('constraint-kind-FIXED_SLOT')).toHaveTextContent('The change you asked for');

    const pin = within(panel).getByTestId('conflicting-constraint-pin.238');
    const held = `${display.pins[238].unique_label!.replace(/\bP(\d)\b/g, 'T$1')} holds SE-Comp A at Monday T0. Without it a timetable exists that uses it for SE-Comp A.`;
    expect(within(pin).getByText(held)).toBeInTheDocument();
    expect(within(panel).getByText('Free SE-Comp A from the fixed item at Monday T0.')).toBeInTheDocument();

    expect(within(panel).getByText('Why this change is impossible')).toBeInTheDocument();
    expect(within(panel).getByText('What would make it possible')).toBeInTheDocument();
    expect(panel).not.toHaveTextContent('Minimal Unsatisfiable Subset');

    // the codes appear only in the small notes
    const code = within(pin).getByText('PINNED_BLOCK · pin.238');
    expect(code.className).toContain('text-[11px]');
    expect(within(panel).getByText('RELAX_PINNED_BLOCK, restored').className).toContain('text-[11px]');
  });

  it('says what an impossible repair means instead of "0 / 156 sessions placed"', async () => {
    const { panel } = await openDiagnosis();
    expect(panel).not.toHaveTextContent('sessions placed');
    expect(within(panel).getByTestId('repair-not-applied')).toHaveTextContent('Official timetable');
    expect(within(panel).getByTestId('repair-not-applied')).toHaveTextContent('Unchanged. Nothing from this repair was applied.');
  });
});

describe('M8: where it opens, what it keeps, and the test controls', () => {
  it.each(['administrator', 'coordinator', 'faculty', 'student'] as const)('http, %s: opens on the real instance, no test controls', async (role) => {
    await open(role);
    expect(screen.getByLabelText('Select instance')).toHaveValue(REAL_INSTANCE);
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
  });

  it('http: no test controls on the example either', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: 'example' } });
    await waitFor(() => expect(screen.queryByTestId('solve-panel')).not.toBeInTheDocument());
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
  });

  it('http: keeps the choice across a reload; a logout forgets it', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: PRINTED_INSTANCE } });
    await screen.findByTestId('printed-violations');
    expect(storedInstance()).toBe(PRINTED_INSTANCE);

    // a reload: a new App, the session and the choice still in sessionStorage
    cleanup();
    render(<App client={new HttpChronosApiClient('/api')} />);
    await screen.findByTestId('printed-violations');
    expect(screen.getByLabelText('Select instance')).toHaveValue(PRINTED_INSTANCE);

    setSession(null);
    expect(storedInstance()).toBeNull();
  });

  it('http: a kept instance the backend no longer offers falls back to one it can solve', async () => {
    mockBackend();
    logIn('administrator');
    sessionStorage.setItem('chronos.instance', 'odd-2025-26');
    render(<App client={new HttpChronosApiClient('/api')} />);
    await screen.findByTestId('period-clock-0');
    expect(screen.getByLabelText('Select instance')).toHaveValue(REAL_INSTANCE);
  });

  it('static: opens on the example with its test controls, and they stay off the real instance', async () => {
    render(<App client={new MockChronosApiClient()} />);
    await screen.findByTestId('timetable-grid');
    expect(screen.getByLabelText('Select instance')).toHaveValue('example');
    expect(screen.getByTestId('toggle-outcome-button')).toBeInTheDocument();
    expect(screen.getByTestId('toggle-reject-mode-button')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('period-clock-0');
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
  });
});

describe('M9: the session details window', () => {
  it('is titled with subject, cohort and teacher; no raw id and no raw record', () => {
    const s = sessions.find((x) => x.sessionId === 'obs-t0-r1-c3-l0')!;
    const { container } = render(<SessionDetailModal session={s} onClose={() => {}} />);
    expect(screen.getByRole('dialog', { name: `${s.subjectName} for SE-Comp A (Anant Nimkar)` })).toBeInTheDocument();
    expect(container.textContent).not.toContain(s.sessionId);
    expect(screen.queryByText(/Placement record/)).not.toBeInTheDocument();
    expect(container.querySelector('pre')).toBeNull();
  });

  it.each(BOTH_MODES)('%s: from the grid', async (_mode, openIt) => {
    await openIt();
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: 'coh-se-a' } });
    fireEvent.click(screen.getByTestId('session-cell-obs-t0-r1-c3-l0'));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByRole('heading')).toHaveTextContent('for SE-Comp A (Anant Nimkar)');
    expect(dialog).not.toHaveTextContent('obs-t0-r1-c3-l0');
  });
});

describe('M10: the division filter shows labels only', () => {
  it('two groups named alike keep their ids out of the option text', () => {
    const options = cohortOptions(edgeList, labelsFor(display));
    expect(options.filter((o) => o.label === 'MDM-DBMS').length).toBeGreaterThan(0);
    expect(options.some((o) => o.label.includes('coh-'))).toBe(false);
  });

  it.each(BOTH_MODES)('%s: in the dropdown', async (_mode, openIt) => {
    await openIt();
    const texts = [...(screen.getByLabelText('Filter timetable by division') as HTMLSelectElement).options].map((o) => o.text);
    expect(texts.length).toBeGreaterThan(1);
    for (const t of texts) expect(t).not.toContain('coh-');
  });
});

describe('M11: hard rules lead the comparison', () => {
  it('words every way the numbers can fall', () => {
    expect(comparisonSentence(0, 36, -15, 21.5)).toBe('The printed timetable scores higher on the soft rules but breaks 36 hard rules; the generated one breaks none.');
    expect(comparisonSentence(0, 1, 30, 21.5)).toBe('The printed timetable scores lower on the soft rules and breaks 1 hard rule; the generated one breaks none.');
    expect(comparisonSentence(2, 36, null, 21.5)).toBe('The printed timetable breaks 36 hard rules; the generated one breaks 2 hard rules.');
  });

  it('reads both counts from the data, first in the table, and changes no number', () => {
    const generated = toQualityView(solution);
    const hard = hardRuleViolations(solution.assignment, edgeList);
    render(<GeneratedVsPrintedCard generated={generated} generatedHard={hard} printed={printed} />);
    const rows = within(screen.getByTestId('generated-vs-printed')).getAllByRole('row');
    expect(rows[1]).toHaveAttribute('data-testid', 'compare-hard');
    expect(rows[2]).toHaveAttribute('data-testid', 'compare-score');
    expect(screen.getByTestId('compare-hard')).toHaveTextContent(`${hard}${printed.violations.length}`);
    expect(screen.getByTestId('compare-score')).toHaveTextContent(`${generated.score!.toFixed(1)}${printed.quality.score!.toFixed(1)}`);
  });

  it.each(BOTH_MODES)('%s: leads with the sentence', async (_mode, openIt) => {
    await openIt();
    expect(screen.getByTestId('compare-sentence')).toHaveTextContent(
      'The printed timetable scores higher on the soft rules but breaks 36 hard rules; the generated one breaks none.'
    );
    expect(screen.getByTestId('compare-hard')).toHaveTextContent('036');
  });
});

describe('S4: a substitution counts its teacher change', () => {
  it('words the counts', () => {
    expect(repairSummary(0, 1)).toBe('1 session: teacher changed');
    expect(repairSummary(2, 1)).toBe('2 sessions changed; 1 session: teacher changed');
    expect(repairSummary(1, 0)).toBe('1 session changed');
    expect(repairSummary(0, 0)).toBe('0 sessions changed');
  });

  it('a proposal says who changed, not "0 sessions changed"', async () => {
    const backend = await open('coordinator');
    const LECTURE = 'obs-t0-r1-c3-l0';
    backend.substitutes = { session_id: LECTURE, faculty_id: 'fac-anant-nimkar', candidates: [{ faculty_id: 'fac-prasenjit-bhavathankar', score_change: 0 }], left_out: [] };
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: 'coh-se-a' } });
    fireEvent.click(screen.getByTestId(`session-cell-${LECTURE}`));
    fireEvent.click(screen.getByTestId('find-substitute'));
    backend.job = job({
      status: 'solved',
      change: { kind: 'substitute_faculty', session_id: LECTURE, faculty_id: 'fac-prasenjit-bhavathankar' },
      solution: { ...solution, displaced: [] },
    });
    fireEvent.click(await screen.findByTestId('substitute-fac-prasenjit-bhavathankar'));
    expect(await screen.findByTestId('repair-summary')).toHaveTextContent('1 session: teacher changed');
    expect(screen.getByTestId('repair-teacher-change')).toHaveTextContent('CE207 · SE-Comp A: Anant Nimkar (AVN) → Prasenjit Bhavathankar (PBB)');
  });
});

describe('S8: audit rows', () => {
  it('the sentence comes first; the code is small and separate, never run together with a label', async () => {
    const backend = mockBackend();
    backend.audit = [{ id: 1, actor: 'test-administrator', action: 'accept', timestamp: '2026-10-31T10:00:00Z', detail: { job_id: 'rep-1' } }];
    logIn('administrator');
    render(<App client={new HttpChronosApiClient('/api')} />);
    const row = await screen.findByTestId('audit-row');
    const sentence = within(row).getByTestId('audit-sentence');
    expect(sentence).toHaveTextContent('test-administrator (administrator) accepted a repair.');
    expect(row).not.toHaveTextContent('Repair accepted accept');
    const code = within(row).getByTestId('audit-code');
    expect(code).toHaveTextContent('accept');
    expect(code.closest('details')!.className).toContain('text-[11px]');
    expect(sentence.compareDocumentPosition(code) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
