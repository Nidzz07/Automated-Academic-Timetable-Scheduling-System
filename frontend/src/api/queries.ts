/**
 * TanStack Query hooks over the ChronosApiClient interface.
 * Components never call the client directly, so the mock and the real HTTP
 * client are interchangeable.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import {
  ChronosApiClient,
  EdgeListInstance,
  MoveSessionRequest,
  chronosApiClient,
} from '@/api/chronosApi';
import { ContractValidationError } from '@/api/contractValidation';
import { SolvedSolution } from '@/adapters/solution';

export const timetableQueryKey = ['timetable'] as const;

export function useTimetableQuery(client: ChronosApiClient = chronosApiClient) {
  return useQuery({
    queryKey: timetableQueryKey,
    queryFn: () => client.getTimetable(),
    // The cache is the edited timetable (moves write into it); only refetch on request.
    staleTime: Infinity,
    // A payload that breaks the contract will break it again; don't retry it.
    retry: (failures, error) => !(error instanceof ContractValidationError) && failures < 3,
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
    retry: (failures, error) => !(error instanceof ContractValidationError) && failures < 3,
  });
}

export function useMoveSessionMutation(client: ChronosApiClient = chronosApiClient) {
  return useMutation({
    mutationFn: ({ request, current }: { request: MoveSessionRequest; current: SolvedSolution }) =>
      client.moveSession(request, current),
  });
}
