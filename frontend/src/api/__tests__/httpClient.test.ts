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
      { id: 'example', label: 'Example instance', solvable: false },
      { id: 'd6_grid', label: 'D6 grid example (no solution)', solvable: false },
      { id: REAL_INSTANCE, label: 'EVEN 2025-26 SE+TE (real)', solvable: true },
      { id: PRINTED_INSTANCE, label: 'EVEN 2025-26 printed (real)', solvable: false },
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
    expect((error as ApiError).message).toBe('GET /instances: 401 missing, invalid or expired token');
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
});
