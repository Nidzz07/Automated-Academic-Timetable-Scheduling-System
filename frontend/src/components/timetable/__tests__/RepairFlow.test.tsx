import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { clickGenerate } from '@/test/generate';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { InfeasibilityDiagnosisPanel } from '@/components/timetable/InfeasibilityDiagnosisPanel';
import { HttpChronosApiClient, MockChronosApiClient, REAL_INSTANCE, setSession } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { SolvedSolution, isInfeasibleSolution, isSolvedSolution } from '@/adapters/solution';
import {
  DAY_NAMES,
  Display,
  EdgeList,
  EnrichedSession,
  buildEnrichedSessions,
  sessionWithoutTeacher,
  facultyText,
  checkMove,
  labelsFor,
} from '@/adapters/timetable';
import { parseSolution } from '@/api/contractValidation';
import { displayText, formatScore, formatTimestamp } from '@/lib/format';

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

type Change = { kind: string; faculty_id?: string; room_id?: string; session_id?: string; slots?: Array<{ day: number; period: number }> };

/**
 * The committed edge list with these changes applied, as the backend builds the current and a
 * job's edge list (solver.repair.apply_change): absences into faculty_availability, a closed
 * room as one pinned_occupancy entry per slot, appended, and a substitute as the session's teacher.
 */
function withChanges(changes: Change[]): EdgeList {
  const changed: EdgeList = JSON.parse(JSON.stringify(edgeList));
  for (const c of changes) {
    if (c.kind === 'faculty_unavailable') {
      changed.faculty_availability.find((f) => f.faculty_id === c.faculty_id)!.unavailable_slots.push(...c.slots!);
    } else if (c.kind === 'room_unavailable') {
      changed.pinned_occupancy.push(...c.slots!.map((s) => ({ ...s, faculty_ids: [], room_ids: [c.room_id!], cohort_ids: [] })));
    } else if (c.kind === 'substitute_faculty') {
      changed.sessions.find((s) => s.id === c.session_id)!.faculty_id = c.faculty_id!;
    }
  }
  return changed;
}

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
 * The S14c-S14i backend: the real instance, one repair job, its base solution, its edge list and
 * its accept, the accepted changes, the current edge list, the official solution and a
 * session's substitutes, whose answers the test sets. A solve starts job solve-1 (state.jobs);
 * the audit log gets a row per solve, repair, accept and clear, a job's row showing its status now.
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
    /** GET .../edge-list/current; the committed edge list when unset (no accepted change) */
    current: null as EdgeList | null,
    /** GET /jobs/rep-1/edge-list; the current edge list when unset */
    jobEdgeList: null as EdgeList | null,
    /** GET .../solution; the committed solution when unset */
    official: null as unknown,
    /** What DELETE .../changes leaves official (D56); unchanged when unset */
    officialAfterClear: null as unknown,
    /** GET /audit, oldest first; served newest first */
    audit: [] as Array<{ action: string; job?: string; detail?: Record<string, unknown> }>,
  };
  const audit = (action: string, job?: string) => state.audit.push({ action, job });
  const jobStatus = (id: string) =>
    (id === 'rep-1' ? state.job : (state.jobs[id] as Record<string, unknown> | undefined))?.status;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
    if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
      state.posted.push(JSON.parse(init?.body as string));
      audit('repair', 'rep-1');
      return json({ job_id: 'rep-1', status: 'queued' }, 202);
    }
    if (url === `/api/instances/${REAL_INSTANCE}/solve`) {
      audit('solve', 'solve-1');
      return json({ job_id: 'solve-1', status: 'queued' }, 202);
    }
    if (url.startsWith('/api/audit?limit=')) {
      const rows = state.audit.map((r, i) => ({
        id: i + 1,
        actor: 'test-administrator',
        action: r.action,
        timestamp: '2026-10-28T10:00:00Z',
        detail: r.job ? { job_id: r.job, status: jobStatus(r.job) } : null,
      }));
      return json(rows.reverse().slice(0, Number(url.split('=')[1])));
    }
    if (url === `/api/instances/${REAL_INSTANCE}/changes`) {
      if (init?.method !== 'DELETE') return json(state.changes);
      const cleared = state.changes;
      state.changes = [];
      state.current = null;
      state.official = state.officialAfterClear ?? state.official;
      state.cleared += 1;
      audit('clear_changes');
      return json(cleared);
    }
    if (url === `/api/instances/${REAL_INSTANCE}/edge-list/current`) return json(state.current ?? edgeList);
    if (url === `/api/instances/${REAL_INSTANCE}/solution`) return json(state.official ?? solution);
    if (url.startsWith(`/api/instances/${REAL_INSTANCE}/sessions/`)) return json(state.substitutes);
    if (url === '/api/jobs/rep-1/accept') {
      audit('accept', 'rep-1');
      return state.accept();
    }
    if (url === '/api/jobs/rep-1/base-solution') return json(state.base ?? solution);
    if (url === '/api/jobs/rep-1/edge-list') return json(state.jobEdgeList ?? state.current ?? edgeList);
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
  fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
  await screen.findByTestId('period-clock-0');
  return backend;
};

const SLOTS = [0, 1, 2, 3, 4].flatMap((day) => [0, 1, 3, 4, 5, 6, 7, 8, 9].map((period) => ({ day, period })));
const theory = (s: EnrichedSession) => !s.labBlockId && s.durationPeriods === 1;
const conflict = (s: EnrichedSession, day: number, period: number) =>
  checkMove(edgeList, labelsFor(display), sessions, s.sessionId, day, period);

/** A theory session and a slot whose grid cell is on screen (not under a lab block), clean or with a cohort clash. */
function pickMove(clean: boolean) {
  for (const s of sessions.filter(theory)) {
    for (const { day, period } of SLOTS) {
      if (day === s.day && period === s.wallClockPeriod) continue;
      const check = conflict(s, day, period);
      const wanted = clean ? check === null : check?.clashes.some((c) => c.kind === 'cohort');
      if (wanted && screen.queryByTestId(`grid-cell-${day}-${period}`)) return { s, day, period, check };
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
    // drag: a draggable card; the drop targets exist only during a drag (S14t)
    expect(screen.queryAllByTestId(/^drag-handle-/).length > 0).toBe(offered);
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
    expect(screen.getByTestId('repair-score')).toHaveTextContent(`${formatScore(score)} → ${formatScore(score - 1.5)} (−1.5)`);

    // the grid shows the proposal: the moved session at its new slot, both changes outlined
    expect(screen.getByTestId('proposal-note')).toBeInTheDocument();
    const cell = screen.getByTestId(`grid-cell-${day}-${period}`);
    const card = within(cell).getByTestId(`session-cell-${s.sessionId}`).closest('[data-flagged]');
    expect(card).toHaveClass('ring-amber-500');
    expect(screen.getByTestId(`session-cell-${other.sessionId}`).closest('[data-flagged]')).toBeInTheDocument();
    // no second repair or drag while one waits
    expect(screen.queryAllByTestId(/^drag-handle-/)).toHaveLength(0);
    expect(screen.getByTestId('mark-unavailable-button')).toBeDisabled();
  });

  it('a clashing drag names every clash and offers "Repair around this", which posts the move', async () => {
    const backend = await openReal();
    const { s, day, period, check } = pickMove(false);
    drop(s.sessionId, day, period);
    expect(await screen.findByTestId('rejection-reason')).toHaveTextContent(
      `Clashes for ${s.subjectCode} (${s.cohortLabel}) at ${DAY_NAMES[day]} T${period}:`
    );
    expect(screen.getAllByTestId('rejection-clash').map((li) => li.textContent)).toEqual(check!.clashes.map((c) => c.text));
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
    expect(screen.getByTestId('quality-score')).toHaveTextContent(formatScore(solution.quality.score - 1.5));
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
    const facultySelect = within(panel).getByLabelText('Unavailable teacher');
    expect(within(facultySelect).getByRole('option', { name: 'Swapnali Kurhade (SK)' })).toBeInTheDocument();
    fireEvent.change(facultySelect, { target: { value: 'fac-swapnali-kurhade' } });
    expect(screen.getByTestId('mark-unavailable-button')).toBeDisabled();
    fireEvent.click(within(panel).getByLabelText('Tuesday T6'));
    fireEvent.click(within(panel).getByLabelText('Tuesday T7'));
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));
    await waitFor(() => expect(status()).toHaveAttribute('data-status', 'timeout'));
    expect(backend.posted[0]).toEqual({
      change: { kind: 'faculty_unavailable', faculty_id: 'fac-swapnali-kurhade', slots: [{ day: 1, period: 6 }, { day: 1, period: 7 }] },
    });
    // D33: a timeout is no repair found, never infeasible
    expect(status()).toHaveTextContent('No repair found within 300.0 s. This does not prove it is impossible.');
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
    fireEvent.change(screen.getByLabelText('Unavailable teacher'), { target: { value: 'fac-swapnali-kurhade' } });
    fireEvent.click(screen.getByLabelText('Tuesday T0'));
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));

    const panel = await screen.findByTestId('infeasibility-panel');
    const first = within(panel).getByTestId('conflicting-constraint-mus.faculty_unavailable.kurhade');
    const names = ['Swapnali Kurhade (SK)', kurhade.cohortLabel, 'Room 603', `${kurhade.subjectCode} · ${kurhade.cohortLabel} · Swapnali Kurhade (SK)`];
    for (const name of names) {
      expect(within(first).getByText(name)).toBeInTheDocument();
    }
    expect(within(first).queryByText('fac-swapnali-kurhade')).not.toBeInTheDocument();
    // D51: pin.0 is pinned_occupancy[0], named by display.json pins[0]
    expect(within(panel).getByTestId('constraint-pins-pin.0')).toHaveTextContent('Fixed item: TE lunch, Mon T4');
    expect(within(panel).getByTestId('relaxation-action')).toHaveTextContent('checked: with this change a timetable exists (12 ms)');
    expect(within(panel).getByTestId('relaxation-applies-to')).toHaveTextContent('Swapnali Kurhade (SK); Tuesday T0');
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
    const pin = displayText(display.pins[1].unique_label!);
    expect(screen.getByTestId('constraint-pins-pin.1')).toHaveTextContent(`Fixed item: ${pin}`);
    expect(screen.getByTestId('relaxation-applies-to')).toHaveTextContent(`SE-Comp A; fixed item ${pin}; Monday T5`);
  });
});

describe('The current edge list (S14j: GET /instances/{id}/edge-list/current)', () => {
  it('drives the drop pre-check: a drop onto an accepted absence is refused in words, nothing is posted', async () => {
    // a clean move on the committed edge list ...
    await openReal();
    const { s, day, period } = pickMove(true);
    cleanup();
    vi.unstubAllGlobals();
    // ... with the teacher's absence at the target accepted
    const absence = { kind: 'faculty_unavailable', faculty_id: s.facultyId, slots: [{ day, period }] };
    const backend = await openReal('coordinator', (b) => {
      b.current = withChanges([absence]);
    });
    drop(s.sessionId, day, period);
    expect(await screen.findByTestId('rejection-reason')).toHaveTextContent(
      `Clashes for ${s.subjectCode} (${s.cohortLabel}) at ${DAY_NAMES[day]} T${period}:`
    );
    expect(screen.getAllByTestId('rejection-clash').map((li) => li.textContent)).toEqual([
      `${facultyText(labelsFor(display), s.facultyId)} is unavailable then.`,
    ]);
    expect(backend.posted).toEqual([]);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/instances/${REAL_INSTANCE}/edge-list/current`, expect.anything());
  });

  it('drives the grid: an accepted room closure, past display.json pins, is labelled as such', async () => {
    const closure = { kind: 'room_unavailable', room_id: 'room-603', slots: [{ day: 0, period: 1 }] };
    await openReal('administrator', (b) => {
      b.current = withChanges([closure]);
    });
    expect(display.pins.length).toBe(edgeList.pinned_occupancy.length);
    const label = 'Room made unavailable by an accepted change';
    const closed = (await screen.findAllByTestId('pinned-block')).filter((el) => el.textContent?.includes(label));
    expect(closed).toHaveLength(1);
    expect(closed[0]).toHaveTextContent('Room 603');
  });

  it('static mode stays as it is: the bundled committed edge list, no request, no repair', async () => {
    const fetchMock = vi.fn(async () => json({ detail: 'Not Found' }, 404));
    vi.stubGlobal('fetch', fetchMock);
    render(<App client={new MockChronosApiClient()} />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('period-clock-0');
    expect(screen.getAllByTestId('pinned-block').some((el) => el.textContent?.includes('accepted change'))).toBe(false);
    expect(screen.queryByTestId('repair-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('accepted-changes')).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
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
      ? ['Select teacher', teacher]
      : role === 'student'
        ? ['Select class', 'coh-se-a']
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
      b.current = withChanges(accepted.map((a) => a.change));
    });
    const panel = await screen.findByTestId('accepted-changes');
    const row = (id: string) => within(panel).getByTestId(`accepted-change-${id}`);
    await waitFor(() => expect(row('rep-7')).toHaveTextContent('Swapnali Kurhade (SK) unavailable: Tuesday T6–T7'));
    expect(row('rep-7')).toHaveTextContent('coord-1');
    expect(row('rep-7')).toHaveTextContent('admin-1');
    expect(row('rep-7')).toHaveTextContent(formatTimestamp('2026-10-22T09:30:00Z'));
    expect(row('rep-8')).toHaveTextContent('Room 603 unavailable: Monday T1');
    expect(row('rep-8')).toHaveTextContent('not recorded');
    expect(row('rep-9')).toHaveTextContent('CE207 · SE-Comp A: taught by Prasenjit Bhavathankar (PBB)');

    // D52: the current edge list has the accepted substitute teaching the session
    showLecture('administrator');
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Prasenjit Bhavathankar (PBB)')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog')).getByText('Close'));

    fireEvent.click(within(panel).getByTestId('clear-changes'));
    expect(within(panel).getByTestId('confirm-clear')).toHaveTextContent('Remove all 3 accepted changes?');
    fireEvent.click(within(panel).getByText('Cancel'));
    expect(within(panel).queryByTestId('confirm-clear')).not.toBeInTheDocument();
    expect(backend.cleared).toBe(0);

    fireEvent.click(within(panel).getByTestId('clear-changes'));
    expect(within(panel).getByTestId('confirm-clear')).toHaveTextContent('The timetable in use may change');
    fireEvent.click(within(panel).getByTestId('confirm-clear-button'));
    expect(await within(panel).findByTestId('no-accepted-changes')).toBeInTheDocument();
    expect(backend.cleared).toBe(1);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/instances/${REAL_INSTANCE}/changes`, expect.objectContaining({ method: 'DELETE' }));
    // the current edge list is read again, without the substitution
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === `/api/instances/${REAL_INSTANCE}/edge-list/current`)).toHaveLength(2)
    );
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Anant Nimkar (AVN)')).toBeInTheDocument();
  });

  it('after Clear, reads the official solution, the current edge list and the changes again (D56)', async () => {
    const backend = await openReal('administrator', (b) => {
      b.changes = accepted;
      b.current = withChanges(accepted.map((a) => a.change));
    });
    await screen.findByTestId('accepted-change-rep-7');
    // clearing makes another timetable official: here one with a session moved
    const { s, day, period } = pickMove(true);
    backend.officialAfterClear = {
      ...solution,
      assignment: solution.assignment.map((a) => (a.session_id === s.sessionId ? { ...a, day, period } : a)),
    };
    const calls = (path: string) =>
      vi.mocked(fetch).mock.calls.filter(([url, init]) => url === `/api/instances/${REAL_INSTANCE}/${path}` && !init?.method).length;
    const before = { solution: calls('solution'), current: calls('edge-list/current'), changes: calls('changes') };

    fireEvent.click(screen.getByTestId('clear-changes'));
    fireEvent.click(screen.getByTestId('confirm-clear-button'));
    await waitFor(() =>
      expect(within(screen.getByTestId(`grid-cell-${day}-${period}`)).getByTestId(`session-cell-${s.sessionId}`)).toBeInTheDocument()
    );
    expect(calls('solution')).toBe(before.solution + 1);
    expect(calls('edge-list/current')).toBe(before.current + 1);
    expect(calls('changes')).toBe(before.changes + 1);
    expect(screen.getByTestId('no-accepted-changes')).toBeInTheDocument();
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
    expect(within(panel).getByTestId('substitute-score-fac-nataasha-raul')).toHaveTextContent('score −2.0');
    expect(within(panel).getByTestId('left-out-fac-sudhir-dhage')).toHaveTextContent(
      `Sudhir Dhage (SND): teaches ${sessionWithoutTeacher('obs-t6-r4-c4-l1', edgeList, labelsFor(display))} then`
    );
    expect(within(panel).getByTestId('left-out-fac-sudhir-dhage').textContent!.match(/Sudhir Dhage/g)).toHaveLength(1);

    // nobody moves: the result is the official placement with the new teacher, in the job's edge list
    backend.job = repairJob({ status: 'solved', change: substitution, solution: { ...solution, displaced: [] } });
    backend.jobEdgeList = withChanges([substitution]);
    fireEvent.click(within(panel).getByTestId(`substitute-${BHAVATHANKAR}`));
    await screen.findByTestId('repair-proposal');
    expect(backend.posted).toEqual([{ change: substitution }]);
    expect(screen.queryByTestId('substitute-panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('repair-change-text')).toHaveTextContent('Change: CE207 · SE-Comp A: taught by Prasenjit Bhavathankar (PBB)');
    await waitFor(() => expect(screen.getByTestId(`session-cell-${LECTURE}`).closest('[data-flagged]')).toBeInTheDocument());
    // the proposal is shown on GET /jobs/{id}/edge-list; the current edge list still has Anant Nimkar
    expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/jobs/rep-1/edge-list', expect.anything());
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Prasenjit Bhavathankar (PBB)')).toBeInTheDocument();
    fireEvent.click(within(screen.getByRole('dialog')).getByText('Close'));

    backend.changes = [{ job_id: 'rep-1', change: substitution, requested_by: 'test-coordinator', accepted_by: 'test-coordinator', accepted_at: '2026-10-21T12:00:00Z' }];
    backend.current = withChanges([substitution]);
    backend.jobEdgeList = null;
    fireEvent.click(screen.getByTestId('accept-repair'));
    await waitFor(() => expect(status()).toHaveTextContent('Accepted: the repaired timetable is now the official one.'));
    // the accepted list and the current edge list are read again: the grid keeps the substitute once the proposal is gone
    expect(await screen.findByTestId('accepted-change-rep-1')).toHaveTextContent('taught by Prasenjit Bhavathankar (PBB)');
    await waitFor(() =>
      expect(vi.mocked(fetch).mock.calls.filter(([url]) => url === `/api/instances/${REAL_INSTANCE}/edge-list/current`)).toHaveLength(2)
    );
    openSession(LECTURE);
    expect(within(screen.getByRole('dialog')).getByText('Prasenjit Bhavathankar (PBB)')).toBeInTheDocument();
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
    const picker = screen.getByLabelText('Select teacher');
    expect(picker).toBeDisabled();
    expect(picker).toHaveValue('fac-swapnali-kurhade');
    expect(screen.getByLabelText('Select timetable')).toHaveValue(REAL_INSTANCE);
  });

  it('a linked student login is locked to that cohort', async () => {
    await logInWith('student', { faculty_id: null, cohort_id: 'coh-se-a' });
    await screen.findByTestId('period-clock-0');
    const picker = screen.getByLabelText('Select class');
    expect(picker).toBeDisabled();
    expect(picker).toHaveValue('coh-se-a');
  });

  it('without a link the picker stays free, on the real timetable', async () => {
    await logInWith('faculty', { faculty_id: null, cohort_id: null });
    expect(screen.getByLabelText('Select teacher')).toBeEnabled();
    expect(screen.getByLabelText('Select timetable')).toHaveValue(REAL_INSTANCE);
  });
});

describe('A queued repair and the audit log (S14o)', () => {
  const solveJob = (status: string) => ({ id: 'solve-1', instance_id: REAL_INSTANCE, kind: 'solve', time_limit_s: 300, status });
  const markKurhadeUnavailable = () => {
    const panel = screen.getByTestId('repair-panel');
    fireEvent.change(within(panel).getByLabelText('Unavailable teacher'), { target: { value: 'fac-swapnali-kurhade' } });
    fireEvent.click(within(panel).getByLabelText('Tuesday T6'));
    fireEvent.click(screen.getByTestId('mark-unavailable-button'));
  };
  const solveStatus = () => screen.getByTestId('solve-status');

  it('a repair queued while this instance’s solve runs waits for it; once the solve ends it is only queued', async () => {
    const backend = await openReal('administrator');
    backend.jobs['solve-1'] = solveJob('running');
    clickGenerate();
    await waitFor(() => expect(solveStatus()).toHaveAttribute('data-status', 'running'));

    markKurhadeUnavailable();
    await waitFor(() =>
      expect(status()).toHaveTextContent('Waiting: the timetable being generated must finish first.')
    );
    expect(status()).toHaveAttribute('data-status', 'queued');

    backend.jobs['solve-1'] = solveJob('timeout');
    await waitFor(() => expect(solveStatus()).toHaveAttribute('data-status', 'timeout'), { timeout: 3000 });
    await waitFor(() => expect(status()).toHaveTextContent('Waiting its turn on the server.'));
  });

  it('a solve started after the repair is not what the repair waits for', async () => {
    const backend = await openReal('administrator');
    markKurhadeUnavailable();
    await waitFor(() => expect(status()).toHaveTextContent('Waiting its turn on the server.'));
    backend.jobs['solve-1'] = solveJob('running');
    clickGenerate();
    await waitFor(() => expect(solveStatus()).toHaveAttribute('data-status', 'running'));
    expect(status()).toHaveTextContent('Waiting its turn on the server.');
  });

  it('the audit log shows new rows after a solve, a repair, its end, an accept and a clear, at the same "Show entries"', async () => {
    const backend = await openReal('administrator');
    const log = await screen.findByTestId('audit-log');
    const rows = () => within(log).queryAllByTestId('audit-row').map((r) => r.textContent ?? '');
    await waitFor(() => expect(within(log).queryByRole('alert')).not.toBeInTheDocument());
    expect(rows()).toEqual([]);

    // a solve: its row appears when it is queued, and shows its final status once it ends
    backend.jobs['solve-1'] = solveJob('timeout');
    clickGenerate();
    await waitFor(() => expect(solveStatus()).toHaveAttribute('data-status', 'timeout'));
    await waitFor(() => expect(rows()).toEqual([expect.stringContaining('"status":"timeout"')]));
    expect(rows()[0]).toContain('solve');

    // a repair: queued, then solved
    const { s, day, period } = pickMove(true);
    const other = sessions.find((o) => theory(o) && o.sessionId !== s.sessionId)!;
    drop(s.sessionId, day, period);
    await waitFor(() => expect(rows()).toHaveLength(2));
    expect(rows()[0]).toContain('"status":"queued"');
    backend.job = repairJob({ status: 'solved', change: moveChange(s, day, period), solution: repaired(s.sessionId, day, period, other.sessionId) });
    await screen.findByTestId('repair-proposal', {}, { timeout: 3000 });
    await waitFor(() => expect(rows()[0]).toContain('"status":"solved"'));

    // an accept, then a clear of the accepted changes
    backend.changes = [{ job_id: 'rep-1', change: moveChange(s, day, period), requested_by: 'test-administrator', accepted_by: 'test-administrator', accepted_at: '2026-10-28T10:01:00Z' }];
    fireEvent.click(await screen.findByTestId('accept-repair'));
    await waitFor(() => expect(rows().map((r) => r.includes('accept'))).toEqual([true, false, false]));
    const panel = screen.getByTestId('accepted-changes');
    fireEvent.click(await within(panel).findByTestId('clear-changes'));
    fireEvent.click(within(panel).getByTestId('confirm-clear-button'));
    await waitFor(() => expect(rows()).toHaveLength(4));
    expect(rows()[0]).toContain('clear_changes');

    // never by changing "Show entries": every read asked for the default 100
    const reads = vi.mocked(fetch).mock.calls.map(([url]) => String(url)).filter((u) => u.startsWith('/api/audit'));
    expect(new Set(reads)).toEqual(new Set(['/api/audit?limit=100']));
    expect(within(log).getByLabelText('Audit entries to show')).toHaveValue('100');
  });
});
