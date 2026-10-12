import { describe, it, expect, vi, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from '@/App';
import { ChronosApiClient, chronosApiClient } from '../chronosApi';
import { ContractValidationError } from '../contractValidation';
import { useMoveSessionMutation, useTimetableQuery } from '../queries';
import { getSolvedSolutionFixture } from '@/adapters/timetable';
import { parseSolution } from '@/adapters/solution';

function makeWrapper() {
  const queryClient = new QueryClient();
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function stubClient(overrides: Partial<ChronosApiClient>): ChronosApiClient {
  return {
    getTimetable: vi.fn(),
    generateTimetable: vi.fn(),
    moveSession: vi.fn(),
    getSolvedSolution: vi.fn(),
    getInfeasibleSolution: vi.fn(),
    ...overrides,
  };
}

describe('useTimetableQuery', () => {
  it('starts pending, then exposes the solution', async () => {
    const solved = getSolvedSolutionFixture();
    const client = stubClient({ getTimetable: vi.fn().mockResolvedValue(solved) });
    const { result } = renderHook(() => useTimetableQuery(client), { wrapper: makeWrapper() });

    expect(result.current.isPending).toBe(true);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBe(solved);
  });

  it('surfaces a ContractValidationError without retrying', async () => {
    const getTimetable = vi.fn(async () => parseSolution({ status: 'solved' }));
    const { result } = renderHook(() => useTimetableQuery(stubClient({ getTimetable })), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(ContractValidationError);
    expect(getTimetable).toHaveBeenCalledTimes(1);
  });
});

describe('useMoveSessionMutation', () => {
  it('forwards the request and current solution to the client', async () => {
    const current = getSolvedSolutionFixture();
    const moveSession = vi.fn().mockResolvedValue({ success: false, rejectionReason: 'clash' });
    const { result } = renderHook(() => useMoveSessionMutation(stubClient({ moveSession })), {
      wrapper: makeWrapper(),
    });
    const request = { sessionId: 'sess-0006', targetDay: 0, targetTeachingPeriod: 4, targetWallClockPeriod: 6 };

    let outcome: unknown;
    await act(async () => {
      outcome = await result.current.mutateAsync({ request, current });
    });

    expect(moveSession).toHaveBeenCalledWith(request, current);
    expect(outcome).toEqual({ success: false, rejectionReason: 'clash' });
  });
});

describe('App query states', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows a loading state before the timetable arrives', async () => {
    render(<App />);
    expect(screen.getByTestId('timetable-loading')).toHaveTextContent(/Loading timetable/i);
    expect(await screen.findByTestId('timetable-grid')).toBeInTheDocument();
  });

  it('shows the contract issues when the payload is invalid', async () => {
    vi.spyOn(chronosApiClient, 'getTimetable').mockImplementation(async () =>
      parseSolution({ schema_version: 'solution.v1', status: 'solved', metadata: {} })
    );
    render(<App />);

    const error = await screen.findByTestId('timetable-error');
    expect(error).toHaveTextContent(/failed solution_v1 contract validation/i);
    expect(within(error).getByTestId('contract-issues')).toHaveTextContent(
      "must have required property 'assignment'"
    );
  });

  it('shows an empty state for a solved timetable with no sessions', async () => {
    vi.spyOn(chronosApiClient, 'getTimetable').mockResolvedValue({
      ...getSolvedSolutionFixture(),
      assignment: [],
    });
    render(<App />);

    expect(await screen.findByTestId('timetable-empty')).toHaveTextContent(/No sessions scheduled/i);
    expect(screen.queryByTestId('timetable-grid')).not.toBeInTheDocument();
  });
});
