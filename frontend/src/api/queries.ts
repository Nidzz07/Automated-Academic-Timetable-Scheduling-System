/**
 * TanStack Query hooks over the ChronosApiClient interface.
 * Components never call the client directly, so the mock and the real HTTP
 * client are interchangeable.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import {
  ChronosApiClient,
  EdgeListInstance,
  HttpChronosApiClient,
  MoveSessionRequest,
  chronosApiClient,
  isFinished,
  ApiError,
} from '@/api/chronosApi';
import { ContractValidationError } from '@/api/contractError';
import { SolvedSolution } from '@/adapters/solution';

// A payload that breaks the contract, or a request the backend refused (4xx), fails alike again
const retryable = (failures: number, error: Error) =>
  !(error instanceof ContractValidationError) && !(error instanceof ApiError && error.status < 500) && failures < 3;

export const timetableQueryKey = ['timetable'] as const;

export function useTimetableQuery(client: ChronosApiClient = chronosApiClient) {
  return useQuery({
    queryKey: timetableQueryKey,
    queryFn: () => client.getTimetable(),
    // The cache is the edited timetable (moves write into it); only refetch on request.
    staleTime: Infinity,
    retry: retryable,
  });
}

export function useEdgeListQuery(
  instance: EdgeListInstance = 'example',
  client: ChronosApiClient = chronosApiClient
) {
  return useQuery({
    queryKey: ['edge-list', instance],
    queryFn: () => client.getEdgeList(instance),
    staleTime: Infinity,
    retry: retryable,
  });
}

export function useDisplayQuery(
  instance: EdgeListInstance,
  client: ChronosApiClient = chronosApiClient
) {
  return useQuery({
    queryKey: ['display', instance],
    queryFn: () => client.getDisplay(instance),
    staleTime: Infinity,
    retry: retryable,
  });
}

export function useInstancesQuery(client: ChronosApiClient = chronosApiClient) {
  return useQuery({ queryKey: ['instances'], queryFn: () => client.listInstances(), staleTime: Infinity, retry: retryable });
}

/** A finished solve writes its solution here, so the grid and quality card show it. */
export const instanceSolutionQueryKey = (instance: EdgeListInstance) => ['instance-solution', instance] as const;

export function useInstanceSolutionQuery(
  instance: EdgeListInstance,
  client: ChronosApiClient = chronosApiClient
) {
  return useQuery({
    queryKey: instanceSolutionQueryKey(instance),
    queryFn: () => client.getInstanceSolution(instance),
    staleTime: Infinity,
    retry: retryable,
  });
}

export function useAnomaliesQuery(
  instance: EdgeListInstance,
  client: ChronosApiClient = chronosApiClient
) {
  return useQuery({
    queryKey: ['anomalies', instance],
    queryFn: () => client.getAnomalies(instance),
    staleTime: Infinity,
    retry: retryable,
  });
}

export function usePrintedBaselineQuery(
  instance: EdgeListInstance,
  client: ChronosApiClient = chronosApiClient
) {
  return useQuery({
    queryKey: ['printed-baseline', instance],
    queryFn: () => client.getPrintedBaseline(instance),
    staleTime: Infinity,
    retry: retryable,
  });
}

export function useSolveMutation(client: HttpChronosApiClient) {
  return useMutation({
    mutationFn: ({ instance, timeLimitS }: { instance: EdgeListInstance; timeLimitS: number }) =>
      client.startSolve(instance, timeLimitS),
  });
}

/** Polls GET /jobs/{id} every pollMs until the job ends or fails; stops when unmounted. */
export function useJobQuery(client: HttpChronosApiClient, jobId: string | null, pollMs: number) {
  return useQuery({
    queryKey: ['job', jobId],
    queryFn: () => client.getJob(jobId!),
    enabled: jobId !== null,
    retry: false,
    refetchInterval: (query) =>
      query.state.status === 'error' || isFinished(query.state.data?.status) ? false : pollMs,
  });
}

export function useMoveSessionMutation(client: ChronosApiClient = chronosApiClient) {
  return useMutation({
    mutationFn: ({ request, current }: { request: MoveSessionRequest; current: SolvedSolution }) =>
      client.moveSession(request, current),
  });
}
