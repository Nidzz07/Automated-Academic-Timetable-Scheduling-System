import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { InfeasibilityDiagnosisPanel } from '@/components/timetable/InfeasibilityDiagnosisPanel';
import { HttpChronosApiClient, MockChronosApiClient, REAL_INSTANCE, setSession } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { SolvedSolution, isInfeasibleSolution, isSolvedSolution } from '@/adapters/solution';
import {
  Display,
  EdgeList,
  EnrichedSession,
  buildEnrichedSessions,
  entityName,
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

/**
 * The S14c-S14g backend: the real instance, one repair job, its base solution and its accept,
 * the accepted changes and a session's substitutes, whose answers the test sets.
 */
function mockBackend() {
  const state = {
    job: repairJob({}) as Record<string, unknown>,
    accept: () => json({ ...state.job, accepted_at: '2026-10-21T12:00:00Z' }),
    jobs: {} as Record<string, unknown>,
    posted: [] as unknown[],
    /** GET /jobs/rep-1/base-solution; the committed solution when unset */
    base: null as unknown,
    changes: [] as unknown[],
    cleared: 0,
    substitutes: null as unknown,
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
    if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
      state.posted.push(JSON.parse(init?.body as string));
      return json({ job_id: 'rep-1', status: 'queued' }, 202);
    }
    if (url === `/api/instances/${REAL_INSTANCE}/changes`) {
      if (init?.method !== 'DELETE') return json(state.changes);
      const cleared = state.changes;
      state.changes = [];
      state.cleared += 1;
      return json(cleared);
    }
    if (url.startsWith(`/api/instances/${REAL_INSTANCE}/sessions/`)) return json(state.substitutes);
    if (url === '/api/jobs/rep-1/accept') return state.accept();
    if (url === '/api/jobs/rep-1/base-solution') return json(state.base ?? solution);
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

const openReal = async (role: UserRole = 'coordinator', setUp?: (backend: ReturnType<typeof mockBackend>) => void) => {
  const backend = mockBackend();
  setUp?.(backend);
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

  it('compares with GET /jobs/{id}/base-solution, the solution the repair started from (D48)', async () => {
    const backend = await openReal();
    const { s, day, period } = pickMove(true);
    const other = sessions.find((o) => theory(o) && o.sessionId !== s.sessionId)!;
    // the base has `other` in another room than the official solution
    backend.base = repaired(s.sessionId, s.day, s.wallClockPeriod, other.sessionId);
    const result = { ...solution, assignment: solution.assignment.map((a) => (a.session_id === s.sessionId ? { ...a, day, period } : a)), displaced: [s.sessionId] };
    backend.job = repairJob({ status: 'solved', base: 'solve-9', solution: result });
    drop(s.sessionId, day, period);
    expect(await screen.findByTestId(`repair-change-${other.sessionId}`)).toHaveAttribute('data-change', 'room');
    const urls = vi.mocked(fetch).mock.calls.map(([url]) => url);
    expect(urls).toContain('/api/jobs/rep-1/base-solution');
    // neither the base job nor the official solution stands in for the base
    expect(urls).not.toContain('/api/jobs/solve-9');
    expect(urls.filter((u) => u === `/api/instances/${REAL_INSTANCE}/solution`)).toHaveLength(1);
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
            constraint_id: 'pin.0',
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
    // D51: pin.0 is pinned_occupancy[0], named by display.json pins[0]
    expect(within(panel).getByTestId('constraint-pins-pin.0')).toHaveTextContent('Pinned: TE lunch, Mon P4 (pin.0)');
    expect(within(panel).getByTestId('relaxation-action')).toHaveTextContent('verification: restored (12 ms)');
    expect(within(panel).getByTestId('relaxation-applies-to')).toHaveTextContent('Swapnali Kurhade (SK); Tuesday P0');
    expect(status()).toHaveAttribute('data-status', 'infeasible');
  });
});

describe('Diagnosis pins by pin.<i> (S14h, D51)', () => {
  it('names a pin relaxation by its constraint id, not by the slot and entity it frees', () => {
    const infeasible = parseSolution({
      schema_version: 'solution.v2',
      status: 'infeasible',
      diagnosis: {
        method: 'mus',
        minimal_conflicting_set: [
          {
            constraint_id: 'pin.1',
            kind: 'PINNED_BLOCK',
            description: 'Pinned occupancy 1 holds coh-se-a at Monday P5.',
            entity_ids: ['coh-se-a'],
            slots: [{ day: 0, period: 5 }],
          },
        ],
        suggested_relaxation: {
          constraint_id: 'pin.1',
          description: 'Free SE-Comp A on Monday P5.',
          action: { action_type: 'RELAX_PINNED_BLOCK', params: { slot: { day: 0, period: 5 }, entity_kind: 'cohort', entity_id: 'coh-se-a' } },
          verification: { status: 'restored', runtime_ms: 3 },
        },
        partial_placement: [],
        unplaced_session_ids: [edgeList.sessions[0].id],
      },
      metadata: { algorithm: 'repair', runtime_ms: 10, sessions_total: 156, sessions_assigned: 155, slots_used: null, backtracks: 0 },
    });
    if (!isInfeasibleSolution(infeasible)) throw new Error('expected an infeasible payload');
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={infeasible} edgeList={edgeList} labels={labelsFor(display)} />);
    const pin = `${display.pins[1].unique_label} (pin.1)`;
    expect(screen.getByTestId('constraint-pins-pin.1')).toHaveTextContent(`Pinned: ${pin}`);
    expect(screen.getByTestId('relaxation-applies-to')).toHaveTextContent(`SE-Comp A; pin ${pin}; Monday P5`);
  });
});

const LECTURE = 'obs-t0-r1-c3-l0'; // CE207 lecture of SE-Comp A, Anant Nimkar (backend/tests/test_substitution.py)
const BHAVATHANKAR = 'fac-prasenjit-bhavathankar';
const substitution = { kind: 'substitute_faculty', session_id: LECTURE, faculty_id: BHAVATHANKAR };
const openSession = (sessionId: string) => fireEvent.click(screen.getByTestId(`session-cell-${sessionId}`));
/** Show SE-Comp A (whose lecture it is), or the teacher, so no lab block of another division covers its cell. */
const showLecture = (role: UserRole, teacher = 'fac-anant-nimkar') => {
  const [label, value] =
    role === 'faculty'
      ? ['Select faculty persona', teacher]
      : role === 'student'
        ? ['Select student division', 'coh-se-a']
        : ['Filter timetable by division', 'coh-se-a'];
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
};

describe('Accepted changes (S14h, D52)', () => {
  const accepted = [
    {
      job_id: 'rep-7',
      change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 1, period: 6 }, { day: 1, period: 7 }] },
      requested_by: 'coord-1',
      accepted_by: 'admin-1',
      accepted_at: '2026-10-22T09:30:00Z',
    },
    { job_id: 'rep-8', change: { kind: 'room_unavailable', room_id: 'room-603', slots: [{ day: 0, period: 1 }] }, requested_by: 'coord-1', accepted_by: null, accepted_at: '2026-10-22T09:45:00Z' },
    { job_id: 'rep-9', change: substitution, requested_by: 'coord-2', accepted_by: 'coord-2', accepted_at: '2026-10-22T10:00:00Z' },
  ];

  it('lists who, when and what by name; the grid shows the accepted substitute; an administrator clears them after confirming', async () => {
    const backend = await openReal('administrator', (b) => {
      b.changes = accepted;
    });
    const panel = await screen.findByTestId('accepted-changes');
    const row = (id: string) => within(panel).getByTestId(`accepted-change-${id}`);
    await waitFor(() => expect(row('rep-7')).toHaveTextContent('Swapnali Kurhade (SK) unavailable: Tuesday P6, Tuesday P7'));
    expect(row('rep-7')).toHaveTextContent('coord-1');
    expect(row('rep-7')).toHaveTextContent('admin-1');
    expect(row('rep-7')).toHaveTextContent(new Date('2026-10-22T09:30:00Z').toLocaleString());
    expect(row('rep-8')).toHaveTextContent('Room 603 unavailable: Monday P1');
    expect(row('rep-8')).toHaveTextContent('not recorded');
    expect(row('rep-9')).toHaveTextContent('CE207 · SE-Comp A: taught by Prasenjit Bhavathankar (PBB)');

    // D52: the accepted substitute teaches the session now
    showLecture('administrator');
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Prasenjit Bhavathankar')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog')).getByText('Close'));

    fireEvent.click(within(panel).getByTestId('clear-changes'));
    expect(within(panel).getByTestId('confirm-clear')).toHaveTextContent('Clear all 3 accepted changes?');
    fireEvent.click(within(panel).getByText('Cancel'));
    expect(within(panel).queryByTestId('confirm-clear')).not.toBeInTheDocument();
    expect(backend.cleared).toBe(0);

    fireEvent.click(within(panel).getByTestId('clear-changes'));
    fireEvent.click(within(panel).getByTestId('confirm-clear-button'));
    expect(await within(panel).findByTestId('no-accepted-changes')).toBeInTheDocument();
    expect(backend.cleared).toBe(1);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/instances/${REAL_INSTANCE}/changes`, expect.objectContaining({ method: 'DELETE' }));
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Anant Nimkar')).toBeInTheDocument();
  });

  it.each([
    ['coordinator', true],
    ['faculty', false],
    ['student', false],
  ] as const)('the %s sees the list: %s, and never Clear', async (role, listed) => {
    await openReal(role, (b) => {
      b.changes = accepted;
    });
    if (listed) await screen.findByTestId('accepted-change-rep-7');
    expect(!!screen.queryByTestId('accepted-changes')).toBe(listed);
    expect(screen.queryByTestId('clear-changes')).not.toBeInTheDocument();
  });
});

describe('Find substitute (S14h, D53)', () => {
  // backend/tests/test_substitution.py TestSubstitutes.test_lecture
  const listed = {
    session_id: LECTURE,
    faculty_id: 'fac-anant-nimkar',
    candidates: [
      { faculty_id: BHAVATHANKAR, score_change: 0.0 },
      { faculty_id: 'fac-nataasha-raul', score_change: -2.0 },
    ],
    left_out: [
      {
        faculty_id: 'fac-sudhir-dhage',
        reasons: ['busy'],
        violations: [{ kind: 'FACULTY_CLASH', session_ids: [LECTURE, 'obs-t6-r4-c4-l1'], slots: [], entity_ids: ['fac-sudhir-dhage'], detail: '' }],
      },
    ],
  };

  it('lists candidates as "Name (INITIALS)" with the score change and why others were left out; a pick is proposed, then accepted', async () => {
    const backend = await openReal('coordinator', (b) => {
      b.substitutes = listed;
    });
    showLecture('coordinator');
    openSession(LECTURE);
    fireEvent.click(screen.getByTestId('find-substitute'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const panel = await screen.findByTestId('substitute-panel');
    await within(panel).findByTestId(`substitute-${BHAVATHANKAR}`);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/instances/${REAL_INSTANCE}/sessions/${LECTURE}/substitutes`, expect.anything());
    expect(within(panel).getByTestId(`substitute-${BHAVATHANKAR}`)).toHaveTextContent('Prasenjit Bhavathankar (PBB)');
    expect(within(panel).getByTestId(`substitute-score-${BHAVATHANKAR}`)).toHaveTextContent('score +0.0');
    expect(within(panel).getByTestId('substitute-fac-nataasha-raul')).toHaveTextContent('Nataasha Raul (NR)');
    expect(within(panel).getByTestId('substitute-score-fac-nataasha-raul')).toHaveTextContent('score -2.0');
    expect(within(panel).getByTestId('left-out-fac-sudhir-dhage')).toHaveTextContent(
      `Sudhir Dhage (SND): busy (teaches ${entityName('obs-t6-r4-c4-l1', edgeList, labelsFor(display))} then)`
    );

    // nobody moves: the result is the official placement with the new teacher
    backend.job = repairJob({ status: 'solved', change: substitution, solution: { ...solution, displaced: [] } });
    fireEvent.click(within(panel).getByTestId(`substitute-${BHAVATHANKAR}`));
    await screen.findByTestId('repair-proposal');
    expect(backend.posted).toEqual([{ change: substitution }]);
    expect(screen.queryByTestId('substitute-panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('repair-change-text')).toHaveTextContent('Change: CE207 · SE-Comp A: taught by Prasenjit Bhavathankar (PBB)');
    await waitFor(() => expect(screen.getByTestId(`session-cell-${LECTURE}`).closest('[data-flagged]')).toBeInTheDocument());

    backend.changes = [{ job_id: 'rep-1', change: substitution, requested_by: 'test-coordinator', accepted_by: 'test-coordinator', accepted_at: '2026-10-21T12:00:00Z' }];
    fireEvent.click(screen.getByTestId('accept-repair'));
    await waitFor(() => expect(status()).toHaveTextContent('Accepted: the repaired timetable is now the official one.'));
    // the accepted list is read again, and the grid keeps the substitute once the proposal is gone
    expect(await screen.findByTestId('accepted-change-rep-1')).toHaveTextContent('taught by Prasenjit Bhavathankar (PBB)');
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Prasenjit Bhavathankar')).toBeInTheDocument();
  });

  it.each(['faculty', 'student'] as const)('is not offered to the %s', async (role) => {
    await openReal(role);
    showLecture(role);
    openSession(LECTURE);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByTestId('find-substitute')).not.toBeInTheDocument();
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
