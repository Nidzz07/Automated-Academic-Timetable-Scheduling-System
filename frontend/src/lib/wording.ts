/**
 * Plain-language wording for the codes the backend, solver and ingestion use, for people outside
 * the project. One table per kind of code, each with a fallback for a code it does not list; the
 * raw code is still shown beside the words as small secondary text. Wording only: no number here
 * is computed (quality is the solver's, D34).
 */

import type { AuditEntry, JobStatus, RepairChange } from '@/api/chronosApi';
import type { DiagnosisMethod, QualityRule } from '@/adapters/solution';
import { EdgeList, EnrichedSession, FacultyLoad, Labels, entityName, sessionPhrase, slotsText } from '@/adapters/timetable';
import { displayText } from '@/lib/format';

/** An unlisted code in words: "frozen_out_of_scope" -> "Frozen out of scope". */
export function humanise(code: string): string {
  const words = code.replace(/[_-]+/g, ' ').trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const lookup = (table: Record<string, string>, code: string) => table[code] ?? humanise(code);

/** Solver text for reading: the faculty and cohort ids it names by name (null keeps the id), then displayText. */
export function readableSolverText(text: string, nameOf?: (id: string) => string | null): string {
  const named = nameOf ? text.replace(/\b(?:fac|coh)-[a-z0-9]+(?:-[a-z0-9]+)*/g, (id) => nameOf(id) ?? id) : text;
  return displayText(named);
}

// --- Quality rules (ROADMAP §6, D34) -----------------------------------------------------------

export interface RuleWording {
  title: string;
  /** One sentence in everyday words */
  meaning: string;
  /** What one unit of `raw` is, singular and plural */
  unit: [string, string];
}

export const RULE_WORDING: Record<string, RuleWording> = {
  'S-GAP': {
    title: "Students' free periods",
    meaning: 'An empty period between two classes on the same day for a division or batch.',
    unit: ['free period', 'free periods'],
  },
  'S-B2B': {
    title: 'Teachers without a break',
    meaning: 'A teacher has classes in two periods in a row with no break; a two-hour lab counts once.',
    unit: ['pair of periods', 'pairs of periods'],
  },
  'S-LOAD16': {
    title: 'Teachers over the weekly limit',
    meaning: "A teacher's weekly teaching hours are above the department's target.",
    unit: ['teacher', 'teachers'],
  },
  FAC_LOAD_IMBALANCE: {
    title: 'Uneven teaching days',
    meaning: "For each teacher, the hours on their busiest day minus their lightest day, added up over all teachers.",
    unit: ['hour', 'hours'],
  },
};

export const ruleWording = (ruleId: string): RuleWording =>
  RULE_WORDING[ruleId] ?? { title: humanise(ruleId), meaning: 'A quality rule of the solver.', unit: ['case', 'cases'] };

/** A solver number as given, without a trailing ".0": 6, 50.5 */
const num = (n: number) => (Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2))));
const points = (n: number) => `${num(n)} point${n === 1 ? '' : 's'}`;

/** "Found 15 free periods → −30 points (2 points each)", or why the rule was not checked. */
export function ruleResult(rule: QualityRule): string {
  if (rule.status === 'not_evaluated') return `Not checked: ${rule.reason}`;
  const [one, many] = ruleWording(rule.rule_id).unit;
  const found = `Found ${num(rule.raw)} ${rule.raw === 1 ? one : many}`;
  if (rule.penalty === 0) return `${found} → no points lost`;
  return `${found} → −${points(rule.penalty)} (${points(rule.weight)} each)`;
}

// --- Weekly load limit (D11, S-LOAD16) -----------------------------------------------------------

/**
 * The weekly hour limit as the solver's S-LOAD16 result states it ("… above 16 h a week …" or
 * "No faculty member teaches more than 16 h a week."): the rule's threshold_hours in
 * solver/rules/quality_rules.yaml, which the frontend cannot read itself. null when the rule was
 * not evaluated or not reported, so no limit is shown.
 */
export function loadLimitHours(rule: QualityRule | undefined): number | null {
  if (rule?.status !== 'evaluated') return null;
  const m = rule.explanation.match(/(?:above|more than) (\d+(?:\.\d+)?) h a week/);
  return m ? Number(m[1]) : null;
}

/** "Over 16 h limit: 17 h" when a load is above the limit; null otherwise. */
export const overLimitText = (hours: number, limit: number | null) =>
  limit !== null && hours > limit ? `Over ${num(limit)} h limit: ${num(hours)} h` : null;

/** "18 h: 6 h scheduled + 12 h fixed items" */
export const loadPartsText = (load: FacultyLoad) => `${load.total} h: ${load.scheduled} h scheduled + ${load.fixed} h fixed items`;

// --- Fixed items (display.json pins: kind and, for frozen items, the decision behind it) -------

/** The pin's kind in words; a frozen item by its decision (D24, D26, D44), never naming either. */
export const PIN_KIND_LABELS: Record<string, string> = {
  'frozen:D24': 'Fixed: elective or minor course',
  'frozen:D26': 'Fixed: runs alongside another subject',
  'frozen:D44': 'Fixed: taught by another department',
  frozen: 'Fixed: kept at its printed time',
  out_of_scope: 'Fixed: session of another programme',
  mdm: 'Fixed: multidisciplinary minor course',
  hss: 'Fixed: humanities course',
  llc: 'Fixed: liberal learning course',
  activity: 'Fixed: student activity',
  project: 'Fixed: major project',
  exam: 'Fixed: exam',
  'accepted change': 'Fixed: closed by an accepted change',
};

export function pinKindLabel(kind: string | null, decision?: string | null): string {
  if (!kind) return 'Fixed: cannot be moved';
  return PIN_KIND_LABELS[`${kind}:${decision}`] ?? PIN_KIND_LABELS[kind] ?? `Fixed: ${humanise(kind).toLowerCase()}`;
}

/** How many cohorts a fixed-item card names before "and N more". */
const LISTED_COHORTS = 3;

/** "SE-Comp A, SE-Comp A batch A, SE-Comp A batch B and 2 more" */
export const cohortListText = (labels: string[]) =>
  labels.length > LISTED_COHORTS
    ? `${labels.slice(0, LISTED_COHORTS).join(', ')} and ${labels.length - LISTED_COHORTS} more`
    : labels.join(', ');

/** A session with a fixed slot, in its details window. */
export const FIXED_SESSION_NOTE = 'It is fixed to this time, so the solver never moves it.';

// --- Session details ---------------------------------------------------------------------------

/** "Operating Systems for SE-Comp A (Kailas Devadkar)" */
export const sessionTitle = (s: Pick<EnrichedSession, 'subjectCode' | 'subjectName' | 'cohortLabel' | 'facultyName'>) =>
  sessionPhrase(s.subjectName === 'Subject' ? s.subjectCode : s.subjectName, s.cohortLabel, s.facultyName);

// --- Diagnosis (contract solution_v2 Kind, relaxation action and verification) -----------------

/** Per diagnosis.method; `badge` is small secondary text, a new contract method is one more line here. */
export const DIAGNOSIS_METHOD_LABELS: Record<DiagnosisMethod, { badge: string; text: string }> = {
  mus: { badge: 'MUS Extraction', text: 'The solver proved that no timetable meets every rule, and found the smallest set of rules that cannot all hold.' },
  search_exhaustion: { badge: 'Search Exhaustion', text: 'A complete search proved that no timetable meets every rule, but no explanation was extracted.' },
  // contract row 9 (D43): a pre-solve certificate, proven but not minimal
  presolve: { badge: 'Presolve', text: 'Proved infeasible by a counting check (not minimal)' },
};
/** solution.v1 does not say how it was diagnosed. */
const UNSTATED_METHOD_LABEL = { badge: 'Method not stated (solution.v1)', text: 'The solver reported that no timetable meets every rule.' };
export const diagnosisMethodLabel = (method: DiagnosisMethod | null) => (method ? DIAGNOSIS_METHOD_LABELS[method] : UNSTATED_METHOD_LABEL);

/** The panel's headings: for a repair the change is what is impossible, for a solve the timetable. */
export const diagnosisHeadings = (forRepair: boolean) => ({
  title: forRepair ? 'This change is not possible' : 'No timetable is possible',
  why: forRepair ? 'Why this change is impossible' : 'Why no timetable is possible',
  fix: 'What would make it possible',
});

/** What an impossible repair means for the timetable; its placed-session count means nothing to a reader. */
export const REPAIR_NOT_APPLIED = 'Nothing from this repair was applied.';

/** How many of an item's named ids a sentence lists before "and N more". */
const LISTED_NAMES = 6;

const DAY_WORDS: Record<string, string> = { Mon: 'Monday', Tue: 'Tuesday', Wed: 'Wednesday', Thu: 'Thursday', Fri: 'Friday' };

/**
 * A sentence of solver/mus.py with names instead of ids: sessions, rooms, faculty, cohorts and
 * `pin.<i>` by `nameOf` (null keeps the id), "Mon P0" as "Monday T0". Its known forms are put in the
 * UI's words ("X moved to Monday T0 in room 601"); any other sentence only gets the names.
 */
export function readableDiagnosisText(text: string, nameOf: (id: string) => string | null): string {
  const name = (id: string) => nameOf(id) ?? id;
  const names = (ids: string) => {
    const all = ids.split(', ').map(name);
    return all.length > LISTED_NAMES ? `${all.slice(0, LISTED_NAMES).join(', ')} and ${all.length - LISTED_NAMES} more` : all.join(', ');
  };
  const reworded = text
    .replace(/^The change: (\S+) is moved to (.+) in (\S+)\.$/, '$1 moved to $2 in $3.')
    .replace(/^The change: /, '')
    .replace(/\b[Rr]oom (?=(?:room|sub)-)/g, '')
    .replace(/Pinned occupancy (\d+) holds (.+?) at /, (_, i: string, ids: string) => `${name(`pin.${i}`)} holds ${names(ids)} at `)
    .replace(/\bFree (?:faculty|cohort|room) (\S+) from the pinned occupancy at /, 'Free $1 from the fixed item at ')
    .replace(/^Lab block \S+: (.+) start together and run over the same contiguous periods\.$/, (_, ids: string) => `These lab sessions start together and run over the same consecutive periods: ${names(ids)}.`)
    .replace(/\bpin\.\d+\b|\b[a-z]+-[a-z0-9]+(?:[-_.][a-z0-9]+)*\b/gi, (id) => nameOf(id) ?? id)
    .replace(/\b(Mon|Tue|Wed|Thu|Fri) (P\d)\b/g, (_, day: string, period: string) => `${DAY_WORDS[day]} ${period}`);
  const shown = displayText(reworded);
  return shown.charAt(0).toUpperCase() + shown.slice(1);
}

export const CONSTRAINT_KIND_LABELS: Record<string, string> = {
  FACULTY_CLASH: 'A teacher would be in two places at once',
  COHORT_CLASH: 'A class would have two sessions at once',
  ROOM_CLASH: 'A room would be booked twice at once',
  ROOM_OCCUPANCY: 'A room and one of its parts would be used at once',
  ROOM_CAPACITY: 'The room is too small for the class',
  ROOM_TYPE: 'The room is the wrong kind (lab or classroom)',
  FACULTY_UNAVAILABLE: 'The teacher is not available then',
  PINNED_BLOCK: 'A fixed item already holds this time',
  LAB_CONTIGUITY: 'A lab must take two periods in a row',
  FIXED_SLOT: 'This session is fixed to this time',
};
export const constraintKindLabel = (kind: string) => lookup(CONSTRAINT_KIND_LABELS, kind);

export const RELAXATION_ACTION_LABELS: Record<string, string> = {
  UNFIX_SLOT: 'Let the session move from its fixed time',
  RELAX_FACULTY_AVAILABILITY: 'Make the teacher available at that time',
  RELAX_PINNED_BLOCK: 'Free the class from the fixed item at that time',
  RECLASSIFY_ROOM: 'Allow the room to be used as the other kind (lab or classroom)',
  MANUAL: 'Needs a decision by a person',
};
export const relaxationActionLabel = (action: string) => lookup(RELAXATION_ACTION_LABELS, action);

export const VERIFICATION_LABELS: Record<string, string> = {
  restored: 'checked: with this change a timetable exists',
  still_infeasible: 'checked: still no timetable with this change alone',
  timeout: 'not confirmed: the check ran out of time',
  not_attempted: 'not checked',
};
export const verificationLabel = (status: string) => lookup(VERIFICATION_LABELS, status);

// --- Ingestion anomaly categories (anomalies.json) ----------------------------------------------

export const ANOMALY_CATEGORY_LABELS: Record<string, string> = {
  scheme_excluded: 'Course left out of the teaching scheme',
  scheme_note: 'Note on the teaching scheme',
  duplicate_room: 'Room listed twice',
  lab_capacity_conflict: 'Two files give a lab different sizes',
  sub_room_labels_derived: 'Lab places named by Chronos',
  lab_excluded: 'Lab not used for B.Tech',
  unknown_room_usage: 'Unclear what a room is used for',
  room_not_ce: 'Room outside the department, not used',
  division_wide_tutorial: 'Tutorial for a whole division instead of per batch',
  initials_not_in_division_legend: "Teacher's initials missing from the division's key",
  unmatched_subject: 'Subject not found in the scheme',
  parallel_division_sessions: 'Two sessions for one division at once',
  malformed_line: 'Timetable cell written in an unexpected way',
  break_partial: 'Break marked on some days only',
  overlaps_break: 'Item runs over a break',
  excluded_item: 'Item kept fixed, not rescheduled',
  frozen_d44: 'Session kept fixed: teacher from another department',
  frozen_d26: 'Session kept fixed: runs alongside another subject',
  lecture_room_excluded: 'Classroom not offered to the scheduler',
  lecture_room_not_class: 'Room is a lab, not a classroom',
  lecture_room_total: 'Lectures printed in rooms the scheduler does not use',
  frozen_room_conflict: 'Timetables disagree on a fixed item’s room',
  room_override: "Lab timetable names another room for a session",
  lab_in_classroom: 'Lab printed in a classroom',
  out_of_scope_in_lab: 'Other programme’s session in a department lab',
  exam_block: 'Exam held in a lab',
  utilisation_mismatch: 'Printed lab use differs from the count',
  frozen_in_lab: 'Minor-course session kept fixed in a lab',
  initials_resolved_d38: 'Teacher’s initials matched by decision D38',
  initials_unresolved: 'Teacher’s initials could not be matched',
  room_label_normalised: 'Room name written another way',
  subroom_beyond_split: 'Lab place beyond the room’s declared parts',
  room_not_generation: 'Room not used for scheduling',
  practical_missing_in_lab_tt: 'Practical missing from the lab timetable',
  practical_room_mismatch: 'Timetables disagree on a practical’s room',
  practical_mismatch: 'Timetables disagree on a practical’s time',
  faculty_day_off: 'Teacher’s day off',
  time_off_grid: 'Time that fits no period',
  load_mismatch: 'Printed workload differs from the count',
  load_above_16: 'Teacher above the weekly target',
  missing_workload: 'No workload line for a teacher',
  no_faculty_page: 'Teacher has no page in the faculty timetable',
  out_of_scope_room_disagreement: 'Other programme’s timetable names another room',
  out_of_scope_initials_unresolved: 'Other programme’s initials could not be matched',
  faculty_tt_line_not_in_grids: 'Faculty timetable line not in the class timetables',
  frozen_out_of_scope: 'Other programme’s session blocks a teacher or room',
  frozen_sources_disagree: 'Sources disagree on a fixed session',
  out_of_scope_not_blocking: 'Other programme’s session that blocks nothing',
  frozen_exam: 'Exam blocks a lab',
  frozen_faculty_tt_mdm: 'Minor-course lab from the faculty timetable kept fixed',
};
export const anomalyCategoryLabel = (category: string) => lookup(ANOMALY_CATEGORY_LABELS, category);

// --- Generated beside printed (numbers read from the data; quality is the solver's, D34) --------

const hardRules = (n: number) => `${n} hard rule${n === 1 ? '' : 's'}`;

/** The comparison card's one factual sentence: hard rules first, the soft-rule score as it falls. */
export function comparisonSentence(
  generatedHard: number,
  printedHard: number,
  generatedScore: number | null,
  printedScore: number | null
): string {
  const soft =
    generatedScore === null || printedScore === null || generatedScore === printedScore
      ? null
      : printedScore > generatedScore
        ? 'higher'
        : 'lower';
  const printed = soft ? `scores ${soft} on the soft rules ${soft === 'higher' ? 'but' : 'and'} breaks ${hardRules(printedHard)}` : `breaks ${hardRules(printedHard)}`;
  return `The printed timetable ${printed}; the generated one breaks ${generatedHard === 0 ? 'none' : hardRules(generatedHard)}.`;
}

// --- A repair's proposal ------------------------------------------------------------------------

/** "2 sessions changed; 1 session: teacher changed", or one of the two; "0 sessions changed" only when nothing did. */
export function repairSummary(placementsChanged: number, teachersChanged: number): string {
  const sessions = (n: number) => `${n} session${n === 1 ? '' : 's'}`;
  return [
    ...(placementsChanged > 0 || teachersChanged === 0 ? [`${sessions(placementsChanged)} changed`] : []),
    ...(teachersChanged > 0 ? [`${sessions(teachersChanged)}: teacher changed`] : []),
  ].join('; ');
}

// --- Audit log (backend/app/service.py: login, solve, repair, accept, clear_changes) ------------

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  login: 'Sign-in',
  solve: 'Timetable generated',
  repair: 'Repair requested',
  accept: 'Repair accepted',
  clear_changes: 'Accepted changes cleared',
};
export const auditActionLabel = (action: string) => lookup(AUDIT_ACTION_LABELS, action);

const JOB_OUTCOME: Record<JobStatus, string> = {
  queued: 'It is waiting to run.',
  running: 'It is running.',
  solved: 'A timetable was found.',
  infeasible: 'No timetable is possible with it.',
  timeout: 'It stopped at its time limit without an answer.',
  error: 'It failed.',
};

/** A change in a sentence: "Swapnali Kurhade's absence on Tuesday T6–T7". */
export function changePhrase(change: RepairChange, edgeList: EdgeList, labels: Labels): string {
  const person = (id: string) => labels.faculty(id).name;
  switch (change.kind) {
    case 'faculty_unavailable':
      return `${person(change.faculty_id)}'s absence on ${slotsText(change.slots)}`;
    case 'room_unavailable':
      return `${entityName(change.room_id, edgeList, labels)} closed on ${slotsText(change.slots)}`;
    case 'move_session':
      return `moving ${entityName(change.session_id, edgeList, labels)} to ${slotsText([change])}`;
    case 'substitute_faculty': {
      // the session without its teacher, whom the substitution replaces
      const s = edgeList.sessions.find((x) => x.id === change.session_id);
      const what = s ? `${labels.subject(s.subject_id)?.code ?? s.subject_id} · ${labels.cohort(s.cohort_id)}` : change.session_id;
      return `${person(change.faculty_id)} teaching ${what} instead`;
    }
  }
}

/** The audit row's change; it logs slots as [day, period] pairs (backend/app/service.py). */
function loggedChange(detail: Record<string, unknown> | null): RepairChange | null {
  const change = detail?.change as (Record<string, unknown> & { kind?: string }) | undefined;
  if (!change?.kind) return null;
  const slots = change.slots as Array<[number, number] | { day: number; period: number }> | undefined;
  return {
    ...change,
    ...(slots ? { slots: slots.map((s) => (Array.isArray(s) ? { day: s[0], period: s[1] } : s)) } : {}),
  } as RepairChange;
}

/**
 * One audit row as a sentence. `rows` are the rows on screen (an accept names its repair's change
 * when that repair's row is among them); `role` is the actor's role when known (the backend logs
 * only the username); `describe` puts a change in words.
 */
export function auditSentence(
  entry: AuditEntry,
  rows: AuditEntry[],
  describe: (change: RepairChange) => string,
  role?: string | null
): string {
  const who = role ? `${entry.actor} (${role.toLowerCase()})` : entry.actor;
  const d = entry.detail ?? {};
  const outcome = () => {
    const status = d.status as JobStatus | undefined;
    const text = status && JOB_OUTCOME[status] ? ` ${JOB_OUTCOME[status]}` : '';
    return d.stale ? `${text} It was not made official: the accepted changes changed while it ran.` : text;
  };
  switch (entry.action) {
    case 'login':
      return d.success === false ? `A sign-in as ${entry.actor} failed.` : `${who} signed in.`;
    case 'solve':
      return `${who} asked the solver to generate a timetable.${outcome()}`;
    case 'repair': {
      const change = loggedChange(entry.detail);
      return `${who} asked for a repair${change ? ` for ${describe(change)}` : ''}.${outcome()}`;
    }
    case 'accept': {
      const repair = rows.find((r) => r.action === 'repair' && r.detail?.job_id === d.job_id);
      const change = repair ? loggedChange(repair.detail) : null;
      return change ? `${who} accepted the repair for ${describe(change)}.` : `${who} accepted a repair.`;
    }
    case 'clear_changes': {
      const n = Number(d.cleared ?? 0);
      return `${who} cleared ${n} accepted change${n === 1 ? '' : 's'}; later timetables no longer include them.`;
    }
    default:
      return `${who}: ${auditActionLabel(entry.action)}.`;
  }
}
