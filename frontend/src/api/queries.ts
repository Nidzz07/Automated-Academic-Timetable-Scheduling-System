/**
 * TanStack Query hooks over the ChronosApiClient interface.
 * Components never call the client directly, so the mock and the real HTTP
 * client are interchangeable.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChronosApiClient,
  EdgeListInstance,
  HttpChronosApiClient,
  MoveSessionRequest,
  RepairChange,
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

/** onStarted is a hook-level callback, so it still fires when the panel unmounts mid-POST. */
export function useSolveMutation(
  client: HttpChronosApiClient,
  onStarted: (instance: EdgeListInstance, jobId: string) => void
) {
  return useMutation({
    mutationFn: ({ instance, timeLimitS }: { instance: EdgeListInstance; timeLimitS: number }) =>
      client.startSolve(instance, timeLimitS),
    onSuccess: ({ job_id }, { instance }) => onStarted(instance, job_id),
  });
}

export function useAuditQuery(client: HttpChronosApiClient, limit: number) {
  return useQuery({ queryKey: ['audit', limit], queryFn: () => client.getAudit(limit), retry: retryable });
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

/**
 * An instance's latest repair job (S14c): start one, poll it, read the solution it started
 * from (its base, D48) once solved, and accept it (D49). Null client: static mode, never used.
 */
export function useRepair(
  client: HttpChronosApiClient | null,
  instance: EdgeListInstance,
  jobId: string | null,
  onStarted: (instance: EdgeListInstance, jobId: string) => void,
  pollMs = 1000
) {
  const queryClient = useQueryClient();
  const start = useMutation({
    mutationFn: (change: RepairChange) => client!.startRepair(instance, change),
    onSuccess: ({ job_id }) => onStarted(instance, job_id),
  });
  const job = useJobQuery(client!, client ? jobId : null, pollMs);
  const solved = job.data?.status === 'solved' ? job.data : undefined;
  const base = useQuery({
    queryKey: ['repair-base', solved?.id],
    queryFn: () => client!.getBaseSolution(solved!.id),
    enabled: !!solved,
    staleTime: Infinity,
    retry: retryable,
  });
  const accept = useMutation({
    mutationFn: (id: string) => client!.acceptRepair(id),
    onSuccess: (accepted) => {
      queryClient.setQueryData(['job', accepted.id], accepted);
      if (accepted.solution) queryClient.setQueryData(instanceSolutionQueryKey(instance), accepted.solution);
      queryClient.invalidateQueries({ queryKey: changesQueryKey(instance) });
    },
  });
  return { start, job, base, accept };
}

export const changesQueryKey = (instance: EdgeListInstance) => ['changes', instance] as const;

/** The accepted changes (D52) of a backend instance; null client: static mode, never fetched. */
export function useChangesQuery(client: HttpChronosApiClient | null, instance: EdgeListInstance, enabled: boolean) {
  return useQuery({
    queryKey: changesQueryKey(instance),
    queryFn: () => client!.getChanges(instance),
    enabled: !!client && enabled,
    retry: retryable,
  });
}

export function useClearChangesMutation(client: HttpChronosApiClient, instance: EdgeListInstance) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => client.clearChanges(instance),
    onSuccess: () => queryClient.setQueryData(changesQueryKey(instance), []),
  });
}

/** Who may substitute for a session where it is now; refetched each time it is opened. */
export function useSubstitutesQuery(client: HttpChronosApiClient, instance: EdgeListInstance, sessionId: string) {
  return useQuery({
    queryKey: ['substitutes', instance, sessionId],
    queryFn: () => client.getSubstitutes(instance, sessionId),
    staleTime: 0,
    gcTime: 0,
    retry: retryable,
  });
}

export function useMoveSessionMutation(client: ChronosApiClient = chronosApiClient) {
  return useMutation({
    mutationFn: ({ request, current }: { request: MoveSessionRequest; current: SolvedSolution }) =>
      client.moveSession(request, current),
  });
}
