import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { HttpChronosApiClient, MockChronosApiClient, REAL_INSTANCE, setSession } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { SolvedSolution, isSolvedSolution } from '@/adapters/solution';
import {
  Display,
  EdgeList,
  EnrichedSession,
  buildEnrichedSessions,
  labelsFor,
  moveConflict,
} from '@/adapters/timetable';
import { parseSolution } from '@/api/contractValidation';

// The real instance's files, as the backend serves them
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

const repairJob = (fields: Record<string, unknown>) => ({
  id: 'rep-1',
  instance_id: REAL_INSTANCE,
  kind: 'repair',
  time_limit_s: 300,
  max_moves: 20000,
  base: 'committed',
  status: 'queued',
  ...fields,
});

/** The S14c backend: the real instance, one repair job and its accept, whose answers the test sets. */
function mockBackend() {
  const state = {
    job: repairJob({}) as Record<string, unknown>,
    accept: () => json({ ...state.job, accepted_at: '2026-10-21T12:00:00Z' }),
    jobs: {} as Record<string, unknown>,
    posted: [] as unknown[],
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
    if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
      state.posted.push(JSON.parse(init?.body as string));
      return json({ job_id: 'rep-1', status: 'queued' }, 202);
    }
    if (url === '/api/jobs/rep-1/accept') return state.accept();
    if (url === '/api/jobs/rep-1') return json(state.job);
    if (url.startsWith('/api/jobs/')) return json(state.jobs[url.slice('/api/jobs/'.length)]);
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

const openReal = async (role: UserRole = 'coordinator') => {
  const backend = mockBackend();
  setSession({ username: `test-${role}`, token: `token-${role}`, role });
  render(<App client={new HttpChronosApiClient('/api')} />);
  await screen.findByTestId('timetable-grid');
  fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
  await screen.findByTestId('period-clock-0');
  return backend;
};

const SLOTS = [0, 1, 2, 3, 4].flatMap((day) => [0, 1, 3, 4, 5, 6, 7, 8, 9].map((period) => ({ day, period })));
const theory = (s: EnrichedSession) => !s.labBlockId && s.durationPeriods === 1;
const conflict = (s: EnrichedSession, day: number, period: number) =>
  moveConflict(edgeList, labelsFor(display), sessions, s.sessionId, day, period);

/** A theory session and a slot whose grid cell is on screen (not under a lab block), clean or clashing. */
function pickMove(clean: boolean) {
  for (const s of sessions.filter(theory)) {
    for (const { day, period } of SLOTS) {
      if (day === s.day && period === s.wallClockPeriod) continue;
      const reason = conflict(s, day, period);
      const wanted = clean ? reason === null : reason?.startsWith('Cohort clash');
      if (wanted && screen.queryByTestId(`grid-cell-${day}-${period}`)) return { s, day, period, reason };
    }
  }
  throw new Error('no such move in the real timetable');
}

const drop = (sessionId: string, day: number, period: number) =>
  fireEvent.drop(screen.getByTestId(`grid-cell-${day}-${period}`), { dataTransfer: { getData: () => sessionId } });

const moveChange = (s: EnrichedSession, day: number, period: number) => ({
  kind: 'move_session',
  session_id: s.sessionId,
  day,
  period,
  room_id: s.roomId,
  ...(s.subRoomId ? { sub_room_id: s.subRoomId } : {}),
});

/** The repair result: the moved session at its new slot (displaced), another re-roomed, a new score. */
function repaired(moved: string, day: number, period: number, reRoomed: string): SolvedSolution {
  return {
    ...solution,
    assignment: solution.assignment.map((a) =>
      a.session_id === moved
        ? { ...a, day, period }
        : a.session_id === reRoomed
          ? { ...a, room_id: a.room_id === 'room-605' ? 'room-609' : 'room-605', sub_room_id: null }
          : a
    ),
    displaced: [moved],
    quality: { ...solution.quality, score: solution.quality.score - 1.5 },
  } as SolvedSolution;
}

const status = () => screen.getByTestId('repair-status');

describe('Repair in the app (http mode, S14d)', () => {
  it.each([
    ['administrator', true],
    ['coordinator', true],
    ['faculty', false],
    ['student', false],
  ] as const)('offers repair and drag to the logged-in %s: %s', async (role, offered) => {
    await openReal(role);
    expect(!!screen.queryByTestId('repair-panel')).toBe(offered);
    expect(!!screen.queryAllByTestId(/^drop-slot-/).length).toBe(offered);
  });

  it('a clean drag posts a move repair; a solved result highlights slot and room changes and the score change', async () => {
    const backend = await openReal();
    const { s, day, period } = pickMove(true);
    const other = sessions.find((o) => theory(o) && o.sessionId !== s.sessionId)!;
    const result = repaired(s.sessionId, day, period, other.sessionId);
    backend.job = repairJob({ status: 'solved', change: moveChange(s, day, period), solution: result });

    drop(s.sessionId, day, period);
    await screen.findByTestId('repair-proposal');
    expect(backend.posted).toEqual([{ change: moveChange(s, day, period) }]);
    expect(screen.queryByTestId('rejection-alert')).not.toBeInTheDocument();

    await screen.findByTestId(`repair-change-${s.sessionId}`);
    expect(screen.getByTestId(`repair-change-${s.sessionId}`)).toHaveAttribute('data-change', 'slot');
    expect(screen.getByTestId(`repair-change-${other.sessionId}`)).toHaveAttribute('data-change', 'room');
    const score = solution.quality.score;
    expect(screen.getByTestId('repair-score')).toHaveTextContent(`${score.toFixed(1)} → ${(score - 1.5).toFixed(1)} (-1.5)`);

    // the grid shows the proposal: the moved session at its new slot, both changes outlined
    expect(screen.getByTestId('proposal-note')).toBeInTheDocument();
    const cell = screen.getByTestId(`grid-cell-${day}-${period}`);
    const card = within(cell).getByTestId(`session-cell-${s.sessionId}`).closest('[data-flagged]');
    expect(card).toHaveClass('ring-amber-500');
    expect(screen.getByTestId(`session-cell-${other.sessionId}`).closest('[data-flagged]')).toBeInTheDocument();
    // no second repair or drag while one waits
    expect(screen.queryAllByTestId(/^drop-slot-/)).toHaveLength(0);
    expect(screen.getByTestId('mark-unavailable-button')).toBeDisabled();
  });

  it('a clashing drag names the clash and offers "Repair around this", which posts the move', async () => {
    const backend = await openReal();
    const { s, day, period, reason } = pickMove(false);
    drop(s.sessionId, day, period);
    expect(await screen.findByTestId('rejection-reason')).toHaveTextContent(reason!);
    expect(backend.posted).toEqual([]);

    backend.job = repairJob({ status: 'running', phase: 'repair' });
    fireEvent.click(screen.getByTestId('repair-around-this'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'running'));
    expect(backend.posted).toEqual([{ change: moveChange(s, day, period) }]);
    expect(screen.queryByTestId('rejection-alert')).not.toBeInTheDocument();
  });

  it('Accept makes the result official; Discard returns to the official timetable', async () => {
    const backend = await openReal();
    const { s, day, period } = pickMove(true);
    const other = sessions.find((o) => theory(o) && o.sessionId !== s.sessionId)!;
    backend.job = repairJob({ status: 'solved', solution: repaired(s.sessionId, day, period, other.sessionId) });
    drop(s.sessionId, day, period);
    fireEvent.click(await screen.findByTestId('discard-repair'));
    await waitFor(() => expect(screen.queryByTestId('repair-proposal')).not.toBeInTheDocument());
    expect(screen.queryByTestId('proposal-note')).not.toBeInTheDocument();
    expect(within(screen.getByTestId(`grid-cell-${day}-${period}`)).queryByTestId(`session-cell-${s.sessionId}`)).not.toBeInTheDocument();

    drop(s.sessionId, day, period);
    await screen.findByTestId(`repair-change-${s.sessionId}`);
    fireEvent.click(screen.getByTestId('accept-repair'));
    await waitFor(() => expect(status()).toHaveTextContent('Accepted: the repaired timetable is now the official one.'));
    expect(screen.queryByTestId('proposal-note')).not.toBeInTheDocument();
    expect(within(screen.getByTestId(`grid-cell-${day}-${period}`)).getByTestId(`session-cell-${s.sessionId}`)).toBeInTheDocument();
    expect(screen.getByTestId('quality-score')).toHaveTextContent((solution.quality.score - 1.5).toFixed(1));
  });

  it('a 409 on Accept says the timetable changed meanwhile', async () => {
    const backend = await openReal();
    const { s, day, period } = pickMove(true);
    const other = sessions.find((o) => theory(o) && o.sessionId !== s.sessionId)!;
    backend.job = repairJob({ status: 'solved', solution: repaired(s.sessionId, day, period, other.sessionId) });
    backend.accept = () => json({ detail: 'the timetable this repair started from is no longer official' }, 409);
    drop(s.sessionId, day, period);
    await screen.findByTestId(`repair-change-${s.sessionId}`);
    fireEvent.click(screen.getByTestId('accept-repair'));
    expect(await screen.findByTestId('accept-error')).toHaveTextContent('The timetable changed meanwhile. Run the repair again.');
    expect(screen.getByTestId('accept-repair')).toBeDisabled();
  });

  it('compares with the base job’s solution when the repair started from one (D48)', async () => {
    const backend = await openReal();
    const { s, day, period } = pickMove(true);
    const other = sessions.find((o) => theory(o) && o.sessionId !== s.sessionId)!;
    // the base job has `other` in another room than the official solution
    const base = repaired(s.sessionId, s.day, s.wallClockPeriod, other.sessionId);
    backend.jobs['solve-9'] = { id: 'solve-9', instance_id: REAL_INSTANCE, kind: 'solve', time_limit_s: 300, status: 'solved', solution: base };
    const result = { ...solution, assignment: solution.assignment.map((a) => (a.session_id === s.sessionId ? { ...a, day, period } : a)), displaced: [s.sessionId] };
    backend.job = repairJob({ status: 'solved', base: 'solve-9', solution: result });
    drop(s.sessionId, day, period);
    expect(await screen.findByTestId(`repair-change-${other.sessionId}`)).toHaveAttribute('data-change', 'room');
  });

  it('marks a faculty member unavailable at picked slots, then a room, as repairs', async () => {
    const backend = await openReal('administrator');
    const panel = screen.getByTestId('repair-panel');
    backend.job = repairJob({ status: 'timeout' });
    const facultySelect = within(panel).getByLabelText('Unavailable faculty member');
    expect(within(facultySelect).getByRole('option', { name: 'Swapnali Kurhade (SK)' })).toBeInTheDocument();
    fireEvent.change(facultySelect, { target: { value: 'fac-swapnali-kurhade' } });
    expect(screen.getByTestId('mark-unavailable-button')).toBeDisabled();
    fireEvent.click(within(panel).getByLabelText('Tuesday P6'));
    fireEvent.click(within(panel).getByLabelText('Tuesday P7'));
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'timeout'));
    expect(backend.posted[0]).toEqual({
      change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 1, period: 6 }, { day: 1, period: 7 }] },
    });
    // D33: a timeout is no repair found, never infeasible
    expect(status()).toHaveTextContent('No repair found within 300 s. This does not prove it is impossible.');
    expect(screen.queryByTestId('infeasibility-panel')).not.toBeInTheDocument();

    fireEvent.change(within(panel).getByLabelText('Unavailable kind'), { target: { value: 'room' } });
    fireEvent.change(within(panel).getByLabelText('Unavailable room'), { target: { value: 'room-603' } });
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));
    await waitFor(() => expect(backend.posted).toHaveLength(2));
    expect(backend.posted[1]).toEqual({
      change: { kind: 'room_unavailable', room_id: 'room-603', slots: [{ day: 1, period: 6 }, { day: 1, period: 7 }] },
    });
  });

  it('an infeasible repair shows its conflicting set and verified relaxation by name (display.json)', async () => {
    const backend = await openReal();
    const kurhade = sessions.find((x) => x.facultyId === 'fac-swapnali-kurhade')!;
    const infeasible = parseSolution({
      schema_version: 'solution.v2',
      status: 'infeasible',
      diagnosis: {
        method: 'mus',
        minimal_conflicting_set: [
          {
            constraint_id: 'mus.faculty_unavailable.kurhade',
            kind: 'FACULTY_UNAVAILABLE',
            description: 'Swapnali Kurhade is unavailable all Tuesday.',
            entity_ids: ['fac-swapnali-kurhade', kurhade.sessionId, kurhade.cohortId, 'room-603'],
            slots: [{ day: 1, period: 0 }],
          },
          {
            constraint_id: 'mus.pinned.te-lunch-mon',
            kind: 'PINNED_BLOCK',
            description: 'TE lunch holds TE-Comp A on Monday P4.',
            entity_ids: ['coh-te-a'],
            slots: [{ day: 0, period: 4 }],
          },
        ],
        suggested_relaxation: {
          constraint_id: 'mus.faculty_unavailable.kurhade',
          description: 'Let Swapnali Kurhade teach on Tuesday P0.',
          action: { action_type: 'RELAX_FACULTY_AVAILABILITY', params: { faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 1, period: 0 }] } },
          verification: { status: 'restored', runtime_ms: 12 },
        },
        partial_placement: [],
        unplaced_session_ids: [kurhade.sessionId],
      },
      metadata: { algorithm: 'repair', runtime_ms: 40, sessions_total: 156, sessions_assigned: 155, slots_used: null, backtracks: 3 },
    });
    backend.job = repairJob({ status: 'infeasible', solution: infeasible });
    fireEvent.change(screen.getByLabelText('Unavailable faculty member'), { target: { value: 'fac-swapnali-kurhade' } });
    fireEvent.click(screen.getByLabelText('Tuesday P0'));
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));

    const panel = await screen.findByTestId('infeasibility-panel');
    const first = within(panel).getByTestId('conflicting-constraint-mus.faculty_unavailable.kurhade');
    const names = ['Swapnali Kurhade (SK)', kurhade.cohortLabel, 'Room 603', `${kurhade.subjectCode} · ${kurhade.cohortLabel} · Swapnali Kurhade (SK)`];
    for (const name of names) {
      expect(within(first).getByText(name)).toBeInTheDocument();
    }
    expect(within(first).queryByText('fac-swapnali-kurhade')).not.toBeInTheDocument();
    expect(within(panel).getByTestId('constraint-pins-mus.pinned.te-lunch-mon')).toHaveTextContent('TE lunch, Mon P4');
    expect(within(panel).getByTestId('relaxation-action')).toHaveTextContent('verification: restored (12 ms)');
    expect(within(panel).getByTestId('relaxation-applies-to')).toHaveTextContent('Swapnali Kurhade (SK); Tuesday P0');
    expect(status()).toHaveAttribute('data-status', 'infeasible');
  });
});

describe('Accounts linked to a faculty member or cohort (D50)', () => {
  const logInWith = async (role: UserRole, link: Record<string, string | null>) => {
    mockBackend();
    const fetchMock = vi.mocked(fetch);
    const backend = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation(async (url, init) =>
      url === '/api/auth/login' ? json({ access_token: 'h.e30.sig', token_type: 'bearer', role, ...link }) : backend(url, init)
    );
    render(<App client={new HttpChronosApiClient('/api')} />);
    fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'linked' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByTestId('login-button'));
    await screen.findByTestId('timetable-grid');
  };

  it('a linked faculty login opens on the real timetable, locked to that teacher', async () => {
    await logInWith('faculty', { faculty_id: 'fac-swapnali-kurhade', cohort_id: null });
    await screen.findByTestId('period-clock-0');
    const picker = screen.getByLabelText('Select faculty persona');
    expect(picker).toBeDisabled();
    expect(picker).toHaveValue('fac-swapnali-kurhade');
    expect(screen.getByLabelText('Select instance')).toHaveValue(REAL_INSTANCE);
  });

  it('a linked student login is locked to that cohort', async () => {
    await logInWith('student', { faculty_id: null, cohort_id: 'coh-se-a' });
    await screen.findByTestId('period-clock-0');
    const picker = screen.getByLabelText('Select student division');
    expect(picker).toBeDisabled();
    expect(picker).toHaveValue('coh-se-a');
  });

  it('without a link the picker stays as it was', async () => {
    await logInWith('faculty', { faculty_id: null, cohort_id: null });
    expect(screen.getByLabelText('Select faculty persona')).toBeEnabled();
    expect(screen.getByLabelText('Select instance')).toHaveValue('example');
  });
});
