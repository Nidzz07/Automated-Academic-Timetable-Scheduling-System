import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { clickGenerate } from '@/test/generate';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { FacultyWorkloadCard } from '../FacultyWorkloadCard';
import { MockChronosApiClient, HttpChronosApiClient, PRINTED_INSTANCE, REAL_INSTANCE, ApiError, setSession, storeInstance } from '@/api/chronosApi';
import type { EdgeListInstance } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { QualityRule, SolutionContract, SolvedSolution, isSolvedSolution } from '@/adapters/solution';
import { Display, EdgeList, EnrichedSession, buildEnrichedSessions, labelsFor } from '@/adapters/timetable';
import { parseSolution } from '@/api/contractValidation';
import { loadChangeText, loadText, searchStepsText } from '@/lib/wording';

// S14v: what the local re-check of 2026-10-31 found. The real instance's files, as the backend serves them
const P_LABEL = /\bP\d\b/;
let real: Record<string, unknown>;
let edgeList: EdgeList;
let display: Display;
let solution: SolvedSolution;
let sessions: EnrichedSession[];
/** The MDM-DBMS group display.json labels "MDM-DBMS, Mon P7–P8" */
let mdmCohort: string;
/** A fixed item whose display.json unique_label carries a P-label */
let pinIndex: number;

beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  display = (await files.getDisplay(REAL_INSTANCE))!;
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  sessions = buildEnrichedSessions(solution.assignment, edgeList, labelsFor(display));
  real = { 'edge-list': edgeList, 'edge-list/current': edgeList, display, anomalies: await files.getAnomalies(REAL_INSTANCE), solution };
  mdmCohort = Object.entries(display.cohorts).find(([, c]) => c.label && P_LABEL.test(c.label) && c.label.includes('Mon'))![0];
  pinIndex = display.pins.findIndex((p) => p.unique_label && P_LABEL.test(p.unique_label));
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const repairJob = (fields: Record<string, unknown>) => ({
  id: 'rep-1',
  instance_id: REAL_INSTANCE,
  kind: 'repair',
  time_limit_s: 300,
  base: 'committed',
  status: 'queued',
  ...fields,
});

/** The backend with one repair job and one solve job; the test sets what each says next. */
function mockBackend() {
  const state = {
    job: repairJob({}) as Record<string, unknown>,
    solveJob: null as Record<string, unknown> | null,
    official: null as unknown,
    repairRefusal: null as { status: number; body: unknown } | null,
    instances: [{ id: REAL_INSTANCE }],
    substitutes: null as unknown,
    jobEdgeList: null as EdgeList | null,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/instances') return json(state.instances);
      if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
        return state.repairRefusal
          ? json(state.repairRefusal.body, state.repairRefusal.status)
          : json({ job_id: 'rep-1', status: 'queued' }, 202);
      }
      if (url === `/api/instances/${REAL_INSTANCE}/solve`) return json({ job_id: 'solve-1', status: 'queued' }, 202);
      if (url.startsWith('/api/audit')) return json([]);
      if (url === `/api/instances/${REAL_INSTANCE}/changes`) return json([]);
      if (url === `/api/instances/${REAL_INSTANCE}/solution`) return json(state.official ?? solution);
      if (url.startsWith(`/api/instances/${REAL_INSTANCE}/sessions/`)) return json(state.substitutes);
      if (url === '/api/jobs/rep-1/accept') {
        state.job = { ...state.job, accepted_at: '2026-10-31T10:00:00Z' };
        return json(state.job);
      }
      if (url === '/api/jobs/rep-1/base-solution') return json(solution);
      if (url === '/api/jobs/rep-1/edge-list') return json(state.jobEdgeList ?? edgeList);
      if (url === '/api/jobs/rep-1') return json(state.job);
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

const openHttp = async (role: UserRole = 'administrator') => {
  const backend = mockBackend();
  logIn(role);
  render(<App client={new HttpChronosApiClient('/api')} />);
  await screen.findByTestId('period-clock-0');
  return backend;
};

const openStatic = async (client = new MockChronosApiClient()) => {
  render(<App client={client} />);
  await screen.findByTestId('timetable-grid');
  fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
  await screen.findByTestId('period-clock-0');
};

const BOTH_MODES = [
  ['static', () => openStatic()],
  ['http', () => openHttp()],
] as const;

/** A teacher's view: static mode picks the role, a login has it. */
const TEACHER_MODES = [
  [
    'static',
    async () => {
      await openStatic();
      fireEvent.click(screen.getByTestId('role-button-faculty'));
    },
  ],
  ['http', () => openHttp('faculty')],
] as const;

const pick = (instance: EdgeListInstance) =>
  fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: instance } });

/** A diagnosis as solver/mus.py writes it, naming the MDM-DBMS group and a fixed item. */
const diagnosisOfRealInstance = () =>
  parseSolution({
    schema_version: 'solution.v2',
    status: 'infeasible',
    diagnosis: {
      method: 'mus',
      minimal_conflicting_set: [
        {
          constraint_id: `pin.${pinIndex}`,
          kind: 'PINNED_BLOCK',
          description: `Pinned occupancy ${pinIndex} holds ${mdmCohort} at Mon P7. Without it a timetable exists that uses it for ${mdmCohort}.`,
          entity_ids: [mdmCohort],
          slots: [{ day: 0, period: 7 }],
        },
      ],
      suggested_relaxation: {
        constraint_id: `pin.${pinIndex}`,
        description: `Free cohort ${mdmCohort} from the pinned occupancy at Mon P7.`,
        action: { action_type: 'RELAX_PINNED_BLOCK', params: { slot: { day: 0, period: 7 }, entity_kind: 'cohort', entity_id: mdmCohort } },
        verification: { status: 'restored', runtime_ms: 12 },
      },
      partial_placement: [],
      unplaced_session_ids: [sessions[0].sessionId],
    },
    metadata: { algorithm: 'freeze-and-expand(pre-check) + mus-extraction(deletion-based)', runtime_ms: 40, sessions_total: 156, sessions_assigned: 0, slots_used: null, backtracks: 174 },
  });

/** Accept stays disabled until the proposal's base solution and edge list have loaded. */
const acceptProposal = async () => {
  const accept = await screen.findByTestId('accept-repair');
  await waitFor(() => expect(accept).toBeEnabled());
  fireEvent.click(accept);
};

const markKurhade = () => {
  const panel = screen.getByTestId('repair-panel');
  fireEvent.change(within(panel).getByLabelText('Unavailable teacher'), { target: { value: 'fac-swapnali-kurhade' } });
  fireEvent.click(within(panel).getByLabelText('Tuesday T6'));
  fireEvent.click(screen.getByTestId('mark-unavailable-button'));
};

describe('1. no P-label reaches a user (D60)', () => {
  it('labelsFor converts what display.json holds; the data keeps its P-labels', () => {
    const labels = labelsFor(display);
    for (const id of Object.keys(display.cohorts)) expect(labels.cohort(id)).not.toMatch(P_LABEL);
    display.pins.forEach((_, i) => {
      expect(labels.pin(i)?.label).not.toMatch(P_LABEL);
      expect(labels.pin(i)?.unique_label ?? '').not.toMatch(P_LABEL);
    });
    expect(labels.cohort(mdmCohort)).toMatch(/^MDM-DBMS, Mon T\d–T\d$/);
    // the sidecar itself is untouched
    expect(display.cohorts[mdmCohort].label).toMatch(P_LABEL);
    expect(display.pins[pinIndex].unique_label).toMatch(P_LABEL);
  });

  it.each(BOTH_MODES)('%s: the whole page, the division dropdown and a fixed-item card, as administrator', async (_mode, openIt) => {
    await openIt();
    expect(document.body.textContent).not.toMatch(P_LABEL);
    const dropdown = screen.getByLabelText('Filter timetable by division') as HTMLSelectElement;
    const options = [...dropdown.options].map((o) => o.text);
    expect(options.filter((o) => o.startsWith('MDM-DBMS, Mon')).length).toBeGreaterThan(0);
    for (const o of options) expect(o).not.toMatch(P_LABEL);

    fireEvent.change(dropdown, { target: { value: mdmCohort } });
    const cards = await screen.findAllByTestId('pinned-block');
    expect(cards.some((c) => /Class: .*MDM-DBMS, Mon T\d–T\d/.test(c.textContent!))).toBe(true);
    expect(document.body.textContent).not.toMatch(P_LABEL);
  });

  it.each(BOTH_MODES)('%s: the printed view', async (_mode, openIt) => {
    await openIt();
    pick(PRINTED_INSTANCE);
    await screen.findByTestId('printed-violations');
    expect(document.body.textContent).not.toMatch(P_LABEL);
  });

  const expectDiagnosisInWords = () => {
    const panel = screen.getByTestId('infeasibility-panel');
    const constraint = within(panel).getByTestId(`conflicting-constraint-pin.${pinIndex}`);
    expect(constraint).toHaveTextContent(/Involves: MDM-DBMS, Mon T\d–T\d/);
    expect(document.body.textContent).not.toMatch(P_LABEL);
  };

  it('static: a diagnosis of the real instance, its "Involves:" line by name', async () => {
    class Diagnosed extends MockChronosApiClient {
      public async getInstanceSolution(instance: EdgeListInstance): Promise<SolutionContract | null> {
        return instance === REAL_INSTANCE ? diagnosisOfRealInstance() : super.getInstanceSolution(instance);
      }
    }
    render(<App client={new Diagnosed()} />);
    await screen.findByTestId('timetable-grid');
    pick(REAL_INSTANCE);
    await screen.findByTestId('infeasibility-panel');
    expectDiagnosisInWords();
  });

  it('http: a refused repair’s diagnosis, its "Involves:" line by name', async () => {
    const backend = await openHttp();
    backend.job = repairJob({ status: 'infeasible', solution: diagnosisOfRealInstance() });
    markKurhade();
    await screen.findByTestId('infeasibility-panel');
    expectDiagnosisInWords();
  });

  it('http: a job’s error and a refusal’s words get T-labels too', async () => {
    const backend = await openHttp();
    backend.repairRefusal = { status: 422, body: { detail: 'Already closed at Tue P6' } };
    markKurhade();
    await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent('Tuesday T6'));
    expect(document.body.textContent).not.toMatch(P_LABEL);
  });
});

describe('2. the workload card: this teacher only (S17a)', () => {
  const rule: QualityRule = {
    rule_id: 'S-LOAD16',
    status: 'evaluated',
    weight: 1,
    raw: 2,
    penalty: 2,
    explanation: '2 faculty members above 16 h a week - fac-a 18 h, fac-b 17 h.',
  };
  const load = { theory: 6, practical: 8, scheduled: 14, fixed: 0, total: 14 };

  it('within the limit: no warning and no one else’s hours, though the rule flags others; the code as small text', () => {
    render(<FacultyWorkloadCard facultyName="Chitra Iyer" facultyInitials="CI" load={load} loadRule={rule} />);
    const card = screen.getByTestId('faculty-workload-card');
    expect(screen.getByTestId('load-status')).toHaveTextContent('Within the 16 h limit.');
    expect(screen.queryByTestId('load-over-limit')).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent(/fac-a|fac-b|18 h|17 h/);
    expect(screen.queryByTestId('rule-finding')).not.toBeInTheDocument();
    const heading = screen.getByTestId('load-rule-heading');
    expect(heading).toHaveTextContent('Weekly limit');
    const code = within(heading).getByTestId('load-rule-code');
    expect(code).toHaveTextContent('S-LOAD16');
    expect(code).toHaveClass('text-[11px]');
    expect(heading.firstChild?.textContent).not.toContain('S-LOAD16');
  });

  it('above the limit: their own red warning, once', () => {
    render(
      <FacultyWorkloadCard
        facultyName="Asha Rao"
        facultyInitials="AR"
        load={{ theory: 6, practical: 8, scheduled: 14, fixed: 4, total: 18 }}
        loadRule={rule}
      />
    );
    const warning = screen.getByTestId('load-over-limit');
    expect(warning).toHaveTextContent('Over 16 h limit: 18 h');
    expect(warning.querySelector('svg')).not.toBeNull();
    expect(warning.className).toContain('text-destructive');
    expect(screen.getByTestId('load-status')).toHaveTextContent('2 h above the 16 h limit.');
    expect(screen.getByTestId('faculty-workload-card')).not.toHaveTextContent(/fac-b|Binu|17 h/);
  });

  it.each(TEACHER_MODES)('%s: in the app, no other teacher’s name or warning; the quality card’s list is not there', async (_mode, openIt) => {
    await openIt();
    fireEvent.change(screen.getByLabelText('Select teacher'), { target: { value: 'fac-anant-nimkar' } });
    const card = screen.getByTestId('faculty-workload-card');
    expect(card).toHaveTextContent('Anant Nimkar');
    expect(card).toHaveTextContent('Within the 16 h limit.');
    expect(within(card).queryByTestId('load-over-limit')).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent(/Amey Ganesh Nile|Azman Qureshi/);
    expect(screen.queryByTestId('rule-finding')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quality-rule-S-LOAD16')).not.toBeInTheDocument();
  });

  it.each(['administrator', 'coordinator'] as const)('http, %s: the department-wide list is still in the quality card', async (role) => {
    await openHttp(role);
    const list = within(screen.getByTestId('quality-rule-S-LOAD16')).getAllByTestId('rule-finding');
    expect(list).toHaveLength(6);
    expect(list[0].textContent).toMatch(/\): Over 16 h limit: \d+ h$/);
  });
});

describe('3. how it was made: one plain sentence, the raw string behind "Details"', () => {
  const expectClosedDetails = () => {
    expect(screen.getByTestId('quality-method')).toHaveTextContent(
      'A step-by-step search that undoes any choice leading to a clash, then improved by trying many small changes'
    );
    expect(screen.getByTestId('quality-method').textContent).not.toMatch(/\(|=/);
    const details = screen.getByTestId('method-details') as HTMLDetailsElement;
    expect(details.tagName).toBe('DETAILS');
    expect(details.open).toBe(false);
    expect(within(details).getByText('Details').tagName).toBe('SUMMARY');
    const code = within(details).getByTestId('quality-method-code');
    expect(code).toHaveTextContent(solution.metadata.algorithm);
    expect(code).toHaveClass('text-[11px]');
    // wraps at spaces and hyphens, never mid-word
    expect(code).toHaveClass('break-normal');
    expect(code.className).not.toContain('break-all');
    expect(code.className).not.toContain('break-words');
  };

  it.each(BOTH_MODES)('%s: the quality card', async (_mode, openIt) => {
    await openIt();
    expectClosedDetails();
  });

  it('http: a repair says so in a sentence, its settings behind "Details"; a diagnosis too', async () => {
    const backend = await openHttp();
    backend.job = repairJob({ status: 'infeasible', solution: diagnosisOfRealInstance() });
    markKurhade();
    const panel = await screen.findByTestId('infeasibility-panel');
    const details = within(panel).getByTestId('method-details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByTestId('quality-method-code').className).not.toContain('break-all');
  });

  it('static: a diagnosis on the example', async () => {
    render(<App client={new MockChronosApiClient('infeasible')} />);
    const panel = await screen.findByTestId('infeasibility-panel');
    const details = within(panel).getByTestId('method-details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(within(details).getByTestId('quality-method-code').className).not.toContain('break-all');
  });
});

describe('4. the Timetable dropdown', () => {
  const offered = () => [...(screen.getByLabelText('Select timetable') as HTMLSelectElement).options].map((o) => o.value);

  it.each(['administrator', 'coordinator', 'faculty', 'student'] as const)('http, %s: only the backend’s instances and the printed view', async (role) => {
    await openHttp(role);
    expect(offered()).toEqual([REAL_INSTANCE, PRINTED_INSTANCE]);
    expect(screen.getByLabelText('Select timetable').textContent).not.toMatch(/Example/);
  });

  it('http: another backend instance is offered too, without a printed view', async () => {
    const backend = mockBackend();
    backend.instances = [{ id: REAL_INSTANCE }, { id: 'odd-2025-26' }];
    logIn('administrator');
    render(<App client={new HttpChronosApiClient('/api')} />);
    await screen.findByTestId('period-clock-0');
    expect(offered()).toEqual([REAL_INSTANCE, PRINTED_INSTANCE, 'odd-2025-26']);
  });

  it('http: "example" kept from an earlier session falls back to a backend instance', async () => {
    mockBackend();
    logIn('administrator');
    storeInstance('example');
    render(<App client={new HttpChronosApiClient('/api')} />);
    await screen.findByTestId('period-clock-0');
    expect(screen.getByLabelText('Select timetable')).toHaveValue(REAL_INSTANCE);
  });

  it('static: the examples stay', async () => {
    await openStatic();
    expect(offered()).toEqual(['example', 'd6_grid', REAL_INSTANCE, PRINTED_INSTANCE]);
  });
});

describe('5. hours in words', () => {
  it('lectures, practicals and fixed items, never T and P', () => {
    const load = (theory: number, practical: number, fixed: number) => ({ theory, practical, scheduled: theory + practical, fixed, total: theory + practical + fixed });
    expect(loadText(load(6, 8, 0))).toBe('6 h lectures + 8 h practicals = 14 h');
    expect(loadText(load(0, 6, 12))).toBe('0 h lectures + 6 h practicals + 12 h fixed items = 18 h');
    expect(loadText(load(1, 2, 1))).toBe('1 h lecture + 2 h practicals + 1 h fixed item = 4 h');
    expect(loadChangeText(load(6, 8, 0), load(7, 8, 0))).toBe('6 h lectures + 8 h practicals = 14 h → 7 h lectures + 8 h practicals = 15 h');
  });

  const NOTATION = /\d+T\b|\d+P\b|hrs\/wk/;

  it.each(TEACHER_MODES)('%s: the workload card', async (_mode, openIt) => {
    await openIt();
    const card = screen.getByTestId('faculty-workload-card');
    fireEvent.change(screen.getByLabelText('Select teacher'), { target: { value: 'fac-azman-qureshi' } });
    expect(within(card).getByTestId('workload-formula-badge')).toHaveTextContent('0 h lectures + 6 h practicals + 12 h fixed items = 18 h');
    expect(card.textContent).not.toMatch(NOTATION);
    expect(card.textContent).not.toMatch(/Theory \(T\)|Practical \(P\)/);
  });

  it('http: a substitution proposal in words', async () => {
    const backend = await openHttp('coordinator');
    const lecture = sessions.find((s) => s.facultyId === 'fac-jignesh-sisodia' && !s.labBlockId)!;
    backend.substitutes = { session_id: lecture.sessionId, faculty_id: lecture.facultyId, candidates: [{ faculty_id: 'fac-anant-nimkar', score_change: 0 }], left_out: [] };
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: lecture.cohortId } });
    fireEvent.click(screen.getByTestId(`session-cell-${lecture.sessionId}`));
    fireEvent.click(screen.getByTestId('find-substitute'));
    backend.job = repairJob({ status: 'solved', change: { kind: 'substitute_faculty', session_id: lecture.sessionId, faculty_id: 'fac-anant-nimkar' }, solution: { ...solution, displaced: [] } });
    const after: EdgeList = JSON.parse(JSON.stringify(edgeList));
    after.sessions.find((s) => s.id === lecture.sessionId)!.faculty_id = 'fac-anant-nimkar';
    backend.jobEdgeList = after;
    fireEvent.click(await screen.findByTestId('substitute-fac-anant-nimkar'));
    const row = await screen.findByTestId('substitution-load-fac-jignesh-sisodia');
    expect(row.textContent).toMatch(/h lectures? \+ \d+ h practicals? \+ 1 h fixed item = 17 h → /);
    expect(screen.getByTestId('substitution-loads').textContent).not.toMatch(NOTATION);
  });
});

describe('6. the room timetable fits the way the main grid does (measured at 1366 px in the browser check)', () => {
  it.each(BOTH_MODES)('%s: a fixed layout that shares the width, text that wraps', async (_mode, openIt) => {
    await openIt();
    const card = screen.getByTestId('room-timetable');
    const table = card.querySelector('table')!;
    expect(table.className).toContain('table-fixed');
    expect(table.className).toContain('w-full');
    expect(table.className).toContain('break-words');
    // no width of its own beside another card; below lg the card has the whole page
    expect(table.className).toContain('lg:min-w-0');
    expect(table.className).not.toContain('min-w-[640px]');
    expect(card.querySelector('.whitespace-nowrap')).toBeNull();
  });
});

describe('7. the search count says what it is', () => {
  it('search steps, not steps undone', () => {
    expect(searchStepsText(174)).toBe('174 search steps');
    expect(searchStepsText(1)).toBe('1 search step');
    expect(searchStepsText(9417)).toBe('9,417 search steps');
    expect(searchStepsText(null)).toBe('Not reported');
  });

  it.each(BOTH_MODES)('%s: the quality card', async (_mode, openIt) => {
    await openIt();
    expect(document.body.textContent).not.toMatch(/undone/);
    expect(screen.getByTestId('quality-search-steps')).toHaveTextContent(`${solution.metadata.backtracks} search steps`);
  });

  it('http: an accepted repair’s count, on the quality card', async () => {
    const backend = await openHttp();
    const repaired = {
      ...solution,
      displaced: [],
      metadata: { ...solution.metadata, algorithm: 'freeze-and-expand(rings=2, freed=4, nodes=174)', backtracks: 174 },
    };
    backend.job = repairJob({ status: 'solved', change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 1, period: 6 }] }, solution: repaired });
    markKurhade();
    await acceptProposal();
    await waitFor(() => expect(screen.getByTestId('quality-search-steps')).toHaveTextContent('174 search steps'));
    expect(screen.getByTestId('quality-method')).toHaveTextContent('Repaired around the change, leaving the rest as it was');
    expect(document.body.textContent).not.toMatch(/undone/);
  });
});

describe('8. a refused request shows the backend’s detail, in words', () => {
  const status = () => screen.getByTestId('repair-status');
  const expectNoPlumbing = (text: string | null) => {
    expect(text).not.toMatch(/POST|GET|\/instances|\/jobs|\b4\d\d\b/);
  };

  it('http: a refused repair', async () => {
    const backend = await openHttp();
    backend.repairRefusal = { status: 422, body: { detail: 'This change is already in force' } };
    markKurhade();
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'error'));
    expect(status()).toHaveTextContent('The repair failed: This change is already in force');
    expectNoPlumbing(status().textContent);
  });

  it('http: a refusal naming an id says the name', async () => {
    const backend = await openHttp();
    backend.repairRefusal = { status: 422, body: { detail: "'fac-anant-nimkar' is not listed for this session's subject and type in qualifications.json (D53)" } };
    markKurhade();
    await waitFor(() => expect(status()).toHaveTextContent('Anant Nimkar (AVN)'));
    expect(status()).not.toHaveTextContent('fac-anant-nimkar');
  });

  it('the client: the error’s message is the detail; validation lists and bare statuses are words too', async () => {
    const answer = (body: unknown, status: number, statusText = '') =>
      vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status, statusText })));
    const client = new HttpChronosApiClient('/api');
    const refused = () => client.startRepair(REAL_INSTANCE, { kind: 'substitute_faculty', session_id: 's', faculty_id: 'f' }).catch((e: unknown) => e as ApiError);

    answer({ detail: 'already in force' }, 422);
    const plain = (await refused()) as ApiError;
    expect(plain).toBeInstanceOf(ApiError);
    expect(plain.status).toBe(422);
    expect(plain.message).toBe('already in force');
    expect(plain.endpoint).toBe(`POST /instances/${REAL_INSTANCE}/repair`);

    answer({ detail: [{ loc: ['body', 'change'], msg: 'Field required', type: 'missing' }, { loc: ['body'], msg: 'Input should be a valid dictionary', type: 'dict_type' }] }, 422);
    expect(((await refused()) as ApiError).message).toBe('Field required; Input should be a valid dictionary');

    answer({}, 500, 'Internal Server Error');
    expect(((await refused()) as ApiError).message).toBe('Internal Server Error');

    answer({}, 500);
    expect(((await refused()) as ApiError).message).toBe('The server answered with an error (500).');
  });

  it('static: never asks a backend, so it has nothing to refuse', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    await openStatic();
    expect(screen.queryByTestId('repair-panel')).not.toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('9. switching Timetable and back never re-applies an earlier solve', () => {
  const score = () => screen.getByTestId('quality-score');
  const withScore = (s: number) => ({ ...solution, displaced: [], quality: { ...solution.quality, score: s } });
  const away = async () => {
    pick(PRINTED_INSTANCE);
    await screen.findByTestId('printed-violations');
  };
  const back = async () => {
    pick(REAL_INSTANCE);
    await screen.findByTestId('solve-panel');
  };

  it('http: solve, accept a repair, switch away and back: the repair stays official', async () => {
    const backend = await openHttp();
    backend.solveJob = { id: 'solve-1', instance_id: REAL_INSTANCE, kind: 'solve', time_limit_s: 300, status: 'solved', solution: withScore(42) };
    clickGenerate();
    await waitFor(() => expect(score()).toHaveTextContent('42.0'));

    backend.job = repairJob({ status: 'solved', change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 1, period: 6 }] }, solution: withScore(50) });
    markKurhade();
    await acceptProposal();
    await waitFor(() => expect(score()).toHaveTextContent('50.0'));

    await away();
    await back();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(score()).toHaveTextContent('50.0');
    // the accepted repair's message also survives the trip
    expect(screen.getByTestId('repair-status')).toHaveTextContent('Accepted');
  });

  it('http: a solve that ends while away is still applied on the way back, once', async () => {
    const backend = await openHttp();
    backend.solveJob = { id: 'solve-1', instance_id: REAL_INSTANCE, kind: 'solve', time_limit_s: 300, status: 'running' };
    clickGenerate();
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'running'));
    await away();
    backend.solveJob = { ...backend.solveJob, status: 'solved', solution: withScore(42) };
    await back();
    await waitFor(() => expect(score()).toHaveTextContent('42.0'));
  });

  it('static: no solve jobs; switching keeps the published timetable', async () => {
    await openStatic();
    const before = score().textContent;
    await (async () => {
      pick(PRINTED_INSTANCE);
      await screen.findByTestId('printed-violations');
      pick(REAL_INSTANCE);
      await screen.findByTestId('generated-vs-printed');
    })();
    expect(score().textContent).toBe(before);
  });
});
