import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { useState } from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '@/App';
import { SolvePanel } from '../SolvePanel';
import {
  HttpChronosApiClient,
  MockChronosApiClient,
  PRINTED_INSTANCE,
  REAL_INSTANCE,
  setSession,
} from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { instanceSolutionQueryKey } from '@/api/queries';
import { SolvedSolution, isSolvedSolution, toQualityView } from '@/adapters/solution';
import { PrintedBaseline } from '@/adapters/realInstance';
import { buildPins, labelsFor } from '@/adapters/timetable';
import infeasibleFixture from '@contracts/examples/solution_v2.infeasible.example.json';

// The real instance's files, as the backend serves them
const files = new MockChronosApiClient();
let real: Record<string, unknown>;
let solution: SolvedSolution;
let baseline: PrintedBaseline;
beforeAll(async () => {
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  baseline = (await files.getPrintedBaseline(REAL_INSTANCE))!;
  const edgeList = await files.getEdgeList(REAL_INSTANCE);
  real = {
    'edge-list': edgeList,
    // no accepted changes: the current edge list is the committed one
    'edge-list/current': edgeList,
    display: await files.getDisplay(REAL_INSTANCE),
    anomalies: await files.getAnomalies(REAL_INSTANCE),
    solution,
  };
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const job = (fields: Record<string, unknown>): Record<string, unknown> => ({
  id: 'job-1',
  instance_id: REAL_INSTANCE,
  time_limit_s: 300,
  status: 'running',
  ...fields,
});

/** The S13a backend: the real instance, one solve job whose state the test sets. */
function mockBackend(solve: () => Response = () => json({ job_id: 'job-1', status: 'queued' }, 202)) {
  const state = { job: job({ status: 'queued' }), jobPolls: 0 };
  const fetchMock = vi.fn(async (url: string) => {
    if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
    if (url === `/api/instances/${REAL_INSTANCE}/solve`) return solve();
    if (url === '/api/jobs/job-1') {
      state.jobPolls += 1;
      return json(state.job);
    }
    const file = url.match(new RegExp(`^/api/instances/${REAL_INSTANCE}/(.+)$`))?.[1];
    return file && file in real ? json(real[file]) : json({ detail: 'Not Found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return state;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});

const logIn = (role: UserRole) => setSession({ username: `test-${role}`, token: `token-${role}`, role });

const status = () => screen.getByTestId('solve-status');
const wait = (ms: number) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

describe('SolvePanel: the job lifecycle', () => {
  // the caller keeps the job id, as App does
  function Panel() {
    const [jobId, setJobId] = useState<string | null>(null);
    return (
      <SolvePanel
        client={new HttpChronosApiClient('/api')}
        instance={REAL_INSTANCE}
        jobId={jobId}
        onJobStarted={(_, id) => setJobId(id)}
        pollMs={10}
      />
    );
  }
  const renderPanel = () => {
    const queryClient = new QueryClient();
    const view = render(
      <QueryClientProvider client={queryClient}>
        <Panel />
      </QueryClientProvider>
    );
    return { queryClient, ...view };
  };

  it('POSTs, shows queued then running, polls until solved, then stops polling', async () => {
    const backend = mockBackend();
    const { queryClient } = renderPanel();
    fireEvent.change(screen.getByTestId('solve-time-limit'), { target: { value: '30' } });
    fireEvent.click(screen.getByTestId('solve-button'));

    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'queued'));
    expect(screen.getByTestId('solve-button')).toBeDisabled();
    backend.job = job({ status: 'running' });
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'running'));
    backend.job = job({ status: 'solved', solution });
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'solved'));

    expect(queryClient.getQueryData(instanceSolutionQueryKey(REAL_INSTANCE))).toEqual(solution);
    expect(screen.getByTestId('solve-button')).toBeEnabled();
    const polls = backend.jobPolls;
    await wait(80);
    expect(backend.jobPolls).toBe(polls);
  });

  it('reads a timeout as no timetable found, not as impossible, and keeps the solution', async () => {
    const backend = mockBackend();
    const { queryClient } = renderPanel();
    backend.job = job({ status: 'timeout', time_limit_s: 5 });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'timeout'));
    expect(status()).toHaveTextContent('No timetable found within 5 s. This does not prove it is impossible.');
    expect(queryClient.getQueryData(instanceSolutionQueryKey(REAL_INSTANCE))).toBeUndefined();
  });

  it('shows a solver error', async () => {
    const backend = mockBackend();
    renderPanel();
    backend.job = job({ status: 'error', error: 'RuntimeError: solved but invalid' });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'error'));
    expect(status()).toHaveTextContent('Solve failed: RuntimeError: solved but invalid');
  });

  it('shows the backend’s reason when the POST is refused', async () => {
    mockBackend(() => json({ detail: 'student may not do this' }, 403));
    renderPanel();
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'error'));
    expect(status()).toHaveTextContent(`POST /instances/${REAL_INSTANCE}/solve: 403 student may not do this`);
  });

  it('stops polling when unmounted', async () => {
    const backend = mockBackend();
    const { unmount } = renderPanel();
    backend.job = job({ status: 'running' });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(backend.jobPolls).toBeGreaterThan(2));
    unmount();
    const polls = backend.jobPolls;
    await wait(80);
    expect(backend.jobPolls).toBe(polls);
  });

  it('refuses a time limit outside the backend’s bounds', () => {
    mockBackend();
    renderPanel();
    fireEvent.change(screen.getByTestId('solve-time-limit'), { target: { value: '1801' } });
    expect(screen.getByTestId('solve-button')).toBeDisabled();
  });
});

describe('Solving the real instance in the app (http mode)', () => {
  const openReal = async (role: UserRole = 'administrator') => {
    const backend = mockBackend();
    logIn(role);
    render(<App client={new HttpChronosApiClient('/api')} />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('period-clock-0');
    return backend;
  };

  it.each([
    ['administrator', true],
    ['coordinator', true],
    ['faculty', false],
    ['student', false],
  ] as const)('offers Solve to the logged-in %s: %s', async (role, offered) => {
    await openReal(role);
    expect(!!screen.queryByTestId('solve-panel')).toBe(offered);
  });

  it('offers Solve on backend instances only', async () => {
    await openReal();
    expect(screen.getByTestId('solve-panel')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: PRINTED_INSTANCE } });
    await screen.findByTestId('printed-violations');
    expect(screen.queryByTestId('solve-panel')).not.toBeInTheDocument();
  });

  it('a solved job refreshes the quality card and the comparison', async () => {
    const backend = await openReal();
    const fresh = { ...solution, quality: { ...solution.quality, score: 42 } };
    backend.job = job({ status: 'solved', solution: fresh });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(screen.getByTestId('quality-score')).toHaveTextContent('42'));
    expect(within(screen.getByTestId('compare-score')).getByText('42.0')).toBeInTheDocument();
  });

  it('an infeasible job opens the diagnosis panel with its diagnosis', async () => {
    const backend = await openReal();
    backend.job = job({ status: 'infeasible', solution: infeasibleFixture });
    fireEvent.click(screen.getByTestId('solve-button'));
    await screen.findByTestId('infeasibility-panel');
    const first = infeasibleFixture.diagnosis.minimal_conflicting_set[0].constraint_id;
    expect(screen.getByTestId(`conflicting-constraint-${first}`)).toBeInTheDocument();
  });

  it('a timeout never opens the diagnosis panel (D33)', async () => {
    const backend = await openReal();
    backend.job = job({ status: 'timeout', time_limit_s: 300 });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'timeout'));
    expect(status()).toHaveTextContent('No timetable found within 300 s. This does not prove it is impossible.');
    expect(screen.queryByTestId('infeasibility-panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('status-badge-solved')).toBeInTheDocument();
  });

  // D56, S14i: GET /jobs/{id} `stale` is true when an accept or a clear happened while it ran
  const STALE = 'Finished, but not official: the accepted changes changed while it ran. Run Solve again.';

  it('a finished solve that is not official says so and does not replace the grid', async () => {
    const backend = await openReal();
    const score = screen.getByTestId('quality-score').textContent;
    const moved = solution.assignment[0];
    const fresh = {
      ...solution,
      assignment: solution.assignment.map((a) => (a === moved ? { ...a, day: (moved.day + 1) % 5 } : a)),
      quality: { ...solution.quality, score: 42 },
    };
    backend.job = job({ status: 'solved', solution: fresh, stale: true, built_with: ['rep-7'] });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-stale', 'true'));
    expect(status()).toHaveTextContent(STALE);
    expect(status()).not.toHaveTextContent('Solved: the grid');
    await wait(50);
    expect(screen.getByTestId('quality-score').textContent).toBe(score);
    expect(screen.getByTestId('quality-score')).not.toHaveTextContent('42');
    expect(within(screen.getByTestId('compare-score')).queryByText('42.0')).not.toBeInTheDocument();
    expect(screen.getByTestId('solve-button')).toBeEnabled();
  });

  it('a stale infeasible solve opens no diagnosis panel', async () => {
    const backend = await openReal();
    backend.job = job({ status: 'infeasible', solution: infeasibleFixture, stale: true });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(status()).toHaveTextContent(STALE));
    await wait(50);
    expect(screen.queryByTestId('infeasibility-panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('status-badge-solved')).toBeInTheDocument();
  });

  it('a solve that is not stale (stale: false) still replaces the grid', async () => {
    const backend = await openReal();
    backend.job = job({ status: 'solved', solution: { ...solution, quality: { ...solution.quality, score: 42 } }, stale: false });
    fireEvent.click(screen.getByTestId('solve-button'));
    await waitFor(() => expect(screen.getByTestId('quality-score')).toHaveTextContent('42'));
    expect(status()).not.toHaveAttribute('data-stale');
  });
});

describe('The real instance against the printed timetable (static mode)', () => {
  const open = async (instance: string) => {
    render(<App />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: instance } });
  };

  it('compares score, each rule penalty and hard violations, read from the files', async () => {
    await open(REAL_INSTANCE);
    const card = await screen.findByTestId('generated-vs-printed');
    const row = (key: string) => within(card).getByTestId(`compare-${key}`);
    const generated = toQualityView(solution);
    expect(row('score')).toHaveTextContent(`${generated.score!.toFixed(1)}${baseline.quality.score!.toFixed(1)}`);
    expect(generated.rules).toHaveLength(4);
    for (const rule of generated.rules) {
      const printed = baseline.quality.rules.find((r) => r.rule_id === rule.rule_id);
      if (rule.status !== 'evaluated' || printed?.status !== 'evaluated') throw new Error(`${rule.rule_id} not evaluated`);
      expect(row(rule.rule_id)).toHaveTextContent(`-${rule.penalty.toFixed(1)}-${printed.penalty.toFixed(1)}`);
    }
    expect(row('hard')).toHaveTextContent(`0${baseline.violations.length}`);
    // hidden from the read-only roles, like the quality card
    fireEvent.click(screen.getByTestId('role-button-student'));
    expect(screen.queryByTestId('generated-vs-printed')).not.toBeInTheDocument();
  });

  it('badges the printed view as the printed timetable, without the comparison or Solve', async () => {
    await open(PRINTED_INSTANCE);
    await screen.findByTestId('printed-violations');
    expect(screen.getByTestId('status-badge-printed')).toHaveTextContent('Printed timetable (SPIT)');
    expect(screen.queryByTestId('status-badge-unsolved')).not.toBeInTheDocument();
    expect(screen.queryByTestId('generated-vs-printed')).not.toBeInTheDocument();
    expect(screen.queryByTestId('solve-panel')).not.toBeInTheDocument();
  });

  it('names faculty who teach no SE/TE session without initials, never "Unresolved"', async () => {
    const labels = labelsFor(await files.getDisplay(REAL_INSTANCE));
    const pins = buildPins(await files.getEdgeList(REAL_INSTANCE), labels);
    const faculty = new Set(pins.flatMap((p) => p.facultyInitials));
    expect(faculty).toContain('Dayanand Ambawade');
    expect(faculty).toContain('Vandana Wekhande');
    expect(faculty).not.toContain('Unresolved');
    expect(faculty).not.toContain('');
  });
});
