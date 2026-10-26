import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { HttpChronosApiClient, MockChronosApiClient, REAL_INSTANCE, setSession } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';
import { SolvedSolution, isSolvedSolution } from '@/adapters/solution';
import { Display, EdgeList, buildEnrichedSessions, facultyAtSlot, labelsFor } from '@/adapters/timetable';

// The real instance's files, as the backend serves them
let real: Record<string, unknown>;
let edgeList: EdgeList;
let display: Display;
let solution: SolvedSolution;
beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  display = (await files.getDisplay(REAL_INSTANCE))!;
  const published = await files.getInstanceSolution(REAL_INSTANCE);
  if (!published || !isSolvedSolution(published)) throw new Error('Expected a solved solution.json');
  solution = published;
  real = { 'edge-list': edgeList, display, anomalies: await files.getAnomalies(REAL_INSTANCE), solution };
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const LECTURE = 'obs-t0-r1-c3-l0'; // CE207 lecture of SE-Comp A, Anant Nimkar, Thursday P4 in 605
const NIMKAR = 'fac-anant-nimkar';
const BHAVATHANKAR = 'fac-prasenjit-bhavathankar';
const KURHADE = 'fac-swapnali-kurhade';
const KURHADE_LECTURE = 'obs-t6-r1-c2-l0'; // CE206 lecture of SE-Comp D, Swapnali Kurhade, Tuesday P9 in 609
const substitution = { kind: 'substitute_faculty', session_id: LECTURE, faculty_id: BHAVATHANKAR };
const absence = { kind: 'faculty_unavailable', faculty_id: KURHADE, slots: [{ day: 1, period: 9 }] };

/** The committed edge list with the changes applied, as solver.repair.apply_change builds it. */
function withChanges(changes: Array<typeof substitution | typeof absence>): EdgeList {
  const changed: EdgeList = JSON.parse(JSON.stringify(edgeList));
  for (const c of changes) {
    if ('slots' in c) {
      changed.faculty_availability.find((f) => f.faculty_id === c.faculty_id)!.unavailable_slots.push(...c.slots);
    } else {
      changed.sessions.find((s) => s.id === c.session_id)!.faculty_id = c.faculty_id;
    }
  }
  return changed;
}

/** The official solution after the absence was accepted: Kurhade's Tuesday P9 lecture moved to Thursday P8. */
const repairedForAbsence = () => ({
  ...solution,
  assignment: solution.assignment.map((a) => (a.session_id === KURHADE_LECTURE ? { ...a, day: 3, period: 8 } : a)),
  displaced: [KURHADE_LECTURE],
});

/** The S14c-S14i backend with one repair job, whose answers the test sets. */
function mockBackend() {
  const state = {
    job: null as Record<string, unknown> | null,
    posted: [] as unknown[],
    changes: [] as unknown[],
    substitutes: null as unknown,
    /** GET .../edge-list/current; the committed edge list when unset */
    current: null as EdgeList | null,
    /** GET /jobs/rep-1/edge-list; the current edge list when unset */
    jobEdgeList: null as EdgeList | null,
    /** GET .../solution; the committed solution when unset */
    official: null as unknown,
  };
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
      if (url === `/api/instances/${REAL_INSTANCE}/repair`) {
        state.posted.push(JSON.parse(init?.body as string));
        return json({ job_id: 'rep-1', status: 'queued' }, 202);
      }
      if (url === `/api/instances/${REAL_INSTANCE}/changes`) return json(state.changes);
      if (url === `/api/instances/${REAL_INSTANCE}/edge-list/current`) return json(state.current ?? edgeList);
      if (url === `/api/instances/${REAL_INSTANCE}/solution`) return json(state.official ?? solution);
      if (url.startsWith(`/api/instances/${REAL_INSTANCE}/sessions/`)) return json(state.substitutes);
      if (url === '/api/jobs/rep-1/accept') return json({ ...state.job, accepted_at: '2026-10-27T10:00:00Z' });
      if (url === '/api/jobs/rep-1/base-solution') return json(solution);
      if (url === '/api/jobs/rep-1/edge-list') return json(state.jobEdgeList ?? state.current ?? edgeList);
      if (url === '/api/jobs/rep-1') return json(state.job);
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

const openReal = async (role: UserRole, setUp?: (backend: ReturnType<typeof mockBackend>) => void) => {
  const backend = mockBackend();
  setUp?.(backend);
  setSession({ username: `test-${role}`, token: `token-${role}`, role });
  render(<App client={new HttpChronosApiClient('/api')} />);
  await screen.findByTestId('timetable-grid');
  fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
  await screen.findByTestId('period-clock-0');
  return backend;
};

const pickFaculty = (id: string) => fireEvent.change(screen.getByLabelText('Select faculty persona'), { target: { value: id } });
const load = () => screen.getByTestId('workload-formula-badge');
const atSlot = (day: number, period: number) => {
  const panel = screen.getByTestId('faculty-at-slot');
  fireEvent.change(within(panel).getByLabelText('Faculty at slot day'), { target: { value: String(day) } });
  fireEvent.change(within(panel).getByLabelText('Faculty at slot period'), { target: { value: String(period) } });
  return panel;
};
const engaged = (id: string) => screen.queryByTestId(`engaged-${id}`);

describe('Faculty workload on the current edge list and the official solution (S14m)', () => {
  it('after an accepted substitution, both teachers’ loads are recalculated', async () => {
    await openReal('faculty', (b) => {
      b.current = withChanges([substitution]);
    });
    // committed: both teach 6T + 8P = 14; the CE207 lecture (1 theory hour) moved from Nimkar to Bhavathankar
    pickFaculty(NIMKAR);
    await waitFor(() => expect(load()).toHaveTextContent('5T + 8P = 13 hrs/wk'));
    pickFaculty(BHAVATHANKAR);
    expect(load()).toHaveTextContent('7T + 8P = 15 hrs/wk');
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(`/api/instances/${REAL_INSTANCE}/edge-list/current`, expect.anything());
  });

  it('after an accepted absence, the load is counted on the repaired official timetable', async () => {
    await openReal('faculty', (b) => {
      b.current = withChanges([absence]);
      b.official = repairedForAbsence();
    });
    pickFaculty(KURHADE);
    await waitFor(() => expect(load()).toHaveTextContent('6T + 10P = 16 hrs/wk'));
    // the lecture is where the official timetable now has it
    expect(within(screen.getByTestId('grid-cell-3-8')).getByTestId(`session-cell-${KURHADE_LECTURE}`)).toBeInTheDocument();
    expect(within(screen.getByTestId('grid-cell-1-9')).queryByTestId(`session-cell-${KURHADE_LECTURE}`)).not.toBeInTheDocument();
  });

  it('a substitution proposal shows both teachers’ weekly load before → after; Accept makes the substitute engaged', async () => {
    const backend = await openReal('coordinator', (b) => {
      b.substitutes = { session_id: LECTURE, faculty_id: NIMKAR, candidates: [{ faculty_id: BHAVATHANKAR, score_change: 0 }], left_out: [] };
    });
    fireEvent.change(screen.getByLabelText('Filter timetable by division'), { target: { value: 'coh-se-a' } });
    fireEvent.click(screen.getByTestId(`session-cell-${LECTURE}`));
    fireEvent.click(screen.getByTestId('find-substitute'));
    backend.job = { id: 'rep-1', instance_id: REAL_INSTANCE, kind: 'repair', time_limit_s: 300, base: 'committed', status: 'solved', change: substitution, solution: { ...solution, displaced: [] } };
    backend.jobEdgeList = withChanges([substitution]);
    fireEvent.click(await screen.findByTestId(`substitute-${BHAVATHANKAR}`));

    const loads = await screen.findByTestId('substitution-loads');
    expect(within(loads).getByTestId(`substitution-load-${NIMKAR}`)).toHaveTextContent('Anant Nimkar (AVN): 6T + 8P = 14 → 5T + 8P = 13 hrs/wk');
    expect(within(loads).getByTestId(`substitution-load-${BHAVATHANKAR}`)).toHaveTextContent(
      'Prasenjit Bhavathankar (PBB): 6T + 8P = 14 → 7T + 8P = 15 hrs/wk'
    );
    expect(vi.mocked(fetch)).toHaveBeenCalledWith('/api/jobs/rep-1/edge-list', expect.anything());

    // the free/engaged view reads the official timetable only, never the proposal
    atSlot(3, 4);
    const lecture = `CE207 · SE-Comp A · ${display.rooms['room-605']}`;
    expect(engaged(NIMKAR)).toHaveTextContent(lecture);
    expect(engaged(BHAVATHANKAR)?.textContent ?? '').not.toContain(lecture);

    backend.current = withChanges([substitution]);
    fireEvent.click(screen.getByTestId('accept-repair'));
    await waitFor(() => expect(engaged(BHAVATHANKAR)).toHaveTextContent(lecture));
    expect(engaged(NIMKAR)?.textContent ?? '').not.toContain(lecture);
    expect(screen.queryByTestId('substitution-loads')).not.toBeInTheDocument();
  });
});

describe('Free and engaged faculty at a slot (S14m)', () => {
  it('Monday P0 on the real instance: teaching, pinned, unavailable and free, as "Name (INITIALS)"', async () => {
    await openReal('coordinator');
    const panel = atSlot(0, 0);
    expect(engaged('fac-anand-godbole')).toHaveTextContent('Anand Godbole (AAG): CE306 · TE Comp - D · 701');
    expect(engaged('fac-rupali-sawant')).toHaveTextContent('Rupali Sawant (RS): MDM-I lab /A /603-7');
    expect(engaged(KURHADE)).toHaveTextContent('Swapnali Kurhade (SK): unavailable');
    expect(screen.getByTestId(`free-${BHAVATHANKAR}`)).toHaveTextContent('Prasenjit Bhavathankar (PBB)');
    expect(screen.queryByTestId(`free-${KURHADE}`)).not.toBeInTheDocument();
    // every one of the edge list's 37 faculty is in exactly one list
    const free = within(within(panel).getByTestId('free-faculty')).getAllByRole('listitem');
    const busy = within(within(panel).getByTestId('engaged-faculty')).getAllByRole('listitem');
    expect([free.length, busy.length]).toEqual([32, 5]);
    expect(edgeList.faculty_availability).toHaveLength(37);
  });

  it('an accepted absence makes the teacher unavailable there, and the moved session engages them where it went', async () => {
    await openReal('administrator', (b) => {
      b.current = withChanges([absence]);
      b.official = repairedForAbsence();
    });
    atSlot(1, 9);
    expect(engaged(KURHADE)).toHaveTextContent('Swapnali Kurhade (SK): unavailable');
    atSlot(3, 8);
    expect(engaged(KURHADE)).toHaveTextContent(`Swapnali Kurhade (SK): CE206 · ${display.cohorts['coh-se-d'].name} · 609`);
  });

  it.each([
    ['administrator', true],
    ['coordinator', true],
    ['faculty', false],
    ['student', false],
  ] as const)('is shown to the %s: %s; the workload card only to faculty', async (role, shown) => {
    await openReal(role);
    expect(!!screen.queryByTestId('faculty-at-slot')).toBe(shown);
    expect(!!screen.queryByTestId('faculty-workload-card')).toBe(role === 'faculty');
  });

  it('static mode: the bundled files, no request', async () => {
    const fetchMock = vi.fn(async () => json({ detail: 'Not Found' }, 404));
    vi.stubGlobal('fetch', fetchMock);
    render(<App client={new MockChronosApiClient()} />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('period-clock-0');
    atSlot(0, 0);
    expect(engaged('fac-anand-godbole')).toHaveTextContent('Anand Godbole (AAG): CE306 · TE Comp - D · 701');
    expect(engaged(KURHADE)).toHaveTextContent('unavailable');

    fireEvent.click(screen.getByTestId('role-button-faculty'));
    expect(screen.queryByTestId('faculty-at-slot')).not.toBeInTheDocument();
    pickFaculty(NIMKAR);
    expect(load()).toHaveTextContent('6T + 8P = 14 hrs/wk');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('facultyAtSlot puts nobody in both lists and needs no solution', () => {
    const labels = labelsFor(display);
    const sessions = buildEnrichedSessions(solution.assignment, edgeList, labels);
    for (const [day, period] of [[0, 0], [1, 3], [4, 9]]) {
      const { free, engaged: busy } = facultyAtSlot(edgeList, labels, sessions, day, period);
      const ids = [...free, ...busy].map((f) => f.facultyId);
      expect(new Set(ids).size).toBe(ids.length);
      expect(ids).toHaveLength(37);
    }
    // without a timetable only pins and unavailability engage anyone
    const unsolved = facultyAtSlot(edgeList, labels, [], 0, 0);
    expect(unsolved.engaged.map((f) => f.facultyId)).not.toContain('fac-anand-godbole');
    expect(unsolved.engaged.find((f) => f.facultyId === KURHADE)?.engagedWith).toEqual(['unavailable']);
  });
});
