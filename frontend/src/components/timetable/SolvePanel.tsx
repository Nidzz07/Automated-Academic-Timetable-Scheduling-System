import React, { useEffect, useId, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { HttpChronosApiClient, EdgeListInstance, JobStatus, NoAnswerError } from '@/api/chronosApi';
import { instanceSolutionQueryKey, useJobQuery, useSolveMutation } from '@/api/queries';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { SERVER_NO_ANSWER, SERVER_PAST_LIMIT, STALE_SOLVE, UI, jobErrorText, solveStatusText } from '@/lib/wording';
import { JobClocks, JobProgressText, useJobProgress } from './JobProgress';
import { CodeDetails, CodeLine } from './MethodDetails';
import { Play, RotateCw, X } from 'lucide-react';

// The backend's SolveRequest bounds (backend/app/service.py DEFAULT_TIME_LIMIT_S, MAX_TIME_LIMIT_S)
const DEFAULT_TIME_LIMIT_S = 300;
const MAX_TIME_LIMIT_S = 1800;

interface SolvePanelProps {
  client: HttpChronosApiClient;
  instance: EdgeListInstance;
  /** The instance's latest job; kept by the caller, so it survives switching instance and back */
  jobId: string | null;
  onJobStarted: (instance: EdgeListInstance, jobId: string) => void;
  /** Stop following the job: the panel is back at its start */
  onJobDiscarded?: (instance: EdgeListInstance) => void;
  /** How often to poll GET /jobs/{id} */
  pollMs?: number;
  /** A finished solve just became the official timetable */
  onOfficial?: () => void;
  /**
   * The solves already written to the query cache. Kept by the caller, because this panel is mounted
   * again on every return to its instance, when an older solve must not replace what came after it
   * (an accepted repair, cleared changes).
   */
  appliedSolves?: Set<string>;
  /** When a job started, kept by the caller for the same reason */
  jobClocks?: JobClocks;
}

/**
 * Solve a backend instance: after a confirm step, since it replaces the official timetable for
 * everyone (D56), POST /instances/{id}/solve, then poll the job until it ends. A solved or
 * infeasible result replaces the instance's solution in the query cache, so the grid, quality card
 * and diagnosis panel show it. A timeout leaves it untouched (D33), and so does a stale result,
 * which the backend keeps but never makes official (D56). No answer from the server, or a job past
 * its limit, ends the wait with Try again and Discard.
 */
export const SolvePanel: React.FC<SolvePanelProps> = ({
  client,
  instance,
  jobId,
  onJobStarted,
  onJobDiscarded,
  pollMs = 1000,
  onOfficial,
  appliedSolves,
  jobClocks,
}) => {
  const [timeLimit, setTimeLimit] = useState(DEFAULT_TIME_LIMIT_S);
  const [confirming, setConfirming] = useState(false);
  const solve = useSolveMutation(client, onJobStarted);
  const job = useJobQuery(client, jobId, pollMs);
  const queryClient = useQueryClient();
  const ownApplied = useRef(new Set<string>());
  const applied = appliedSolves ?? ownApplied.current;
  const ownClocks = useRef<JobClocks>(new Map());

  const finished = job.data;
  const solution = finished?.solution;
  const stale = finished?.stale === true;
  useEffect(() => {
    // once per job: a result is news when it ends, even if that happened while on another instance
    if (finished && solution && !stale && !applied.has(finished.id)) {
      applied.add(finished.id);
      queryClient.setQueryData(instanceSolutionQueryKey(instance), solution);
      onOfficial?.();
    }
    // onOfficial changes every render; only a new result is news
  }, [finished?.id, solution, stale, instance, queryClient, applied]);

  const failure = solve.error ?? job.error;
  // the POST's answer stands in only until the job it started is read; with no job it says nothing
  const status: JobStatus | null = failure ? 'error' : job.data?.status ?? (jobId !== null ? solve.data?.status : null) ?? null;
  const { text: progress, stalled } = useJobProgress({
    postedAt: solve.isPending ? solve.submittedAt : null,
    jobId,
    status,
    limitS: job.data?.time_limit_s,
    clocks: jobClocks ?? ownClocks.current,
  });
  // a job being re-read after coming back to the instance counts as busy until its status is known
  const busy = solve.isPending || (jobId !== null && job.isPending) || ((status === 'queued' || status === 'running') && !stalled);
  const validLimit = timeLimit > 0 && timeLimit <= MAX_TIME_LIMIT_S;
  const phase = status === 'running' ? job.data?.phase : undefined;
  const noAnswer = failure instanceof NoAnswerError;
  const jobError = !failure && status === 'error' ? jobErrorText(job.data?.error) : null;

  // Focus goes to the safe choice, so a second press of Enter cannot start it; Cancel gives it back
  const generateButton = useRef<HTMLButtonElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);
  useEffect(() => {
    if (confirming) cancelButton.current?.focus();
    else if (wasConfirming.current) generateButton.current?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);
  const questionId = useId();

  const start = (variables: { instance: EdgeListInstance; timeLimitS: number }) => solve.mutate(variables);
  // A job that could not be read may still be running: read it again. One never started, or stuck, starts anew.
  const retry = () => {
    if (solve.error || stalled) start(solve.variables ?? { instance, timeLimitS: timeLimit });
    else job.refetch();
  };
  const discard = () => {
    solve.reset();
    onJobDiscarded?.(instance);
  };

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
          ref={generateButton}
          size="sm"
          className="gap-1.5"
          disabled={busy || !validLimit || confirming}
          onClick={() => setConfirming(true)}
          data-testid="solve-button"
        >
          <Play className="h-4 w-4" />
          <span>{busy ? UI.generating : UI.generate}</span>
        </Button>
        {status && !solve.isPending && (
          <span role="status" data-testid="solve-status" data-status={status} data-phase={phase} data-stale={stale || undefined}>
            {noAnswer
              ? SERVER_NO_ANSWER
              : stalled
                ? SERVER_PAST_LIMIT
                : stale && status !== 'error'
                  ? STALE_SOLVE
                  : solveStatusText(status, {
                      phase,
                      timeLimitS: job.data?.time_limit_s,
                      error: failure?.message ?? jobError?.text,
                    })}
          </span>
        )}
        <JobProgressText text={progress} testId="solve-progress" />
        {jobError?.detail && (
          <CodeDetails testId="solve-error-details">
            <CodeLine>{jobError.detail}</CodeLine>
          </CodeDetails>
        )}
        {(noAnswer || stalled) && (
          <span className="flex gap-2">
            <Button size="sm" className="gap-1" disabled={!!job.error && job.isFetching} onClick={retry} data-testid="retry-solve">
              <RotateCw className="h-3.5 w-3.5" />
              {UI.tryAgain}
            </Button>
            <Button variant="outline" size="sm" className="gap-1" onClick={discard} data-testid="discard-solve">
              <X className="h-3.5 w-3.5" />
              {UI.discard}
            </Button>
          </span>
        )}
        {confirming && (
          <div
            role="group"
            aria-labelledby={questionId}
            data-testid="confirm-generate"
            className="w-full space-y-2 rounded-lg border border-destructive/40 p-3"
          >
            <p id={questionId}>{UI.generateConfirm}</p>
            <div className="flex gap-2">
              <Button
                variant="destructive"
                size="sm"
                onClick={() => {
                  setConfirming(false);
                  start({ instance, timeLimitS: timeLimit });
                }}
                data-testid="confirm-generate-button"
              >
                {UI.generate}
              </Button>
              <Button ref={cancelButton} variant="outline" size="sm" onClick={() => setConfirming(false)} data-testid="cancel-generate">
                {UI.cancel}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
