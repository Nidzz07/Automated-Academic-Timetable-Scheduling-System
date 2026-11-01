import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { InfeasibilityDiagnosisPanel } from '../InfeasibilityDiagnosisPanel';
import { PAST_LIMIT_GRACE_S, useElapsedSeconds } from '../JobProgress';
import { LoadLimitChange } from '../OverLimitWarning';
import { FreeRoomsPanel } from '../RoomViews';
import { SessionDetailModal } from '../SessionDetailModal';
import {
  AuditEntry,
  HttpChronosApiClient,
  JOB_ANSWER_WITHIN_MS,
  MockChronosApiClient,
  NoAnswerError,
  REAL_INSTANCE,
  setSession,
} from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { InfeasibleSolution, SolvedSolution, isInfeasibleSolution, isSolvedSolution } from '@/adapters/solution';
import { Display, EdgeList, EnrichedSession, EXAMPLE_LABELS, buildEnrichedSessions, labelsFor } from '@/adapters/timetable';
import { parseSolution } from '@/api/contractValidation';
import { SERVER_NO_ANSWER, SERVER_PAST_LIMIT, auditSentence, jobErrorText, jobRunningText, loadLimitChange, sessionWhenText } from '@/lib/wording';
import { clickGenerate } from '@/test/generate';
import infeasibleV2Fixture from '@contracts/examples/solution_v2.infeasible.example.json';

// S17a: what the check of the deployed site found on 2026-11-01. The real instance's files, as the backend serves them
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
  real = { 'edge-list': edgeList, 'edge-list/current': edgeList, display, anomalies: await files.getAnomalies(REAL_INSTANCE), solution };
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const job = (id: string, kind: 'solve' | 'repair', fields: Record<string, unknown> = {}) => ({
  id,
  instance_id: REAL_INSTANCE,
  kind,
  time_limit_s: 300,
  status: 'queued',
  ...fields,
});

/** Never answers, like a server that took the connection and went quiet; a real fetch rejects on abort. */
const hang = (init?: RequestInit) =>
  new Promise<Response>((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });

function mockBackend() {
  const state = {
    solve: job('solve-1', 'solve') as Record<string, unknown>,
    repair: job('rep-1', 'repair') as Record<string, unknown>,
    changes: [] as unknown[],
    hangSolve: false,
    hangRepair: false,
    hangJobs: false,
    solvePosts: 0,
    repairPosts: 0,
    jobReads: 0,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
      if (url === `/api/instances/${REAL_INSTANCE}/solve`) {
        state.solvePosts += 1;
        return state.hangSolve ? hang(init) : json({ job_id: 'solve-1', status: 'queued' }, 202);
      }
      if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
        state.repairPosts += 1;
        return state.hangRepair ? hang(init) : json({ job_id: 'rep-1', status: 'queued' }, 202);
      }
      if (url.startsWith('/api/audit')) return json([]);
      if (url === `/api/instances/${REAL_INSTANCE}/changes`) {
        if (init?.method !== 'DELETE') return json(state.changes);
        const cleared = state.changes;
        state.changes = [];
        return json(cleared);
      }
      if (url === '/api/jobs/rep-1/accept') {
        state.repair = { ...state.repair, accepted_at: '2026-11-01T10:00:00Z' };
        return json(state.repair);
      }
      if (url === '/api/jobs/rep-1/base-solution') return json(solution);
      if (url === '/api/jobs/rep-1/edge-list') return json(edgeList);
      if (url === '/api/jobs/rep-1' || url === '/api/jobs/solve-1') {
        state.jobReads += 1;
        if (state.hangJobs) return hang(init);
        return json(url.endsWith('rep-1') ? state.repair : state.solve);
      }
      const file = url.match(new RegExp(`^/api/instances/${REAL_INSTANCE}/(.+)$`))?.[1];
      return file && file in real ? json(real[file]) : json({ detail: 'Not Found' }, 404);
    })
  );
  return state;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setSession(null);
});

const openHttp = async (role: UserRole = 'administrator', answerWithinMs = JOB_ANSWER_WITHIN_MS, changes: unknown[] = []) => {
  const backend = mockBackend();
  backend.changes = changes;
  setSession({ username: `test-${role}`, token: `token-${role}`, role });
  render(<App client={new HttpChronosApiClient('/api', answerWithinMs)} />);
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
  ['static', openStatic],
  ['http', () => openHttp()],
] as const;

const markAbsent = () => {
  const panel = screen.getByTestId('repair-panel');
  fireEvent.change(within(panel).getByLabelText('Unavailable teacher'), { target: { value: 'fac-swapnali-kurhade' } });
  fireEvent.click(within(panel).getByLabelText('Friday T0'));
  fireEvent.click(screen.getByTestId('mark-unavailable-button'));
};

/** The panel's text a reader sees, with every closed "Details" left out. */
const shownText = (panel: HTMLElement) => {
  const copy = panel.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('details').forEach((d) => {
    if (!d.open) d.remove();
  });
  return copy.textContent ?? '';
};

const INTERNAL_CODE = /\b(mus|search_exhaustion|presolve|[A-Z]+_[A-Z_]+|restored|pin\.\d+)\b/;

describe('1. the diagnosis panel: every code behind a closed "Details"', () => {
  const diagnosis = (): InfeasibleSolution => {
    const parsed = parseSolution(infeasibleV2Fixture);
    if (!isInfeasibleSolution(parsed)) throw new Error('expected an infeasible payload');
    return parsed;
  };

  const expectCodesHidden = (panel: HTMLElement) => {
    expect(shownText(panel)).not.toMatch(INTERNAL_CODE);
    for (const details of panel.querySelectorAll('details')) {
      if (details.getAttribute('data-testid') !== 'partial-placement') expect(details.open).toBe(false);
    }
  };

  it('the method, each constraint’s kind and id and the relaxation’s action are inside; the sentences are not', () => {
    const solved = diagnosis();
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={solved} edgeList={edgeList} labels={EXAMPLE_LABELS} />);
    const panel = screen.getByTestId('infeasibility-panel');
    expectCodesHidden(panel);

    expect(screen.getByTestId('diagnosis-method')).toHaveTextContent('mus');
    expect(screen.getByTestId('diagnosis-method')).not.toBeVisible();
    for (const c of solved.diagnosis.minimal_conflicting_set) {
      const code = screen.getByTestId(`constraint-code-${c.constraint_id}`);
      expect(code).toHaveTextContent(`${c.kind} · ${c.constraint_id}`);
      expect(code).not.toBeVisible();
    }
    expect(screen.getByTestId('relaxation-code')).toHaveTextContent('RECLASSIFY_ROOM, restored');
    expect(screen.getByTestId('relaxation-code')).not.toBeVisible();
    expect(screen.getByTestId('relaxation-constraint-id')).not.toBeVisible();

    // the plain sentences stay in view
    expect(screen.getByText('The solver proved that no timetable meets every rule, and found the smallest set of rules that cannot all hold.')).toBeVisible();
    expect(screen.getByTestId('relaxation-action')).toBeVisible();
  });

  it('opening a "Details" shows its codes', () => {
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={diagnosis()} />);
    const details = screen.getByTestId('relaxation-details') as HTMLDetailsElement;
    details.open = true;
    expect(screen.getByTestId('relaxation-code')).toBeVisible();
  });

  it('static: the example’s diagnosis in the app', async () => {
    render(<App client={new MockChronosApiClient()} />);
    await screen.findByTestId('timetable-grid');
    fireEvent.click(screen.getByTestId('toggle-outcome-button'));
    expectCodesHidden(await screen.findByTestId('infeasibility-panel'));
  });

  it('http: a refused repair’s diagnosis, with a fixed item and "the change"', async () => {
    const backend = await openHttp();
    const session = sessions[0].sessionId;
    backend.repair = job('rep-1', 'repair', {
      status: 'infeasible',
      solution: {
        schema_version: 'solution.v2',
        status: 'infeasible',
        diagnosis: {
          method: 'mus',
          minimal_conflicting_set: [
            { constraint_id: 'change', kind: 'FIXED_SLOT', description: `The change: ${session} is moved to Mon P0 in room-601.`, entity_ids: [session], slots: [] },
            { constraint_id: 'pin.238', kind: 'PINNED_BLOCK', description: 'Pinned occupancy 238 holds coh-se-a at Mon P0.', entity_ids: ['coh-se-a'], slots: [{ day: 0, period: 0 }] },
          ],
          suggested_relaxation: {
            constraint_id: 'pin.238',
            description: 'Free cohort coh-se-a from the pinned occupancy at Mon P0.',
            action: { action_type: 'RELAX_PINNED_BLOCK', params: { slot: { day: 0, period: 0 }, entity_kind: 'cohort', entity_id: 'coh-se-a' } },
            verification: { status: 'restored', runtime_ms: 12 },
          },
          partial_placement: [],
          unplaced_session_ids: [session],
        },
        metadata: { algorithm: 'freeze-and-expand(pre-check) + mus-extraction(deletion-based)', runtime_ms: 40, sessions_total: 156, sessions_assigned: 0, slots_used: null, backtracks: 174 },
      },
    });
    markAbsent();
    const panel = await screen.findByTestId('infeasibility-panel');
    expect(shownText(panel)).not.toMatch(/\bmus\b|PINNED_BLOCK|pin\.238|FIXED_SLOT|RELAX_PINNED_BLOCK|, restored/);
    expect(within(panel).getByTestId('constraint-code-pin.238')).not.toBeVisible();
    expect(within(panel).getByTestId('constraint-code-change')).not.toBeVisible();
  });
});

describe('2. progress during long jobs', () => {
  /** Date and setInterval move by hand; fetch and react-query's own setTimeout(0) run for real. */
  const useHandClock = () => vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
  const advance = (ms: number) =>
    act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

  /** Real time passes, the hand clock does not, until the job is in this state on the page. */
  const until = async (testId: string, text: RegExp) => {
    for (let i = 0; i < 300 && !text.test(screen.queryByTestId(testId)?.textContent ?? ''); i++) await advance(0);
    expect(screen.getByTestId(testId).textContent).toMatch(text);
  };
  const RUNNING_FROM_0 = /^Running: 0 s/;
  const WAITING_FROM_0 = /^Waiting: 0 s/;

  it('the wording', () => {
    expect(jobRunningText(47, 300)).toBe('Running: 47 s of at most 300 s');
    expect(jobRunningText(3)).toBe('Running: 3 s');
  });

  it('counts whole seconds from the clock, so a throttled tab is still right', () => {
    useHandClock();
    const start = Date.now();
    const { result, rerender } = renderHook(({ since }: { since: number | null }) => useElapsedSeconds(since), {
      initialProps: { since: start as number | null },
    });
    expect(result.current).toBe(0);
    act(() => void vi.advanceTimersByTime(47_400));
    expect(result.current).toBe(47);
    rerender({ since: null });
    expect(result.current).toBe(0);
  });

  it('Generate: the seconds and the limit while it runs, and the wait before it', async () => {
    const backend = await openHttp();
    useHandClock();
    clickGenerate();
    await until('solve-progress', WAITING_FROM_0);
    expect(screen.getByTestId('solve-progress')).toHaveTextContent('Waiting: 0 s so far');
    await advance(5_000);
    expect(screen.getByTestId('solve-progress')).toHaveTextContent('Waiting: 5 s so far');
    backend.solve = job('solve-1', 'solve', { status: 'running', phase: 'search' });
    await advance(1_000);
    await until('solve-progress', RUNNING_FROM_0);
    expect(screen.getByTestId('solve-status')).toHaveTextContent('Searching for a timetable.');
    // the limit starts when it runs: this clock starts then
    await advance(47_000);
    expect(screen.getByTestId('solve-progress')).toHaveTextContent('Running: 47 s of at most 300 s');
    // the ticking line is outside the live region, so a screen reader is not told every second
    expect(screen.getByTestId('solve-progress')).toHaveAttribute('role', 'timer');
    expect(screen.getByTestId('solve-status')).not.toContainElement(screen.getByTestId('solve-progress'));
    backend.solve = job('solve-1', 'solve', { status: 'solved', solution });
    await advance(1_000);
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'solved'));
    expect(screen.queryByTestId('solve-progress')).not.toBeInTheDocument();
  });

  it('a repair: the same, with its own limit', async () => {
    const backend = await openHttp();
    backend.repair = job('rep-1', 'repair', { status: 'running', phase: 'repair', time_limit_s: 120 });
    useHandClock();
    markAbsent();
    await until('repair-progress', RUNNING_FROM_0);
    await advance(30_000);
    expect(screen.getByTestId('repair-progress')).toHaveTextContent('Running: 30 s of at most 120 s');
    expect(screen.getByTestId('repair-status')).toHaveTextContent('Repairing the timetable.');
  });

  it('the seconds go on after switching timetable and back', async () => {
    const backend = await openHttp();
    backend.solve = job('solve-1', 'solve', { status: 'running', phase: 'search' });
    useHandClock();
    clickGenerate();
    await until('solve-progress', RUNNING_FROM_0);
    await advance(10_000);
    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: `${REAL_INSTANCE}:printed` } });
    for (let i = 0; i < 300 && screen.queryByTestId('solve-panel'); i++) await advance(0);
    expect(screen.queryByTestId('solve-panel')).not.toBeInTheDocument();
    await advance(20_000);
    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
    await until('solve-progress', /^Running: \d+ s/);
    expect(screen.getByTestId('solve-progress').textContent).toMatch(/^Running: 30 s of at most 300 s$/);
  });

  describe('the POST that starts a job gets no answer', () => {
    it('the client stops waiting after 30 s', async () => {
      expect(JOB_ANSWER_WITHIN_MS).toBe(30_000);
      vi.stubGlobal('fetch', vi.fn((_url: string, init?: RequestInit) => hang(init)));
      vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
      const started = new HttpChronosApiClient('/api').startSolve(REAL_INSTANCE, 300);
      const refused = expect(started).rejects.toBeInstanceOf(NoAnswerError);
      await vi.advanceTimersByTimeAsync(29_999);
      expect(vi.getTimerCount()).toBe(1);
      await vi.advanceTimersByTimeAsync(1);
      await refused;
      expect(vi.getTimerCount()).toBe(0);
    });

    it.each([
      ['no connection', () => Promise.reject(new TypeError('Failed to fetch'))],
      ['a gateway’s error', async () => json({ detail: 'x' }, 502)],
      ['a host’s page instead of the API', async () => new Response('<html>Restarting</html>', { status: 200 })],
    ])('%s is no answer too', async (_what, answer) => {
      vi.stubGlobal('fetch', vi.fn(answer));
      await expect(new HttpChronosApiClient('/api').startRepair(REAL_INSTANCE, { kind: 'faculty_unavailable', faculty_id: 'f', slots: [] })).rejects.toBeInstanceOf(NoAnswerError);
    });

    it('a refusal is still the backend’s own answer', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => json({ detail: 'Already closed' }, 422)));
      await expect(new HttpChronosApiClient('/api').getJob('j')).rejects.toThrow('Already closed');
    });

    it('Generate: the plain sentence, then Try again posts again, Discard goes back to the start', async () => {
      const backend = await openHttp('administrator', 30);
      backend.hangSolve = true;
      clickGenerate();
      expect(screen.getByTestId('solve-progress')).toHaveTextContent(/^Waiting for the server to answer: \d s of at most 30 s$/);
      await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveTextContent(SERVER_NO_ANSWER));
      expect(screen.getByTestId('solve-status').textContent).toBe('The server did not answer. It may be busy or restarting. Try again in a minute.');
      expect(screen.getByTestId('solve-button')).toHaveTextContent('Generate');
      expect(screen.getByTestId('solve-button')).toBeEnabled();

      fireEvent.click(screen.getByTestId('retry-solve'));
      await waitFor(() => expect(backend.solvePosts).toBe(2));
      await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveTextContent(SERVER_NO_ANSWER));

      fireEvent.click(screen.getByTestId('discard-solve'));
      expect(screen.queryByTestId('solve-status')).not.toBeInTheDocument();
      expect(screen.queryByTestId('retry-solve')).not.toBeInTheDocument();
    });

    it('Try again that gets an answer goes on as usual', async () => {
      const backend = await openHttp('administrator', 30);
      backend.hangSolve = true;
      clickGenerate();
      await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveTextContent(SERVER_NO_ANSWER));
      backend.hangSolve = false;
      backend.solve = job('solve-1', 'solve', { status: 'running', phase: 'search' });
      fireEvent.click(screen.getByTestId('retry-solve'));
      await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'running'));
      expect(screen.queryByTestId('retry-solve')).not.toBeInTheDocument();
    });

    it('a repair: nothing stays on "Repairing…"; Try again posts the same change; Discard clears the form', async () => {
      const backend = await openHttp('administrator', 30);
      backend.hangRepair = true;
      markAbsent();
      expect(screen.getByTestId('mark-unavailable-button')).toHaveTextContent('Repairing…');
      await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent(SERVER_NO_ANSWER));
      expect(screen.getByTestId('mark-unavailable-button')).toHaveTextContent('Mark unavailable and repair');

      fireEvent.click(screen.getByTestId('retry-repair'));
      await waitFor(() => expect(backend.repairPosts).toBe(2));
      await waitFor(() => expect(screen.getByTestId('retry-repair')).toBeEnabled());

      fireEvent.click(screen.getByTestId('discard-repair'));
      expect(screen.queryByTestId('repair-status')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Unavailable teacher')).toHaveValue('');
    });
  });

  describe('a job that can no longer be read, or never ends', () => {
    it('a read that hangs says the same; Try again reads the job again and posts nothing', async () => {
      const backend = await openHttp('administrator', 30);
      backend.hangJobs = true;
      markAbsent();
      await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent(SERVER_NO_ANSWER));
      backend.hangJobs = false;
      backend.repair = job('rep-1', 'repair', { status: 'running', phase: 'repair' });
      fireEvent.click(screen.getByTestId('retry-repair'));
      await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveAttribute('data-status', 'running'));
      expect(backend.repairPosts).toBe(1);
    });

    it.each([
      ['running', { status: 'running', phase: 'search', time_limit_s: 10 }],
      ['queued', { status: 'queued', time_limit_s: 10 }],
    ])('a Generate still %s past its limit stops waiting; a late result still counts', async (_state, fields) => {
      const backend = await openHttp();
      backend.solve = job('solve-1', 'solve', fields);
      useHandClock();
      clickGenerate();
      await until('solve-progress', fields.status === 'running' ? RUNNING_FROM_0 : WAITING_FROM_0);
      await advance((10 + PAST_LIMIT_GRACE_S) * 1000);
      expect(screen.getByTestId('solve-progress')).toBeInTheDocument();
      await advance(2_000);
      expect(screen.getByTestId('solve-status')).toHaveTextContent(SERVER_PAST_LIMIT);
      expect(screen.queryByTestId('solve-progress')).not.toBeInTheDocument();
      expect(screen.getByTestId('retry-solve')).toBeEnabled();
      expect(screen.getByTestId('discard-solve')).toBeEnabled();

      backend.solve = job('solve-1', 'solve', { status: 'solved', solution });
      await advance(1_000);
      vi.useRealTimers();
      await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'solved'));
      expect(screen.queryByTestId('retry-solve')).not.toBeInTheDocument();
    });

    it('a repair past its limit: the form is back, Discard leaves, the proposal never appears', async () => {
      const backend = await openHttp();
      backend.repair = job('rep-1', 'repair', { status: 'running', phase: 'repair', time_limit_s: 10 });
      useHandClock();
      markAbsent();
      await until('repair-progress', RUNNING_FROM_0);
      await advance((10 + PAST_LIMIT_GRACE_S + 2) * 1000);
      expect(screen.getByTestId('repair-status')).toHaveTextContent(SERVER_PAST_LIMIT);
      expect(screen.getByTestId('mark-unavailable-button')).toHaveTextContent('Mark unavailable and repair');
      fireEvent.click(screen.getByTestId('discard-repair'));
      expect(screen.queryByTestId('repair-status')).not.toBeInTheDocument();
    });
  });

  describe('how a job ends, in plain words', () => {
    it('a job’s error text', () => {
      expect(jobErrorText('server restarted').text).toBe('the server restarted while it ran. Nothing was changed.');
      expect(jobErrorText('cancelled').text).toBe('it was cancelled. Nothing was changed.');
      expect(jobErrorText('RuntimeError: solved but invalid')).toEqual({
        text: 'the solver stopped with an error. Nothing was changed.',
        detail: 'RuntimeError: solved but invalid',
      });
      expect(jobErrorText('The solver failed. An administrator can see the details in the audit log.').detail).toBeNull();
      expect(jobErrorText(undefined).text).toBe('the solver stopped with an error. Nothing was changed.');
    });

    it('a repair whose server restarted, with Discard; the raw exception only behind Details', async () => {
      const backend = await openHttp();
      backend.repair = job('rep-1', 'repair', { status: 'error', error: 'server restarted' });
      markAbsent();
      await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent('The repair failed: the server restarted while it ran. Nothing was changed.'));
      expect(screen.getByTestId('discard-repair')).toBeInTheDocument();
      expect(screen.queryByTestId('retry-repair')).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId('discard-repair'));

      backend.repair = job('rep-1', 'repair', { status: 'error', error: 'BrokenProcessPool: gone' });
      markAbsent();
      await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent('the solver stopped with an error'));
      expect(screen.getByTestId('repair-status')).not.toHaveTextContent('BrokenProcessPool');
      expect(within(screen.getByTestId('repair-error-details')).getByText('BrokenProcessPool: gone')).not.toBeVisible();
    });

    it('a repair’s timeout is not "impossible" (D33)', async () => {
      const backend = await openHttp();
      backend.repair = job('rep-1', 'repair', { status: 'timeout', time_limit_s: 300 });
      markAbsent();
      await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent('No repair found within 300.0 s. This does not prove it is impossible.'));
      expect(screen.queryByTestId('infeasibility-panel')).not.toBeInTheDocument();
    });
  });
});

describe('3. "Done" holds only until the official timetable changes otherwise', () => {
  const generateToDone = async (backend: ReturnType<typeof mockBackend>) => {
    backend.solve = job('solve-1', 'solve', { status: 'solved', solution });
    clickGenerate();
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveTextContent('Done: the grid and quality score show the new timetable.'));
  };
  const change = {
    job_id: 'old-1',
    change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 4, period: 0 }] },
    requested_by: 'a',
    accepted_by: 'a',
    accepted_at: '2026-11-01T09:00:00Z',
  };

  it('Clear accepted changes takes the message away, and the panel is usable', async () => {
    const backend = await openHttp('administrator', JOB_ANSWER_WITHIN_MS, [change]);
    await generateToDone(backend);
    fireEvent.click(await screen.findByTestId('clear-changes'));
    fireEvent.click(screen.getByTestId('confirm-clear-button'));
    await waitFor(() => expect(screen.queryByTestId('solve-status')).not.toBeInTheDocument());
    expect(screen.getByTestId('solve-button')).toBeEnabled();
    expect(screen.getByTestId('solve-button')).toHaveTextContent('Generate');
  });

  it('Accepting a repair takes it away', async () => {
    const backend = await openHttp();
    await generateToDone(backend);
    backend.repair = job('rep-1', 'repair', { status: 'solved', solution, change: change.change, base: 'solve-1' });
    markAbsent();
    const accept = await screen.findByTestId('accept-repair');
    await waitFor(() => expect(accept).toBeEnabled());
    expect(screen.getByTestId('solve-status')).toBeInTheDocument();
    fireEvent.click(accept);
    await waitFor(() => expect(screen.getByTestId('repair-status')).toHaveTextContent('Accepted'));
    expect(screen.queryByTestId('solve-status')).not.toBeInTheDocument();
  });

  it('Discarding a proposal changes nothing official: the message stays', async () => {
    const backend = await openHttp();
    await generateToDone(backend);
    backend.repair = job('rep-1', 'repair', { status: 'solved', solution, change: change.change, base: 'solve-1' });
    markAbsent();
    fireEvent.click((await screen.findAllByTestId('discard-repair'))[0]);
    expect(screen.getByTestId('solve-status')).toHaveTextContent('Done:');
  });

  it('A solve still running keeps its status through a Clear: it reports for itself when it ends (D56)', async () => {
    const backend = await openHttp('administrator', JOB_ANSWER_WITHIN_MS, [change]);
    backend.solve = job('solve-1', 'solve', { status: 'running', phase: 'search' });
    clickGenerate();
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'running'));
    fireEvent.click(await screen.findByTestId('clear-changes'));
    fireEvent.click(screen.getByTestId('confirm-clear-button'));
    await screen.findByTestId('no-accepted-changes');
    expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'running');
    expect(screen.getByTestId('solve-button')).toBeDisabled();
  });

  it('a new Generate does not show the old "Done" beside "Generating…"', async () => {
    const backend = await openHttp('administrator', 200);
    await generateToDone(backend);
    backend.hangSolve = true;
    clickGenerate();
    expect(screen.getByTestId('solve-button')).toHaveTextContent('Generating…');
    expect(screen.queryByTestId('solve-status')).not.toBeInTheDocument();
  });
});

describe('4. Generate asks first (D56)', () => {
  it('asks before anything is sent; Cancel sends nothing and gives the focus back', async () => {
    const backend = await openHttp();
    fireEvent.click(screen.getByTestId('solve-button'));
    const confirm = screen.getByTestId('confirm-generate');
    expect(confirm).toHaveTextContent('Generate makes a new timetable and replaces the official one for everyone. Continue?');
    expect(screen.getByRole('group', { name: /replaces the official one/ })).toBe(confirm);
    expect(screen.getByTestId('confirm-generate-button')).toHaveTextContent('Generate');
    const cancel = screen.getByTestId('cancel-generate');
    expect(cancel).toHaveTextContent('Cancel');
    expect(cancel).toHaveFocus();
    expect(screen.getByTestId('solve-button')).toBeDisabled();
    expect(backend.solvePosts).toBe(0);

    fireEvent.click(cancel);
    expect(screen.queryByTestId('confirm-generate')).not.toBeInTheDocument();
    expect(screen.getByTestId('solve-button')).toHaveFocus();
    expect(backend.solvePosts).toBe(0);
  });

  it('Generate in the question starts it with the time limit shown', async () => {
    const backend = await openHttp();
    fireEvent.change(screen.getByTestId('solve-time-limit'), { target: { value: '45' } });
    clickGenerate();
    expect(screen.queryByTestId('confirm-generate')).not.toBeInTheDocument();
    await waitFor(() => expect(backend.solvePosts).toBe(1));
    const posted = vi.mocked(fetch).mock.calls.find(([url]) => url === `/api/instances/${REAL_INSTANCE}/solve`)!;
    expect(JSON.parse((posted[1] as RequestInit).body as string)).toEqual({ time_limit_s: 45 });
  });
});

describe('6. the audit log on a restored timetable', () => {
  const row = (detail: Record<string, unknown>): AuditEntry => ({ id: 1, actor: 'demo_seed', action: 'solve', timestamp: '2026-11-01T09:00:00Z', detail });
  const say = (entry: AuditEntry) => auditSentence(entry, [entry], () => '');

  it('says restored when the solve row’s source is solution.json', () => {
    expect(say(row({ instance_id: REAL_INSTANCE, source: 'solution.json', status: 'solved' }))).toBe('demo_seed restored the committed timetable.');
  });

  it('a real solve, by anyone, is still a solve', () => {
    expect(say(row({ status: 'solved', time_limit_s: 300 }))).toBe('demo_seed asked the solver to generate a timetable. A timetable was found.');
  });

  it('http: on the page, by an administrator', async () => {
    const backend = mockBackend();
    const fetchMock = vi.mocked(fetch);
    const original = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url, init) =>
      String(url).startsWith('/api/audit') ? json([row({ source: 'solution.json', status: 'solved' })]) : original(url, init)
    );
    setSession({ username: 'test-administrator', token: 'token-administrator', role: 'administrator' });
    render(<App client={new HttpChronosApiClient('/api')} />);
    expect(backend.solvePosts).toBe(0);
    const sentence = await screen.findByTestId('audit-sentence');
    expect(sentence).toHaveTextContent('demo_seed restored the committed timetable.');
    expect(sentence).not.toHaveTextContent('asked the solver');
  });
});

describe('7. smaller things', () => {
  describe('the details window names the day and the time', () => {
    const labels = () => labelsFor(display);
    const lecture = () => sessions.find((s) => s.durationPeriods === 1 && s.periods[0] === 1) ?? sessions.find((s) => s.durationPeriods === 1)!;

    it('the wording, from the instance’s own clock times', () => {
      expect(sessionWhenText({ day: 3, periods: [1] }, labels())).toBe('Thursday T1, 10:00 AM–11:00 AM');
      expect(sessionWhenText({ day: 3, periods: [0] }, labels())).toBe('Thursday T0, 9:00 AM–10:00 AM');
      expect(sessionWhenText({ day: 0, periods: [6, 7] }, labels())).toBe('Monday T6–T7, 2:15 PM–4:15 PM');
      // a lab run across the short break, from the start of the first to the end of the last
      expect(sessionWhenText({ day: 1, periods: [1, 3] }, labels())).toBe('Tuesday T1–T3, 10:00 AM–12:15 PM');
      // the contract examples have no clock times
      expect(sessionWhenText({ day: 3, periods: [1] }, EXAMPLE_LABELS)).toBe('Thursday T1');
    });

    it('in the window, never "Starts at"', () => {
      const s = lecture();
      render(<SessionDetailModal session={s} labels={labels()} onClose={() => {}} />);
      expect(screen.getByTestId('session-when').textContent).toBe(sessionWhenText(s, labels()));
      expect(screen.getByRole('dialog')).not.toHaveTextContent('Starts at');
    });

    it.each(BOTH_MODES)('%s: in the app', async (_mode, openIt) => {
      await openIt();
      const s = lecture();
      fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: s.cohortId } });
      fireEvent.click(screen.getByTestId(`session-cell-${s.sessionId}`));
      expect(within(screen.getByRole('dialog')).getByTestId('session-when')).toHaveTextContent(/^(Mon|Tues|Wednes|Thurs|Fri)day T\d, \d+:\d\d [AP]M–\d+:\d\d [AP]M$/);
    });
  });

  describe('over the limit, said once', () => {
    it('the wording', () => {
      expect(loadLimitChange(18, 19, 16)).toEqual({ text: '18 h → 19 h, over the 16 h limit', over: true });
      expect(loadLimitChange(16, 17, 16)).toEqual({ text: '16 h → 17 h, over the 16 h limit', over: true });
      expect(loadLimitChange(19, 18, 16)).toEqual({ text: '19 h → 18 h, over the 16 h limit', over: true });
      expect(loadLimitChange(17, 15, 16)).toEqual({ text: '17 h → 15 h, back within the 16 h limit', over: false });
      expect(loadLimitChange(18, 18, 16)).toEqual({ text: 'Over 16 h limit: 18 h', over: true });
      expect(loadLimitChange(14, 15, 16)).toBeNull();
      expect(loadLimitChange(18, 19, null)).toBeNull();
    });

    it('one warning, not two side by side; coming back within it is no warning', () => {
      const { rerender } = render(<LoadLimitChange before={18} after={19} limit={16} />);
      expect(screen.getAllByTestId('load-over-limit')).toHaveLength(1);
      expect(screen.getByTestId('load-over-limit')).toHaveTextContent('18 h → 19 h, over the 16 h limit');
      rerender(<LoadLimitChange before={17} after={15} limit={16} />);
      expect(screen.queryByTestId('load-over-limit')).not.toBeInTheDocument();
      expect(screen.getByTestId('load-back-within')).toHaveTextContent('17 h → 15 h, back within the 16 h limit');
    });
  });

  it('the Free rooms card is as tall as its content, not stretched beside the room timetable', () => {
    render(<FreeRoomsPanel edgeList={edgeList} sessions={sessions} labels={labelsFor(display)} />);
    expect(screen.getByTestId('free-rooms')).toHaveClass('self-start');
  });

  it.each(BOTH_MODES)('%s: the skip link is the first tab stop, and it is there before the page has loaded', async (_mode, openIt) => {
    await openIt();
    const focusable = document.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), [tabindex="0"]');
    expect(focusable[0]).toBe(screen.getByTestId('skip-to-timetable'));
    expect(screen.getAllByTestId('skip-to-timetable')).toHaveLength(1);
  });
});
