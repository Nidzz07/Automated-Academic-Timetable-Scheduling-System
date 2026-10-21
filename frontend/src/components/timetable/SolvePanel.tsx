import React, { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { HttpChronosApiClient, EdgeListInstance, JobStatus } from '@/api/chronosApi';
import { instanceSolutionQueryKey, useJobQuery, useSolveMutation } from '@/api/queries';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Play } from 'lucide-react';

// The backend's SolveRequest bounds (backend/app/service.py DEFAULT_TIME_LIMIT_S, MAX_TIME_LIMIT_S)
const DEFAULT_TIME_LIMIT_S = 300;
const MAX_TIME_LIMIT_S = 1800;

// The backend's optional phase of a running job (S13d)
const PHASE_MESSAGE = {
  search: 'Running (search): searching for a timetable.',
  improve: 'Running (improve): improving the timetable found.',
  repair: 'Running (repair): repairing the timetable.',
};

interface SolvePanelProps {
  client: HttpChronosApiClient;
  instance: EdgeListInstance;
  /** The instance's latest job; kept by the caller, so it survives switching instance and back */
  jobId: string | null;
  onJobStarted: (instance: EdgeListInstance, jobId: string) => void;
  /** How often to poll GET /jobs/{id} */
  pollMs?: number;
}

/**
 * Solve a backend instance: POST /instances/{id}/solve, then poll the job until it ends.
 * A solved or infeasible result replaces the instance's solution in the query cache, so the
 * grid, quality card and diagnosis panel show it. A timeout leaves it untouched (D33).
 */
export const SolvePanel: React.FC<SolvePanelProps> = ({ client, instance, jobId, onJobStarted, pollMs = 1000 }) => {
  const [timeLimit, setTimeLimit] = useState(DEFAULT_TIME_LIMIT_S);
  const solve = useSolveMutation(client, onJobStarted);
  const job = useJobQuery(client, jobId, pollMs);
  const queryClient = useQueryClient();

  const solution = job.data?.solution;
  useEffect(() => {
    if (solution) queryClient.setQueryData(instanceSolutionQueryKey(instance), solution);
  }, [solution, instance, queryClient]);

  const failure = solve.error ?? job.error;
  const status: JobStatus | null = failure ? 'error' : job.data?.status ?? solve.data?.status ?? null;
  // a job being re-read after coming back to the instance counts as busy until its status is known
  const busy = solve.isPending || (jobId !== null && job.isPending) || status === 'queued' || status === 'running';
  const validLimit = timeLimit > 0 && timeLimit <= MAX_TIME_LIMIT_S;
  const phase = status === 'running' ? job.data?.phase : undefined;

  const message: Record<JobStatus, string> = {
    queued: 'Queued: waiting for a solver worker.',
    running: phase ? PHASE_MESSAGE[phase] : 'Running: searching for a timetable.',
    solved: 'Solved: the grid and quality score show the new timetable.',
    infeasible: 'Infeasible: the diagnosis panel shows the conflicting constraints.',
    timeout: `No timetable found within ${job.data?.time_limit_s} s. This does not prove it is impossible.`,
    error: `Solve failed: ${failure?.message ?? job.data?.error ?? 'unknown error'}`,
  };

  return (
    <Card data-testid="solve-panel">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Generate a timetable</CardTitle>
        <CardDescription>Runs the solver on the backend for this instance.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3 pt-0 text-xs">
        <label className="flex items-center gap-1.5 font-semibold text-muted-foreground">
          Time limit (s)
          <input
            type="number"
            min={1}
            max={MAX_TIME_LIMIT_S}
            value={timeLimit}
            onChange={(e) => setTimeLimit(e.target.valueAsNumber)}
            data-testid="solve-time-limit"
            className="w-20 rounded-md border border-border bg-transparent px-2 py-1 font-medium text-foreground"
          />
        </label>
        <Button
          size="sm"
          className="gap-1.5 text-xs"
          disabled={busy || !validLimit}
          onClick={() => solve.mutate({ instance, timeLimitS: timeLimit })}
          data-testid="solve-button"
        >
          <Play className="h-3.5 w-3.5" />
          <span>{busy ? 'Solving…' : 'Solve'}</span>
        </Button>
        {status && (
          <span role="status" data-testid="solve-status" data-status={status} data-phase={phase}>
            {message[status]}
          </span>
        )}
      </CardContent>
    </Card>
  );
};
