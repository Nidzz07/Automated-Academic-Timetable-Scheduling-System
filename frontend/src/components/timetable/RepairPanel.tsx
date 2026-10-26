import React, { useMemo, useState } from 'react';
import { ApiError, JobStatus } from '@/api/chronosApi';
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
  entityName,
  facultyLoad,
  facultyText,
  loadText,
} from '@/adapters/timetable';
import { InfeasibilityDiagnosisPanel } from './InfeasibilityDiagnosisPanel';
import { changeText } from './AcceptedChangesPanel';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Check, Wrench, X } from 'lucide-react';

/** A solved repair not yet accepted, against the solution it started from (D48). */
export interface RepairProposal {
  base: SolvedSolution;
  result: SolvedSolution;
  changes: RepairChangeView[];
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
  /** Forget the job: the grid shows the official timetable again */
  onDiscard: () => void;
}

const selectClass = 'rounded-md border border-border bg-transparent px-2 py-1 font-medium text-foreground';
const score = (s: SolvedSolution) => toQualityView(s).score;

/**
 * Repair the official timetable (S14c): mark a faculty member or a room unavailable at some
 * slots, or (from the grid) move a session, then poll the job. A solved result is shown with
 * every changed session and the score change, and becomes official only when accepted (D49).
 * A timeout is never shown as infeasible (D33).
 */
export const RepairPanel: React.FC<RepairPanelProps> = ({ repair, jobId, proposal, edgeList, labels, workload, onDiscard }) => {
  const [kind, setKind] = useState<'faculty' | 'room'>('faculty');
  const [target, setTarget] = useState('');
  const [slots, setSlots] = useState<string[]>([]);
  const grid = useMemo(() => buildWeekGrid(edgeList), [edgeList]);
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
  const status: JobStatus | null = failure ? 'error' : data?.status ?? start.data?.status ?? null;
  const pending = data?.status === 'solved' && !data.accepted_at;
  const busy = start.isPending || (jobId !== null && job.isPending) || status === 'queued' || status === 'running';

  const markUnavailable = () => {
    const picked = slots.map((key) => {
      const [day, period] = key.split('-').map(Number);
      return { day, period };
    });
    start.mutate(
      kind === 'faculty'
        ? { kind: 'faculty_unavailable', faculty_id: target, slots: picked }
        : { kind: 'room_unavailable', room_id: target, slots: picked }
    );
  };

  const where = (a: SessionAssignment) => {
    const room = edgeList.rooms.find((r) => r.id === (a.sub_room_id ?? a.room_id));
    return `${DAY_NAMES[a.day]} P${a.period}, ${room ? labels.room(room) : a.room_id}`;
  };
  // A substitution changes two teachers' loads: who teaches the session now, and the substitute
  const substitution = data?.change?.kind === 'substitute_faculty' ? data.change : null;
  const loads = useMemo(() => {
    if (!substitution || !workload) return [];
    const from = workload.before.find((s) => s.sessionId === substitution.session_id)?.facultyId;
    const load = (sessions: EnrichedSession[], id: string) => facultyLoad(sessions.filter((s) => s.facultyId === id));
    return [...new Set([from ?? '', substitution.faculty_id])]
      .filter((id) => id !== '')
      .map((id) => ({ id, before: load(workload.before, id), after: load(workload.after, id) }));
  }, [substitution, workload]);
  const before = proposal ? score(proposal.base) : null;
  const after = proposal ? score(proposal.result) : null;

  const message: Record<JobStatus, string> = {
    queued: 'Queued: waiting for a solver worker.',
    running: 'Running: repairing the timetable.',
    solved: data?.accepted_at
      ? 'Accepted: the repaired timetable is now the official one.'
      : 'Proposed: the grid shows the repaired timetable with every changed session outlined. It is not official until accepted.',
    infeasible: 'Infeasible: no timetable satisfies this change. The diagnosis below shows why.',
    timeout: `No repair found within ${data?.time_limit_s} s. This does not prove it is impossible.`,
    error: `Repair failed: ${failure?.message ?? data?.error ?? 'unknown error'}`,
  };

  return (
    <Card data-testid="repair-panel">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Repair the timetable</CardTitle>
        <CardDescription>
          Changes the official timetable as little as possible. Drag a session on the grid to move it, mark a
          faculty member or a room unavailable, or find a substitute from a session's details.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0 text-xs">
        <fieldset disabled={busy || pending} className="space-y-2" data-testid="mark-unavailable">
          <legend className="font-semibold text-foreground">Mark unavailable</legend>
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
              <option value="faculty">Faculty member</option>
              <option value="room">Room</option>
            </select>
            <select
              aria-label={kind === 'faculty' ? 'Unavailable faculty member' : 'Unavailable room'}
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
          <table className="border-collapse text-[11px]">
            <thead>
              <tr>
                <th />
                {grid.teachingPeriods.map((p) => (
                  <th key={p} className="px-1 font-mono font-normal text-muted-foreground">
                    P{p}
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
                    return (
                      <td key={p} className="px-1 text-center">
                        <input
                          type="checkbox"
                          aria-label={`${DAY_NAMES[day]} P${p}`}
                          checked={slots.includes(key)}
                          onChange={(e) =>
                            setSlots((s) => (e.target.checked ? [...s, key] : s.filter((k) => k !== key)))
                          }
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          <Button
            size="sm"
            className="gap-1.5 text-xs"
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
            {message[status]}
          </p>
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
                    : `${before.toFixed(1)} → ${after.toFixed(1)} (${after - before >= 0 ? '+' : ''}${(after - before).toFixed(1)})`}
                </p>
                {loads.length > 0 && (
                  <div data-testid="substitution-loads">
                    <p className="font-semibold">Weekly load</p>
                    <ul className="space-y-1">
                      {loads.map((l) => (
                        <li key={l.id} data-testid={`substitution-load-${l.id}`}>
                          {facultyText(labels, l.id)}: {loadText(l.before)} → {loadText(l.after)} hrs/wk
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <p className="font-semibold">
                  {proposal.changes.length} session{proposal.changes.length === 1 ? '' : 's'} changed
                </p>
                <ul className="space-y-1">
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
                className="gap-1 text-xs"
                disabled={!proposal || accept.isPending || !!accept.error}
                onClick={() => accept.mutate(data.id)}
                data-testid="accept-repair"
              >
                <Check className="h-3.5 w-3.5" />
                Accept
              </Button>
              <Button variant="outline" size="sm" className="gap-1 text-xs" onClick={onDiscard} data-testid="discard-repair">
                <X className="h-3.5 w-3.5" />
                Discard
              </Button>
            </div>
          </div>
        )}

        {data?.status === 'infeasible' && data.solution && isInfeasibleSolution(data.solution) && (
          <InfeasibilityDiagnosisPanel infeasibleSolution={data.solution} edgeList={edgeList} labels={labels} />
        )}
      </CardContent>
    </Card>
  );
};
