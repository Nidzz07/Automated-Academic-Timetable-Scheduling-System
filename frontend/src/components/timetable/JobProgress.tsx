import React, { useEffect, useState } from 'react';
import { JOB_ANSWER_WITHIN_MS, JobStatus } from '@/api/chronosApi';
import { jobQueuedText, jobRunningText, jobStartingText } from '@/lib/wording';

/**
 * How long past its limit a job may stay queued or running before the page stops waiting on it. The
 * server's own budget has passed by then; it covers a slow finish, not a job that never ends.
 */
export const PAST_LIMIT_GRACE_S = 60;

/** When each job was first seen in each state, kept by the caller so it survives a remounted panel. */
export type JobClocks = Map<string, number>;

/** Whole seconds since `since`, ticking every second; read from the clock, so a throttled tab stays right. */
export function useElapsedSeconds(since: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since === null) return;
    setNow(Date.now());
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [since]);
  return since === null ? 0 : Math.max(0, Math.floor((now - since) / 1000));
}

interface JobProgressInput {
  /** When the request that starts the job was sent, while it waits for an answer */
  postedAt: number | null;
  jobId: string | null;
  status: JobStatus | null;
  /** The job's time_limit_s, once it has been read */
  limitS?: number;
  /** It waits for this UI's earlier job, which has its own limit: not stuck */
  waiting?: boolean;
  clocks: JobClocks;
}

/**
 * What to show while a job is under way, counted in the browser: the wait for the server's answer,
 * the wait for a worker, then the run against its limit (the limit starts when it runs, so the
 * clock starts again). `stalled` once it has gone PAST_LIMIT_GRACE_S beyond its limit.
 */
export function useJobProgress({ postedAt, jobId, status, limitS, waiting, clocks }: JobProgressInput) {
  const state = status === 'queued' || status === 'running' ? status : null;
  const key = jobId !== null && state ? `${jobId}:${state}` : null;
  if (key && !clocks.has(key)) clocks.set(key, Date.now());
  const seconds = useElapsedSeconds(postedAt ?? (key ? clocks.get(key)! : null));
  const stalled = postedAt === null && state !== null && limitS !== undefined && !waiting && seconds > limitS + PAST_LIMIT_GRACE_S;

  let text: string | null = null;
  if (postedAt !== null) text = jobStartingText(seconds, JOB_ANSWER_WITHIN_MS / 1000);
  else if (!stalled && state === 'queued') text = jobQueuedText(seconds);
  else if (!stalled && state === 'running') text = jobRunningText(seconds, limitS);
  return { text, stalled };
}

/** The ticking line. role="timer" is not announced each second, unlike the status beside it. */
export const JobProgressText: React.FC<{ text: string | null; testId: string }> = ({ text, testId }) =>
  text ? (
    <span role="timer" data-testid={testId} className="font-semibold tabular-nums">
      {text}
    </span>
  ) : null;
