import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ApiError, JobStatus, NoAnswerError, RepairChange } from '@/api/chronosApi';
import { useRepair } from '@/api/queries';
import {
  RepairChangeView,
  SessionAssignment,
  SolvedSolution,
  isInfeasibleSolution,
  toQualityView,
} from '@/adapters/solution';
import {
  DAY_NAMES,
  EdgeList,
  EnrichedSession,
  Labels,
  buildWeekGrid,
  diagnosisName,
  entityName,
  facultyLoad,
  facultyText,
  slotText,
} from '@/adapters/timetable';
import { InfeasibilityDiagnosisPanel } from './InfeasibilityDiagnosisPanel';
import { changeText } from './AcceptedChangesPanel';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { formatScore, formatScoreChange, periodLabel } from '@/lib/format';
import {
  SERVER_NO_ANSWER,
  SERVER_PAST_LIMIT,
  TAUGHT_PERIOD_KEY,
  UI,
  jobErrorText,
  loadChangeText,
  loadLimitHours,
  refusalText,
  repairStatusText,
  repairSummary,
  taughtPeriodText,
} from '@/lib/wording';
import { JobClocks, JobProgressText, useJobProgress } from './JobProgress';
import { CodeDetails, CodeLine } from './MethodDetails';
import { LoadLimitChange } from './OverLimitWarning';
import { Check, RotateCw, Wrench, X } from 'lucide-react';

/** A solved repair not yet accepted, against the solution it started from (D48). */
export interface RepairProposal {
  base: SolvedSolution;
  result: SolvedSolution;
  changes: RepairChangeView[];
}

/** A teacher and the periods to mark unavailable, for a person to check and send. */
export interface RepairPrefill {
  facultyId: string;
  slots: Array<{ day: number; period: number }>;
}

interface RepairPanelProps {
  repair: ReturnType<typeof useRepair>;
  jobId: string | null;
  proposal: RepairProposal | null;
  edgeList: EdgeList;
  labels: Labels;
  /**
   * Weekly loads around a substitution: the official timetable on the current edge list (before)
   * and the proposal on the job's edge list (after)
   */
  workload?: { before: EnrichedSession[]; after: EnrichedSession[] };
  /**
   * An earlier job of this UI still queued or running ("the solve of this instance"): a queued
   * repair waits for it. The backend does not say what else holds its workers.
   */
  waitingFor?: string | null;
  /** The official timetable's sessions: the mark-unavailable grid shows which periods a teacher teaches */
  official?: EnrichedSession[];
  /** Fills in the mark-unavailable form (the substitute finder's way out); each new object fills it again */
  prefill?: RepairPrefill | null;
  /** Start a repair for this change */
  onStart: (change: RepairChange) => void;
  /** Forget the job: the grid shows the official timetable again */
  onDiscard: () => void;
  /** When a job started; kept by the caller, so it survives this panel being mounted again */
  jobClocks?: JobClocks;
}

const selectClass = 'rounded-md border border-border bg-transparent px-2 py-1 font-medium text-foreground';
const score = (s: SolvedSolution) => toQualityView(s).score;

/**
 * Repair the official timetable (S14c): mark a faculty member or a room unavailable at some
 * slots, or (from the grid) move a session, then poll the job. A solved result is shown with
 * every changed session and the score change, and becomes official only when accepted (D49).
 * A timeout is never shown as infeasible (D33). Every ending can be left: a proposal, an
 * impossible change, a timeout or a failure by Discard, which returns the panel to its start. No
 * answer from the server, or a job past its limit, ends the wait with Try again and Discard.
 */
export const RepairPanel: React.FC<RepairPanelProps> = ({
  repair,
  jobId,
  proposal,
  edgeList,
  labels,
  workload,
  waitingFor,
  official = [],
  prefill,
  onStart,
  onDiscard,
  jobClocks,
}) => {
  const [kind, setKind] = useState<'faculty' | 'room'>('faculty');
  const [target, setTarget] = useState('');
  const [slots, setSlots] = useState<string[]>([]);
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
  const markButton = useRef<HTMLButtonElement>(null);
  const focusWhenFilled = useRef(false);
  useEffect(() => {
    if (!prefill) return;
    focusWhenFilled.current = true;
    setKind('faculty');
    setTarget(prefill.facultyId);
    setSlots(prefill.slots.map((s) => `${s.day}-${s.period}`));
  }, [prefill]);
  // the button is disabled until the filled-in form has rendered
  useEffect(() => {
    if (!focusWhenFilled.current || !target || slots.length === 0) return;
    focusWhenFilled.current = false;
    markButton.current?.focus({ preventScroll: true });
  }, [target, slots]);
  // What the chosen teacher teaches, by "day-period": placed sessions and the fixed items naming them
  const taught = useMemo(() => {
    const at = new Map<string, string[]>();
    if (kind !== 'faculty' || !target) return at;
    const add = (key: string, what: string) => at.set(key, [...(at.get(key) ?? []), what]);
    for (const s of official) {
      if (s.facultyId === target) s.periods.forEach((p) => add(`${s.day}-${p}`, `${s.subjectCode} · ${s.cohortLabel}`));
    }
    edgeList.pinned_occupancy.forEach((p, i) => {
      if (p.faculty_ids.includes(target)) add(`${p.day}-${p.period}`, labels.pin(i)?.label ?? 'a fixed item');
    });
    return at;
  }, [kind, target, official, edgeList, labels]);
  const options = useMemo(
    () =>
      (kind === 'faculty'
        ? edgeList.faculty_availability.map((f) => ({ id: f.faculty_id, label: facultyText(labels, f.faculty_id) }))
        : edgeList.rooms.map((r) => ({ id: r.id, label: labels.room(r) }))
      ).sort((a, b) => a.label.localeCompare(b.label)),
    [kind, edgeList, labels]
  );

  const { start, job, accept } = repair;
  const data = job.data;
  const failure = start.error ?? job.error;
  // the POST's answer stands in only until the job it started is read; with no job it says nothing
  const status: JobStatus | null = failure ? 'error' : data?.status ?? (jobId !== null ? start.data?.status : null) ?? null;
  const pending = data?.status === 'solved' && !data.accepted_at;
  const ownClocks = useRef<JobClocks>(new Map());
  const { text: progress, stalled } = useJobProgress({
    postedAt: start.isPending ? start.submittedAt : null,
    jobId,
    status,
    limitS: data?.time_limit_s,
    waiting: !!waitingFor,
    clocks: jobClocks ?? ownClocks.current,
  });
  const busy =
    start.isPending || (jobId !== null && job.isPending && !failure) || ((status === 'queued' || status === 'running') && !stalled);
  const ended = status === 'infeasible' || status === 'timeout' || status === 'error';
  const noAnswer = failure instanceof NoAnswerError;
  const jobError = !failure && status === 'error' ? jobErrorText(data?.error) : null;
  // A job that could not be read may still be running: read it again. One never started, or stuck, starts anew.
  const change = start.variables ?? data?.change;
  const retry = () => {
    if ((start.error || stalled) && change) onStart(change);
    else job.refetch();
  };

  const resetForm = () => {
    setKind('faculty');
    setTarget('');
    setSlots([]);
  };
  const discard = () => {
    resetForm();
    onDiscard();
  };

  const markUnavailable = () => {
    const picked = slots.map((key) => {
      const [day, period] = key.split('-').map(Number);
      return { day, period };
    });
    onStart(
      kind === 'faculty'
        ? { kind: 'faculty_unavailable', faculty_id: target, slots: picked }
        : { kind: 'room_unavailable', room_id: target, slots: picked }
    );
  };

  const where = (a: SessionAssignment) => {
    const room = edgeList.rooms.find((r) => r.id === (a.sub_room_id ?? a.room_id));
    return `${slotText(a.day, a.period)}, ${room ? labels.room(room) : a.room_id}`;
  };
  // A substitution changes two teachers' loads: who teaches the session now, and the substitute
  const substitution = data?.change?.kind === 'substitute_faculty' ? data.change : null;
  const loads = useMemo(() => {
    if (!substitution || !workload) return [];
    const from = workload.before.find((s) => s.sessionId === substitution.session_id)?.facultyId;
    return [...new Set([from ?? '', substitution.faculty_id])]
      .filter((id) => id !== '')
      .map((id) => ({ id, before: facultyLoad(id, workload.before, edgeList), after: facultyLoad(id, workload.after, edgeList) }));
  }, [substitution, workload, edgeList]);
  // A substitution changes the session's teacher even when nothing moves
  const teacherChange = useMemo(() => {
    if (!substitution || !workload) return null;
    const from = workload.before.find((s) => s.sessionId === substitution.session_id);
    return from ? { what: `${from.subjectCode} · ${from.cohortLabel}`, from: from.facultyId, to: substitution.faculty_id } : null;
  }, [substitution, workload]);
  // the weekly limit as the solver states it in the proposal's S-LOAD16 (else the base's)
  const limit = proposal
    ? loadLimitHours(toQualityView(proposal.result).rules.find((r) => r.rule_id === 'S-LOAD16')) ??
      loadLimitHours(toQualityView(proposal.base).rules.find((r) => r.rule_id === 'S-LOAD16'))
    : null;
  const before = proposal ? score(proposal.base) : null;
  const after = proposal ? score(proposal.result) : null;

  return (
    <Card data-testid="repair-panel">
      <CardHeader className="pb-3">
        <CardTitle>Repair the timetable</CardTitle>
        <CardDescription>{UI.repairNote}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        <fieldset disabled={busy || pending} className="space-y-2" data-testid="mark-unavailable">
          <legend className="text-lg font-semibold">Mark unavailable</legend>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Unavailable kind"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as 'faculty' | 'room');
                setTarget('');
              }}
              className={selectClass}
            >
              <option value="faculty">{UI.teacher}</option>
              <option value="room">Room</option>
            </select>
            <select
              aria-label={kind === 'faculty' ? 'Unavailable teacher' : 'Unavailable room'}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              className={selectClass}
            >
              <option value="">Choose…</option>
              {options.map((o) => (
                <option key={o.id} value={o.id}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <table className="border-collapse text-xs">
            <thead>
              <tr>
                <th />
                {grid.teachingPeriods.map((p) => (
                  <th key={p} className="px-1.5 font-semibold">
                    {periodLabel(p)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {grid.days.map((day) => (
                <tr key={day}>
                  <th className="pr-2 text-left font-medium">{DAY_NAMES[day]}</th>
                  {grid.teachingPeriods.map((p) => {
                    const key = `${day}-${p}`;
                    const teaches = taught.get(key);
                    return (
                      <td
                        key={p}
                        data-testid={teaches ? `taught-${key}` : undefined}
                        className={`px-1.5 py-0.5 text-center ${teaches ? 'bg-primary/15 font-semibold' : ''}`}
                      >
                        <span className="inline-flex items-center gap-0.5">
                          <input
                            type="checkbox"
                            aria-label={slotText(day, p)}
                            title={teaches && taughtPeriodText(teaches)}
                            checked={slots.includes(key)}
                            onChange={(e) =>
                              setSlots((s) => (e.target.checked ? [...s, key] : s.filter((k) => k !== key)))
                            }
                          />
                          {teaches && <span aria-hidden="true">●</span>}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {taught.size > 0 && (
            <p data-testid="taught-key" className="text-xs">
              <span aria-hidden="true">●</span> {TAUGHT_PERIOD_KEY}
            </p>
          )}
          <Button
            ref={markButton}
            size="sm"
            className="gap-1.5"
            disabled={!target || slots.length === 0}
            onClick={markUnavailable}
            data-testid="mark-unavailable-button"
          >
            <Wrench className="h-3.5 w-3.5" />
            <span>{busy ? 'Repairing…' : 'Mark unavailable and repair'}</span>
          </Button>
        </fieldset>

        {status && (
          <p role="status" data-testid="repair-status" data-status={status}>
            {noAnswer
              ? SERVER_NO_ANSWER
              : stalled
                ? SERVER_PAST_LIMIT
                : repairStatusText(status, {
                    accepted: !!data?.accepted_at,
                    waiting: !!waitingFor,
                    timeLimitS: data?.time_limit_s,
                    // what the backend said, by name; a job's own error in plain words
                    error: failure ? refusalText(failure.message, (id) => diagnosisName(id, edgeList, labels)) : jobError?.text,
                  })}
          </p>
        )}
        {progress && (
          <p>
            <JobProgressText text={progress} testId="repair-progress" />
          </p>
        )}
        {jobError?.detail && (
          <CodeDetails testId="repair-error-details">
            <CodeLine>{jobError.detail}</CodeLine>
          </CodeDetails>
        )}

        {pending && (
          <div data-testid="repair-proposal" className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
            {data.change && <p data-testid="repair-change-text">Change: {changeText(data.change, edgeList, labels)}</p>}
            {proposal ? (
              <>
                <p data-testid="repair-score">
                  Score:{' '}
                  {before === null || after === null
                    ? 'not evaluated'
                    : `${formatScore(before)} → ${formatScore(after)} (${formatScoreChange(after - before)})`}
                </p>
                {loads.length > 0 && (
                  <div data-testid="substitution-loads">
                    <p className="font-semibold">Weekly load, before → after</p>
                    <ul className="space-y-1">
                      {loads.map((l) => (
                        <li key={l.id} data-testid={`substitution-load-${l.id}`} className="space-x-2">
                          <span>
                            {facultyText(labels, l.id)}: {loadChangeText(l.before, l.after)}
                          </span>
                          <LoadLimitChange before={l.before.total} after={l.after.total} limit={limit} className="text-xs" />
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p data-testid="repair-summary" className="font-semibold">
                  {repairSummary(proposal.changes.length, teacherChange ? 1 : 0)}
                </p>
                <ul className="space-y-1">
                  {teacherChange && (
                    <li data-testid="repair-teacher-change">
                      <span className="font-medium">{teacherChange.what}</span>: {facultyText(labels, teacherChange.from)} →{' '}
                      {facultyText(labels, teacherChange.to)}
                    </li>
                  )}
                  {proposal.changes.map((c) => (
                    <li
                      key={c.sessionId}
                      data-testid={`repair-change-${c.sessionId}`}
                      data-change={c.slotChanged ? 'slot' : 'room'}
                    >
                      <span className="font-medium">{entityName(c.sessionId, edgeList, labels)}</span>:{' '}
                      {where(c.before)} → {where(c.after)} {c.slotChanged ? '(moved)' : '(room only)'}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p>Loading the timetable this repair started from…</p>
            )}
            {accept.error && (
              <p role="alert" data-testid="accept-error" className="text-destructive">
                {accept.error instanceof ApiError && accept.error.status === 409
                  ? 'The timetable changed meanwhile. Run the repair again.'
                  : accept.error.message}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                className="gap-1"
                disabled={!proposal || accept.isPending || !!accept.error}
                onClick={() => accept.mutate(data.id, { onSuccess: resetForm })}
                data-testid="accept-repair"
              >
                <Check className="h-3.5 w-3.5" />
                Accept
              </Button>
              <Button variant="outline" size="sm" className="gap-1" onClick={discard} data-testid="discard-repair">
                <X className="h-3.5 w-3.5" />
                Discard
              </Button>
            </div>
          </div>
        )}

        {data?.status === 'infeasible' && !failure && data.solution && isInfeasibleSolution(data.solution) && (
          <InfeasibilityDiagnosisPanel infeasibleSolution={data.solution} edgeList={edgeList} labels={labels} forRepair />
        )}

        {(ended || stalled) && (
          <div className="flex gap-2">
            {(noAnswer || stalled) && (
              <Button size="sm" className="gap-1" disabled={!!job.error && job.isFetching} onClick={retry} data-testid="retry-repair">
                <RotateCw className="h-3.5 w-3.5" />
                {UI.tryAgain}
              </Button>
            )}
            <Button variant="outline" size="sm" className="gap-1" onClick={discard} data-testid="discard-repair">
              <X className="h-3.5 w-3.5" />
              {UI.discard}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
};
