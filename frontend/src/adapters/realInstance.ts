/**
 * The real instance's side files (data/instances/even-2025-26/), none of them a contract:
 * anomalies.json (ingestion anomaly report) and the timetable as printed,
 * real_baseline.assignment.json + real_baseline.report.json (S12b, written by
 * ingestion/real_baseline.py; see docs/real-baseline-even-2025-26.md).
 */

import type { DayIndex, QualityRule, QualityView, SessionAssignment } from '@/adapters/solution';
import type { EdgeList } from '@/adapters/timetable';

/** anomalies.json, written by `python -m ingestion.anomalies`. */
export interface AnomalyReport {
  counts: {
    total: number;
    needs_human: number;
    /** Anomalies per category, as the report counts them */
    by_category?: Record<string, number>;
    by_resolution?: Record<string, number>;
  };
  anomalies: Array<{
    category: string;
    source_file: string;
    location: string;
    message: string;
    /** The ROADMAP decision that resolves it (e.g. "D24"), or "needs human" */
    resolution: string;
  }>;
}

export const NEEDS_HUMAN = 'needs human';

/** One violation of the time-only check on the printed timetable. */
export interface PrintedViolation {
  kind: string;
  session_ids: string[];
  slots: Array<{ day: DayIndex; period: number }>;
  detail: string;
  /** Per session: subject code, cohort, faculty and the printed cell text, named from display.json */
  sessions: Record<string, { subject: string; cohort: string; faculty: string; printed: string }>;
}

interface AssignmentFile {
  assignment: Record<
    string,
    { day: DayIndex; period: number; room_id: string | null; sub_room_id: string | null }
  >;
}

interface ReportFile {
  violations: PrintedViolation[];
  quality: { score: number; rules_version: string; not_evaluated_rule_ids: string[]; breakdown: QualityRule[] };
}

export interface PrintedBaseline {
  /** Placements as printed; room_id is '' where the printed room is not in the edge list's room set (D10, D29) */
  assignment: SessionAssignment[];
  violations: PrintedViolation[];
  quality: QualityView;
}

/**
 * The printed timetable on the edge list's grid. Throws when the files are out of step with
 * the edge list (a session it does not have), since every cell would then be misplaced.
 */
export function toPrintedBaseline(assignmentFile: unknown, reportFile: unknown, edgeList: EdgeList): PrintedBaseline {
  const { assignment } = assignmentFile as AssignmentFile;
  const { violations, quality } = reportFile as ReportFile;
  const known = new Set(edgeList.sessions.map((s) => s.id));
  const unknown = [
    ...Object.keys(assignment),
    ...violations.flatMap((v) => v.session_ids),
  ].filter((id) => !known.has(id));
  if (unknown.length) {
    throw new Error(`real_baseline files name sessions edge_list.json does not have: ${unknown.join(', ')}`);
  }
  return {
    assignment: Object.entries(assignment).map(([session_id, a]) => ({
      session_id,
      day: a.day,
      period: a.period,
      room_id: a.room_id ?? '',
      sub_room_id: a.sub_room_id,
    })),
    violations,
    quality: {
      score: quality.score,
      rulesVersion: quality.rules_version,
      notEvaluatedRuleIds: quality.not_evaluated_rule_ids,
      rules: quality.breakdown,
    },
  };
}
