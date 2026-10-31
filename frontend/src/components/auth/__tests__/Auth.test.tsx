import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '@/App';
import {
  HttpChronosApiClient,
  MockChronosApiClient,
  REAL_INSTANCE,
  getAuthState,
  roleFromToken,
  setSession,
} from '@/api/chronosApi';

// The real instance's files, as the backend serves them
let real: Record<string, unknown>;
beforeAll(async () => {
  const files = new MockChronosApiClient();
  const edgeList = await files.getEdgeList(REAL_INSTANCE);
  real = {
    'edge-list': edgeList,
    // no accepted changes: the current edge list is the committed one
    'edge-list/current': edgeList,
    display: await files.getDisplay(REAL_INSTANCE),
    anomalies: await files.getAnomalies(REAL_INSTANCE),
    solution: await files.getInstanceSolution(REAL_INSTANCE),
  };
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

/** An unsigned token with these claims: the UI only reads them. */
const tokenWith = (claims: Record<string, unknown>) =>
  `h.${btoa(JSON.stringify(claims)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_')}.sig`;

const AUDIT = [
  { id: 3, actor: 'admin', action: 'solve', timestamp: '2026-10-21T10:02:00Z', detail: { instance_id: REAL_INSTANCE } },
  { id: 2, actor: 'admin', action: 'login', timestamp: '2026-10-21T10:01:00Z', detail: { ok: true } },
  { id: 1, actor: 'coord', action: 'login', timestamp: '2026-10-21T10:00:00Z', detail: null },
];

/** The S13 backend: accounts by password, the real instance, one solve job, the audit log. */
function mockBackend(login: (body: { username: string; password: string }) => Response) {
  const state = { job: { id: 'job-1', instance_id: REAL_INSTANCE, time_limit_s: 300, status: 'queued' } as Record<string, unknown>, refuseAll: false };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/auth/login') return login(JSON.parse(init?.body as string));
    if (state.refuseAll) return json({ detail: 'missing, invalid or expired token' }, 401);
    if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
    if (url === `/api/instances/${REAL_INSTANCE}/solve`) return json({ job_id: 'job-1', status: 'queued' }, 202);
    if (url === '/api/jobs/job-1') return json(state.job);
    if (url.startsWith('/api/audit?limit=')) return json(AUDIT.slice(0, Number(url.split('=')[1])));
    const file = url.match(new RegExp(`^/api/instances/${REAL_INSTANCE}/(.+)$`))?.[1];
    return file && file in real ? json(real[file]) : json({ detail: 'Not Found' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { state, fetchMock };
}

const accounts = ({ username, password }: { username: string; password: string }) =>
  password === 'right'
    ? json({ access_token: tokenWith({ sub: username, role: username }), token_type: 'bearer', role: username })
    : json({ detail: 'incorrect username or password' }, 401);

const renderApp = () => render(<App client={new HttpChronosApiClient('/api')} />);

async function logIn(username: string, password = 'right') {
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: username } });
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } });
  fireEvent.click(screen.getByTestId('login-button'));
}

const urls = (fetchMock: ReturnType<typeof vi.fn>) => fetchMock.mock.calls.map(([url]) => url as string);

afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});

describe('Login (http mode)', () => {
  it('shows the login screen and nothing else until logged in', () => {
    const { fetchMock } = mockBackend(accounts);
    renderApp();
    expect(screen.getByTestId('login-screen')).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('logs in, keeps the token in memory and sessionStorage, and sends it', async () => {
    const { fetchMock } = mockBackend(accounts);
    renderApp();
    await logIn('coordinator');
    await screen.findByTestId('timetable-grid');
    expect(JSON.parse(fetchMock.mock.calls[0][1]?.body as string)).toEqual({ username: 'coordinator', password: 'right' });
    const { session } = getAuthState();
    expect(session).toMatchObject({ username: 'coordinator', role: 'coordinator' });
    expect(JSON.parse(sessionStorage.getItem('chronos.session')!)).toEqual(session);
    const auth = fetchMock.mock.calls.find(([url]) => url === '/api/instances')![1]?.headers;
    expect(new Headers(auth).get('Authorization')).toBe(`Bearer ${session!.token}`);
    expect(screen.getByTestId('signed-in-as')).toHaveTextContent('Signed in as coordinator (Timetable Coordinator)');
  });

  it('refuses a bad password and stays on the login screen', async () => {
    mockBackend(accounts);
    renderApp();
    await logIn('coordinator', 'wrong');
    expect(await screen.findByTestId('login-error')).toHaveTextContent('Incorrect username or password.');
    expect(screen.getByTestId('login-screen')).toBeInTheDocument();
    expect(getAuthState().session).toBeNull();
  });

  it('logs out: back to the login screen, the token cleared', async () => {
    mockBackend(accounts);
    renderApp();
    await logIn('student');
    fireEvent.click(await screen.findByTestId('logout-button'));
    expect(screen.getByTestId('login-screen')).toBeInTheDocument();
    expect(screen.queryByTestId('session-expired')).not.toBeInTheDocument();
    expect(getAuthState().session).toBeNull();
    expect(sessionStorage.getItem('chronos.session')).toBeNull();
  });

  it('any 401 returns to the login screen with "Session expired"', async () => {
    const { state } = mockBackend(accounts);
    renderApp();
    await logIn('administrator');
    await screen.findByTestId('timetable-grid');
    state.refuseAll = true;
    // the real instance is already open: the next request is the audit log's at another limit
    fireEvent.change(screen.getByLabelText('Audit entries to show'), { target: { value: '25' } });
    expect(await screen.findByTestId('session-expired')).toHaveTextContent('Session expired, please log in again');
    expect(sessionStorage.getItem('chronos.session')).toBeNull();
  });

  it('takes the role from the token when the response has none (display only)', async () => {
    mockBackend(({ username }) => json({ access_token: tokenWith({ sub: username, role: 'faculty' }), token_type: 'bearer' }));
    renderApp();
    await logIn('someone');
    await screen.findByTestId('timetable-grid');
    expect(getAuthState().session?.role).toBe('faculty');
    expect(screen.getByTestId('session-role')).toHaveTextContent('Faculty Member');
    expect(roleFromToken('not-a-token')).toBeNull();
    expect(roleFromToken(tokenWith({ role: 'root' }))).toBeNull();
  });

  it('shows the logged-in role without the role switcher; the persona pickers stay', async () => {
    mockBackend(accounts);
    renderApp();
    await logIn('faculty');
    await screen.findByTestId('timetable-grid');
    expect(screen.queryByTestId('role-button-administrator')).not.toBeInTheDocument();
    expect(screen.getByTestId('faculty-persona-selector')).toBeInTheDocument();
  });
});

describe('Solve job across instance switches', () => {
  it('keeps tracking the job after switching instance and back, with its phase', async () => {
    const { state, fetchMock } = mockBackend(accounts);
    renderApp();
    await logIn('administrator');
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });
    fireEvent.click(await screen.findByTestId('solve-button'));
    state.job = { ...state.job, status: 'running', phase: 'search' };
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-phase', 'search'));
    expect(screen.getByTestId('solve-status')).toHaveTextContent('Searching for a timetable.');

    fireEvent.change(screen.getByLabelText('Select timetable'), { target: { value: 'example' } });
    await waitFor(() => expect(screen.queryByTestId('solve-panel')).not.toBeInTheDocument());
    state.job = { ...state.job, phase: 'improve' };
    fireEvent.change(await screen.findByLabelText('Select timetable'), { target: { value: REAL_INSTANCE } });

    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-phase', 'improve'));
    expect(screen.getByTestId('solve-button')).toBeDisabled();
    state.job = { ...state.job, status: 'solved', phase: undefined, solution: real.solution };
    await waitFor(() => expect(screen.getByTestId('solve-status')).toHaveAttribute('data-status', 'solved'), { timeout: 3000 });
    // one POST: coming back resumed the job rather than starting another
    expect(urls(fetchMock).filter((u) => u.endsWith('/solve'))).toHaveLength(1);
  });
});

describe('Audit log', () => {
  it('administrator: newest first, with a limit selector', async () => {
    const { fetchMock } = mockBackend(accounts);
    renderApp();
    await logIn('administrator');
    const log = await screen.findByTestId('audit-log');
    await waitFor(() => expect(within(log).getAllByTestId('audit-row')).toHaveLength(3));
    expect(within(log).getAllByTestId('audit-row').map((r) => r.textContent)).toEqual([
      expect.stringContaining('solve'),
      expect.stringContaining('{"ok":true}'),
      expect.stringContaining('coord'),
    ]);
    expect(urls(fetchMock)).toContain('/api/audit?limit=100');
    fireEvent.change(within(log).getByLabelText('Audit entries to show'), { target: { value: '25' } });
    await waitFor(() => expect(urls(fetchMock)).toContain('/api/audit?limit=25'));
  });

  it.each(['coordinator', 'faculty', 'student'])('%s: no audit log, and no request for it', async (role) => {
    const { fetchMock } = mockBackend(accounts);
    renderApp();
    await logIn(role);
    await screen.findByTestId('timetable-grid');
    expect(screen.queryByTestId('audit-log')).not.toBeInTheDocument();
    expect(urls(fetchMock).some((u) => u.startsWith('/api/audit'))).toBe(false);
  });
});
