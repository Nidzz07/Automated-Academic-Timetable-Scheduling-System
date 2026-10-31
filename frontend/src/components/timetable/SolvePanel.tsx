import React, { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { HttpChronosApiClient, EdgeListInstance, JobStatus } from '@/api/chronosApi';
import { instanceSolutionQueryKey, useJobQuery, useSolveMutation } from '@/api/queries';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { STALE_SOLVE, UI, solveStatusText } from '@/lib/wording';
import { Play } from 'lucide-react';

// The backend's SolveRequest bounds (backend/app/service.py DEFAULT_TIME_LIMIT_S, MAX_TIME_LIMIT_S)
const DEFAULT_TIME_LIMIT_S = 300;
const MAX_TIME_LIMIT_S = 1800;

interface SolvePanelProps {
  client: HttpChronosApiClient;
  instance: EdgeListInstance;
  /** The instance's latest job; kept by the caller, so it survives switching instance and back */
  jobId: string | null;
  onJobStarted: (instance: EdgeListInstance, jobId: string) => void;
  /** How often to poll GET /jobs/{id} */
  pollMs?: number;
  /** A finished solve just became the official timetable */
  onOfficial?: () => void;
}

/**
 * Solve a backend instance: POST /instances/{id}/solve, then poll the job until it ends.
 * A solved or infeasible result replaces the instance's solution in the query cache, so the
 * grid, quality card and diagnosis panel show it. A timeout leaves it untouched (D33), and so
 * does a stale result, which the backend keeps but never makes official (D56).
 */
export const SolvePanel: React.FC<SolvePanelProps> = ({ client, instance, jobId, onJobStarted, pollMs = 1000, onOfficial }) => {
  const [timeLimit, setTimeLimit] = useState(DEFAULT_TIME_LIMIT_S);
  const solve = useSolveMutation(client, onJobStarted);
  const job = useJobQuery(client, jobId, pollMs);
  const queryClient = useQueryClient();

  const solution = job.data?.solution;
  const stale = job.data?.stale === true;
  useEffect(() => {
    if (solution && !stale) {
      queryClient.setQueryData(instanceSolutionQueryKey(instance), solution);
      onOfficial?.();
    }
    // onOfficial changes every render; only a new result is news
  }, [solution, stale, instance, queryClient]);

  const failure = solve.error ?? job.error;
  const status: JobStatus | null = failure ? 'error' : job.data?.status ?? solve.data?.status ?? null;
  // a job being re-read after coming back to the instance counts as busy until its status is known
  const busy = solve.isPending || (jobId !== null && job.isPending) || status === 'queued' || status === 'running';
  const validLimit = timeLimit > 0 && timeLimit <= MAX_TIME_LIMIT_S;
  const phase = status === 'running' ? job.data?.phase : undefined;

  return (
    <Card data-testid="solve-panel">
      <CardHeader className="pb-3">
        <CardTitle>Generate a timetable</CardTitle>
        <CardDescription>{UI.generateNote}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-wrap items-center gap-3 pt-0">
        <label className="flex items-center gap-1.5 font-semibold">
          {UI.timeLimit}
          <input
            type="number"
            min={1}
            max={MAX_TIME_LIMIT_S}
            value={timeLimit}
            onChange={(e) => setTimeLimit(e.target.valueAsNumber)}
            data-testid="solve-time-limit"
            className="w-24 rounded-md border border-input bg-transparent px-2 py-1 font-medium"
          />
        </label>
        <Button
          size="sm"
          className="gap-1.5"
          disabled={busy || !validLimit}
          onClick={() => solve.mutate({ instance, timeLimitS: timeLimit })}
          data-testid="solve-button"
        >
          <Play className="h-4 w-4" />
          <span>{busy ? UI.generating : UI.generate}</span>
        </Button>
        {status && (
          <span role="status" data-testid="solve-status" data-status={status} data-phase={phase} data-stale={stale || undefined}>
            {stale && status !== 'error'
              ? STALE_SOLVE
              : solveStatusText(status, { phase, timeLimitS: job.data?.time_limit_s, error: failure?.message ?? job.data?.error })}
          </span>
        )}
      </CardContent>
    </Card>
  );
};
