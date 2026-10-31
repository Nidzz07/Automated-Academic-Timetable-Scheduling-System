import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import {
  ApiError,
  HttpChronosApiClient,
  MockChronosApiClient,
  PRINTED_INSTANCE,
  REAL_INSTANCE,
  setSession,
} from '../chronosApi';
import { ContractValidationError } from '../contractError';
import type { SolutionContract } from '@/adapters/solution';
import type { Display, EdgeList } from '@/adapters/timetable';
import type { AnomalyReport } from '@/adapters/realInstance';

// The real instance's files, as the backend serves them (read through the static client)
let edgeList: EdgeList;
let display: Display;
let anomalies: AnomalyReport;
let solution: SolutionContract;
beforeAll(async () => {
  const files = new MockChronosApiClient();
  edgeList = await files.getEdgeList(REAL_INSTANCE);
  display = (await files.getDisplay(REAL_INSTANCE))!;
  anomalies = (await files.getAnomalies(REAL_INSTANCE))!;
  solution = (await files.getInstanceSolution(REAL_INSTANCE))!;
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** fetch answering from a path → response table; any other path is a 404. */
function mockFetch(routes: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (url: string, _init?: RequestInit) => (routes[url] ?? (() => json({ detail: 'Not Found' }, 404)))());
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const base = `/api/instances/${REAL_INSTANCE}`;

afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});

describe('HttpChronosApiClient (S13a endpoints)', () => {
  const client = new HttpChronosApiClient('/api');

  it('GET /instances: the backend ids, solvable, with the real instance’s printed view', async () => {
    mockFetch({ '/api/instances': () => json([{ id: REAL_INSTANCE }, { id: 'other' }]) });
    expect(await client.listInstances()).toEqual([
      { id: REAL_INSTANCE, label: 'Even semester 2025–26, SE and TE', solvable: true },
      { id: PRINTED_INSTANCE, label: 'Even semester 2025–26, as printed by SPIT', solvable: false },
      { id: 'other', label: 'other', solvable: true },
    ]);
  });

  it('GET edge-list, display, anomalies and solution of a backend instance', async () => {
    const fetchMock = mockFetch({
      [`${base}/edge-list`]: () => json(edgeList),
      [`${base}/display`]: () => json(display),
      [`${base}/anomalies`]: () => json(anomalies),
      [`${base}/solution`]: () => json(solution),
    });
    expect(await client.getEdgeList(REAL_INSTANCE)).toEqual(edgeList);
    expect(await client.getDisplay(REAL_INSTANCE)).toEqual(display);
    expect(await client.getAnomalies(REAL_INSTANCE)).toEqual(anomalies);
    expect(await client.getInstanceSolution(REAL_INSTANCE)).toEqual(solution);
    // the printed view reads the real instance's files and has no solution of its own
    expect(await client.getAnomalies(PRINTED_INSTANCE)).toEqual(anomalies);
    expect(await client.getInstanceSolution(PRINTED_INSTANCE)).toBeNull();
    expect(fetchMock.mock.calls.map(([url]) => url)).not.toContain(`/api/instances/${PRINTED_INSTANCE}/anomalies`);
  });

  it('serves the contract examples bundled, without a request', async () => {
    const fetchMock = mockFetch({});
    expect((await client.getEdgeList('example')).sessions.length).toBeGreaterThan(0);
    expect(await client.getDisplay('d6_grid')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('reads a 404 as absent for the solution and sidecars, and as an unknown instance for the edge list', async () => {
    mockFetch({});
    expect(await client.getInstanceSolution(REAL_INSTANCE)).toBeNull();
    expect(await client.getDisplay(REAL_INSTANCE)).toBeNull();
    expect(await client.getAnomalies(REAL_INSTANCE)).toBeNull();
    await expect(client.getEdgeList('nope')).rejects.toThrow("Unknown instance 'nope'");
  });

  it('throws ApiError with the backend’s detail on any other failure', async () => {
    mockFetch({ '/api/instances': () => json({ detail: 'missing, invalid or expired token' }, 401) });
    const error = await client.listInstances().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(401);
    expect((error as ApiError).message).toBe('missing, invalid or expired token');
    expect((error as ApiError).endpoint).toBe('GET /instances');
  });

  it('sends the session’s bearer token, and none without one', async () => {
    const fetchMock = mockFetch({ '/api/instances': () => json([]) });
    await client.listInstances();
    setSession({ username: 'u', token: 'tok', role: 'student' });
    await client.listInstances();
    const auth = fetchMock.mock.calls.map(([, init]) => new Headers(init?.headers).get('Authorization'));
    expect(auth).toEqual([null, 'Bearer tok']);
  });

  it('validates every payload against its contract', async () => {
    const broken = { ...edgeList, sessions: 'not a list' };
    mockFetch({
      [`${base}/edge-list`]: () => json(broken),
      [`${base}/solution`]: () => json({ ...solution, status: 'maybe' }),
      '/api/jobs/j1': () => json({ id: 'j1', instance_id: REAL_INSTANCE, time_limit_s: 5, status: 'solved', solution: { status: 'solved' } }),
    });
    await expect(client.getEdgeList(REAL_INSTANCE)).rejects.toBeInstanceOf(ContractValidationError);
    await expect(client.getInstanceSolution(REAL_INSTANCE)).rejects.toBeInstanceOf(ContractValidationError);
    await expect(client.getJob('j1')).rejects.toBeInstanceOf(ContractValidationError);
  });

  it('POST /instances/{id}/solve sends the time limit', async () => {
    const fetchMock = mockFetch({ [`${base}/solve`]: () => json({ job_id: 'j1', status: 'queued' }, 202) });
    expect(await client.startSolve(REAL_INSTANCE, 30)).toEqual({ job_id: 'j1', status: 'queued' });
    const [, init] = fetchMock.mock.calls[0];
    expect(init?.method).toBe('POST');
    expect(JSON.parse(init?.body as string)).toEqual({ time_limit_s: 30 });
  });

  it('GET /jobs/{id}: validates the solution, and refuses an unknown status', async () => {
    const job = { id: 'j1', instance_id: REAL_INSTANCE, time_limit_s: 300 };
    mockFetch({
      '/api/jobs/j1': () => json({ ...job, status: 'solved', solution }),
      '/api/jobs/j2': () => json({ ...job, id: 'j2', status: 'timeout' }),
      '/api/jobs/j3': () => json({ ...job, id: 'j3', status: 'paused' }),
    });
    expect(await client.getJob('j1')).toEqual({ ...job, status: 'solved', solution });
    expect(await client.getJob('j2')).toEqual({ ...job, id: 'j2', status: 'timeout' });
    await expect(client.getJob('j3')).rejects.toThrow("unknown status 'paused'");
  });

  it('GET /instances/{id}/edge-list/current and GET /jobs/{id}/edge-list are validated (S14i)', async () => {
    const changed = { ...edgeList, pinned_occupancy: [...edgeList.pinned_occupancy, { day: 0, period: 1, faculty_ids: [], room_ids: ['room-603'], cohort_ids: [] }] };
    const fetchMock = mockFetch({
      [`${base}/edge-list/current`]: () => json(changed),
      '/api/jobs/r1/edge-list': () => json(changed),
      '/api/jobs/r2/edge-list': () => json({ ...edgeList, sessions: 'not a list' }),
    });
    expect(await client.getCurrentEdgeList(REAL_INSTANCE)).toEqual(changed);
    expect(await client.getJobEdgeList('r1')).toEqual(changed);
    await expect(client.getJobEdgeList('r2')).rejects.toBeInstanceOf(ContractValidationError);
    await expect(client.getJobEdgeList('nope')).rejects.toBeInstanceOf(ApiError);
    expect(fetchMock.mock.calls.map(([url]) => url)).not.toContain(`${base}/edge-list`);
  });

  it('the contract examples and the printed view are not backend instances: their own edge list, never /current', async () => {
    const fetchMock = mockFetch({ [`${base}/edge-list`]: () => json(edgeList) });
    expect(await client.getCurrentEdgeList('example')).toEqual(await client.getEdgeList('example'));
    // the printed timetable is laid on the committed edge list
    expect(await client.getCurrentEdgeList(PRINTED_INSTANCE)).toEqual(edgeList);
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([`${base}/edge-list`]);
  });

  it('GET /jobs/{id}/base-solution is validated; DELETE /changes and the substitutes path (S14f, S14g)', async () => {
    const fetchMock = mockFetch({
      '/api/jobs/r1/base-solution': () => json(solution),
      '/api/jobs/r2/base-solution': () => json({ ...solution, status: 'maybe' }),
      [`${base}/changes`]: () => json([]),
      [`${base}/sessions/obs%2F1/substitutes`]: () => json({ session_id: 'obs/1', faculty_id: 'f', candidates: [], left_out: [] }),
    });
    expect(await client.getBaseSolution('r1')).toEqual(solution);
    await expect(client.getBaseSolution('r2')).rejects.toBeInstanceOf(ContractValidationError);
    expect(await client.clearChanges(REAL_INSTANCE)).toEqual([]);
    expect(fetchMock.mock.calls.at(-1)?.[1]?.method).toBe('DELETE');
    expect((await client.getSubstitutes(REAL_INSTANCE, 'obs/1')).session_id).toBe('obs/1');
  });
});

describe('Static mode keeps the committed edge list (S14j)', () => {
  it('getCurrentEdgeList is getEdgeList, read from the bundled files without a request', async () => {
    const fetchMock = mockFetch({});
    const files = new MockChronosApiClient();
    expect(await files.getCurrentEdgeList(REAL_INSTANCE)).toEqual(edgeList);
    expect(await files.getCurrentEdgeList('example')).toEqual(await files.getEdgeList('example'));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
