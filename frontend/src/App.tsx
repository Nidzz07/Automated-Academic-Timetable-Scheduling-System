import { useCallback, useRef, useState, useMemo, useSyncExternalStore } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient } from '@tanstack/react-query';
import { TimetableGrid } from '@/components/timetable/TimetableGrid';
import { TimetableHeader } from '@/components/timetable/TimetableHeader';
import { QualityScoreCard } from '@/components/timetable/QualityScoreCard';
import { SessionDetailModal } from '@/components/timetable/SessionDetailModal';
import { RoleSelector } from '@/components/timetable/RoleSelector';
import { FacultyWorkloadCard } from '@/components/timetable/FacultyWorkloadCard';
import { InfeasibilityDiagnosisPanel } from '@/components/timetable/InfeasibilityDiagnosisPanel';
import { RejectionAlert } from '@/components/timetable/RejectionAlert';
import { FreeRoomsPanel, RoomTimetable } from '@/components/timetable/RoomViews';
import { FacultyAtSlotPanel } from '@/components/timetable/FacultyAtSlotPanel';
import { AnomalyReportPanel } from '@/components/timetable/AnomalyReport';
import { PrintedViolationsPanel } from '@/components/timetable/PrintedViolations';
import { SolvePanel } from '@/components/timetable/SolvePanel';
import type { JobClocks } from '@/components/timetable/JobProgress';
import { RepairPanel, RepairPrefill, RepairProposal } from '@/components/timetable/RepairPanel';
import { AcceptedChangesPanel } from '@/components/timetable/AcceptedChangesPanel';
import { SubstitutePanel } from '@/components/timetable/SubstitutePanel';
import { GeneratedVsPrintedCard } from '@/components/timetable/GeneratedVsPrintedCard';
import { LoginScreen } from '@/components/auth/LoginScreen';
import { AuditLog } from '@/components/auth/AuditLog';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { UserRole, ROLE_CAPABILITIES } from '@/types/roles';
import {
  SolutionContract,
  SolvedSolution,
  SessionAssignment,
  isSolvedSolution,
  isInfeasibleSolution,
  toQualityView,
  DayIndex,
  repairChanges,
} from '@/adapters/solution';
import {
  buildEnrichedSessions,
  checkMove,
  cohortOptions,
  Display,
  EdgeList,
  EnrichedSession,
  entityName,
  facultyLoad,
  facultyText,
  hardRuleViolations,
  labelsFor,
  sessionTeacher,
  slotText,
} from '@/adapters/timetable';
import { AnomalyReport, PrintedBaseline } from '@/adapters/realInstance';
import {
  AuthSession,
  ChronosApiClient,
  chronosApiClient,
  EdgeListInstance,
  getAuthState,
  HttpChronosApiClient,
  InstanceOption,
  isFinished,
  MockChronosApiClient,
  PRINTED_INSTANCE,
  REAL_INSTANCE,
  RepairChange,
  setSession,
  storedInstance,
  storeInstance,
  subscribeAuth,
} from '@/api/chronosApi';
import { ContractValidationError } from '@/api/contractError';
import {
  timetableQueryKey,
  useAnomaliesQuery,
  useCurrentEdgeListQuery,
  useDisplayQuery,
  useEdgeListQuery,
  useInstanceSolutionQuery,
  useInstancesQuery,
  useJobQuery,
  useMoveSessionMutation,
  usePrintedBaselineQuery,
  useRepair,
  useTimetableQuery,
} from '@/api/queries';
import { SKIP_PAST_TIMETABLE, SKIP_TO_TIMETABLE, UI, contractFailedText, gridHint } from '@/lib/wording';

interface AppProps {
  /** The API client; by default the one VITE_API_MODE picks */
  client?: ChronosApiClient;
}

export function App({ client = chronosApiClient }: AppProps) {
  const auth = useSyncExternalStore(subscribeAuth, getAuthState);
  // http mode needs a login; static (demo) mode picks its role in the RoleSelector
  const session = client instanceof HttpChronosApiClient ? auth.session : null;
  if (client instanceof HttpChronosApiClient && !session) {
    return <LoginScreen client={client} expired={auth.expired} />;
  }
  // keyed by the token: a new login starts with an empty cache and no jobs of the last user
  return <SessionApp key={session?.token ?? 'static'} client={client} session={session} />;
}

const SKIP_LINK =
  'sr-only rounded-md bg-primary font-semibold text-primary-foreground focus:not-sr-only focus:inline-block focus:px-3 focus:py-2';
// shown over the page when focused, so the page does not jump under it
const SKIP_TO_GRID_LINK = `${SKIP_LINK} focus:absolute focus:left-4 focus:top-2 focus:z-50`;

function SessionApp({ client, session }: { client: ChronosApiClient; session: AuthSession | null }) {
  // One client per App mount, so every render (and every test) starts with an empty cache.
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      {/* The first tab stop, before Log out: the grid is far down the page, past the panels */}
      <a href="#timetable" data-testid="skip-to-timetable" className={SKIP_TO_GRID_LINK}>
        {SKIP_TO_TIMETABLE}
      </a>
      {session && (
        <div className="bg-background text-foreground">
          <div className="flex w-full items-center justify-end gap-3 px-4 pt-4 lg:px-6">
            <span data-testid="signed-in-as">
              Signed in as <span className="font-semibold">{session.username}</span> ({ROLE_CAPABILITIES[session.role].title})
            </span>
            <Button variant="outline" size="sm" onClick={() => setSession(null)} data-testid="logout-button">
              Log out
            </Button>
          </div>
        </div>
      )}
      <TimetableApp client={client} session={session} />
    </QueryClientProvider>
  );
}

/** D50: a faculty or student login linked to one teacher or cohort is locked to it, on the real timetable. */
const isLinked = (session: AuthSession | null) =>
  (session?.role === 'faculty' && !!session.facultyId) || (session?.role === 'student' && !!session.cohortId);

function TimetableApp({ client, session }: { client: ChronosApiClient; session: AuthSession | null }) {
  // A login (http mode) opens on the real timetable, or the instance it last picked (kept across a
  // reload); static mode opens on the bundled example; a linked account stays on the real timetable
  const linked = isLinked(session);
  const [instanceChoice, setInstanceChoice] = useState<EdgeListInstance>(() =>
    linked ? REAL_INSTANCE : session ? storedInstance() ?? REAL_INSTANCE : 'example'
  );
  const instances = useInstancesQuery(client);
  // An instance the backend does not offer (any more) falls back to the first it can solve
  const instance = useMemo(() => {
    const offered = instances.data;
    if (!offered || offered.some((i) => i.id === instanceChoice)) return instanceChoice;
    return offered.find((i) => i.solvable)?.id ?? offered[0]?.id ?? instanceChoice;
  }, [instances.data, instanceChoice]);
  const onInstanceChange = useCallback(
    (next: EdgeListInstance) => {
      setInstanceChoice(next);
      if (session) storeInstance(next);
    },
    [session]
  );
  // The latest solve and repair job per instance, kept here so switching instance and back keeps tracking them
  const [solveJobs, setSolveJobs] = useState<Record<EdgeListInstance, string>>({});
  // The order this UI started its jobs in: a queued repair waits only for a job started before it
  const startOrder = useRef(new Map<string, number>());
  const onSolveStarted = useCallback((solved: EdgeListInstance, jobId: string) => {
    startOrder.current.set(jobId, startOrder.current.size);
    setSolveJobs((jobs) => ({ ...jobs, [solved]: jobId }));
  }, []);
  const onSolveDiscarded = useCallback(
    (solved: EdgeListInstance) => setSolveJobs(({ [solved]: _discarded, ...jobs }) => jobs),
    []
  );
  // When each job started: the panels counting its seconds unmount on a switch of instance, this does not
  const jobClocks = useRef<JobClocks>(new Map());
  // The solves already applied: the workspace and its SolvePanel unmount on a switch of instance, this does not
  const appliedSolves = useRef(new Set<string>());
  const [repairJobs, setRepairJobs] = useState<Record<EdgeListInstance, string>>({});
  const onRepairStarted = useCallback((repaired: EdgeListInstance, jobId: string) => {
    startOrder.current.set(jobId, startOrder.current.size);
    setRepairJobs((jobs) => ({ ...jobs, [repaired]: jobId }));
  }, []);
  const onRepairDiscarded = useCallback(
    (repaired: EdgeListInstance) =>
      setRepairJobs(({ [repaired]: _discarded, ...jobs }) => jobs),
    []
  );
  const timetable = useTimetableQuery(client);
  const edgeList = useEdgeListQuery(instance, client);
  const currentEdgeList = useCurrentEdgeListQuery(instance, client);
  const display = useDisplayQuery(instance, client);
  const published = useInstanceSolutionQuery(instance, client);
  const anomalies = useAnomaliesQuery(instance, client);
  const printed = usePrintedBaselineQuery(instance, client);
  const queries = [instances, timetable, edgeList, currentEdgeList, display, published, anomalies, printed];

  if (
    instances.status !== 'success' ||
    timetable.status !== 'success' ||
    edgeList.status !== 'success' ||
    currentEdgeList.status !== 'success' ||
    display.status !== 'success' ||
    published.status !== 'success' ||
    anomalies.status !== 'success' ||
    printed.status !== 'success'
  ) {
    const error = queries.find((q) => q.error)?.error;
    return (
      <div className="min-h-screen bg-background text-foreground">
        <div className="w-full px-4 py-8 lg:px-6">
          {error ? (
            <TimetableLoadError
              error={error}
              onRetry={() => queries.forEach((q) => q.refetch())}
            />
          ) : (
            <Card role="status" data-testid="timetable-loading">
              <CardHeader>
                <CardTitle>Loading timetable…</CardTitle>
              </CardHeader>
            </Card>
          )}
        </div>
      </div>
    );
  }

  return (
    <TimetableWorkspace
      solution={timetable.data}
      edgeList={currentEdgeList.data}
      committedEdgeList={edgeList.data}
      display={display.data}
      publishedSolution={published.data}
      anomalies={anomalies.data}
      baseline={printed.data}
      instances={instances.data}
      instance={instance}
      onInstanceChange={onInstanceChange}
      instanceLocked={linked}
      client={client}
      session={session}
      solveJobs={solveJobs}
      startOrder={startOrder.current}
      appliedSolves={appliedSolves.current}
      onSolveStarted={onSolveStarted}
      onSolveDiscarded={onSolveDiscarded}
      jobClocks={jobClocks.current}
      repairJobId={repairJobs[instance] ?? null}
      onRepairStarted={onRepairStarted}
      onRepairDiscarded={onRepairDiscarded}
    />
  );
}

function TimetableLoadError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const isContractError = error instanceof ContractValidationError;
  return (
    <Card role="alert" data-testid="timetable-error" className="border-destructive/50">
      <CardHeader>
        <CardTitle>
          {isContractError
            ? contractFailedText(error.schema)
            : 'Could not load the timetable'}
        </CardTitle>
        {!isContractError && <CardDescription>{error.message}</CardDescription>}
      </CardHeader>
      <CardContent className="space-y-3">
        {isContractError && (
          <ul className="list-disc pl-5 font-mono text-xs" data-testid="contract-issues">
            {error.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        )}
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </CardContent>
    </Card>
  );
}

interface TimetableWorkspaceProps {
  solution: SolutionContract;
  /** The edge list with every accepted change (http mode, D52): absences, room closures, substitutions */
  edgeList: EdgeList;
  /** The committed edge list, as ingestion wrote it (the anomaly report's ids) */
  committedEdgeList: EdgeList;
  /** D41 display sidecar; null for the contract examples */
  display: Display | null;
  /** The solution published beside a non-example instance's edge list; null when not solved yet */
  publishedSolution: SolutionContract | null;
  /** The instance's ingestion anomaly report; null for the contract examples */
  anomalies: AnomalyReport | null;
  /** The timetable as printed (the real instance and its printed view); not a solution contract */
  baseline: PrintedBaseline | null;
  instances: InstanceOption[];
  instance: EdgeListInstance;
  onInstanceChange: (instance: EdgeListInstance) => void;
  /** The account is linked to one teacher or class (D50) */
  instanceLocked: boolean;
  client: ChronosApiClient;
  /** Who is logged in (http mode): role and D50 link; null in static mode, where the RoleSelector picks the role */
  session: AuthSession | null;
  solveJobs: Record<EdgeListInstance, string>;
  /** The order this UI started its solve and repair jobs in, by job id */
  startOrder: ReadonlyMap<string, number>;
  /** The solve jobs whose result was already written to the query cache */
  appliedSolves: Set<string>;
  onSolveStarted: (instance: EdgeListInstance, jobId: string) => void;
  onSolveDiscarded: (instance: EdgeListInstance) => void;
  jobClocks: JobClocks;
  /** The instance's latest repair job, until accepted-and-shown or discarded */
  repairJobId: string | null;
  onRepairStarted: (instance: EdgeListInstance, jobId: string) => void;
  onRepairDiscarded: (instance: EdgeListInstance) => void;
}

function TimetableWorkspace({
  solution,
  edgeList: currentEdgeList,
  committedEdgeList,
  display,
  publishedSolution,
  anomalies,
  baseline,
  instances,
  instance,
  onInstanceChange,
  instanceLocked,
  client,
  session,
  solveJobs,
  startOrder,
  appliedSolves,
  onSolveStarted,
  onSolveDiscarded,
  jobClocks,
  repairJobId,
  onRepairStarted,
  onRepairDiscarded,
}: TimetableWorkspaceProps) {
  const sessionRole = session?.role ?? null;
  const [darkMode, setDarkMode] = useState<boolean>(false);
  const [roleChoice, setCurrentRole] = useState<UserRole>('administrator');
  const currentRole = sessionRole ?? roleChoice;
  // Persona choices default to the first option the payload offers
  const [facultyChoice, setSelectedFaculty] = useState<string | null>(null);
  const [studentChoice, setSelectedStudentDivision] = useState<string | null>(null);
  const [cohortFilter, setCohortFilter] = useState<string>('all');
  const [showQualityCard, setShowQualityCard] = useState<boolean>(true);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [selectedViolation, setSelectedViolation] = useState<number | null>(null);
  // The session whose substitutes are listed, per instance
  const [substituteFor, setSubstituteFor] = useState<{ instance: EdgeListInstance; sessionId: string } | null>(null);
  // The substitute finder's way out: the repair form filled in with the teacher and the session's periods
  const [repairPrefill, setRepairPrefill] = useState<RepairPrefill | null>(null);

  // The query cache holds the solution; optimistic moves and reverts write straight into it
  const queryClient = useQueryClient();
  const moveSession = useMoveSessionMutation(client);
  const setSolution = (next: SolutionContract) => queryClient.setQueryData(timetableQueryKey, next);

  // Track provisional session ID during optimistic move validation
  const [provisionalSessionId, setProvisionalSessionId] = useState<string | null>(null);

  // Surface readable rejection message from mock backend
  const [rejectionAlert, setRejectionAlert] = useState<{
    reason: string;
    /** Every clash at the target of a drag on a backend instance */
    clashes?: string[];
    sessionId?: string;
    originalSlotLabel?: string;
    onRepair?: () => void;
  } | null>(null);

  // Toggle for testing rejection on move
  const [rejectMoveMode, setRejectMoveMode] = useState<boolean>(false);

  const caps = ROLE_CAPABILITIES[currentRole];

  // The solution examples were solved for the example instance; other instances show their own
  // published solution, or none (Not solved yet)
  const isExample = instance === 'example';
  // "Simulate Infeasible" and "Test Revert on Move" act on the mock's example: static mode only
  const mock = client instanceof MockChronosApiClient ? client : null;
  const testControls = isExample && !!mock;
  const shown = isExample ? solution : publishedSolution;
  // The printed view lays the printed timetable on the grid; the real instance compares with it
  const printed = instance === PRINTED_INSTANCE ? baseline : null;
  const solvable = instances.find((i) => i.id === instance)?.solvable ?? false;
  const labels = useMemo(() => labelsFor(display), [display]);
  // the solver's quality explanations name faculty and cohorts by id; display.json names them
  const nameOf = useMemo(
    () =>
      display
        ? (id: string) => (display.faculty[id] ? facultyText(labels, id) : display.cohorts[id] ? labels.cohort(id) : null)
        : undefined,
    [display, labels]
  );

  // Repairs of a backend instance's official timetable (S14c; administrator and coordinator)
  const http = client instanceof HttpChronosApiClient ? client : null;
  const solveJobId = http ? solveJobs[instance] ?? null : null;
  const solveJob = useJobQuery(http!, solveJobId, 1000).data;
  // What an ended Generate said ("Done: the grid ... show the new timetable") holds only until the official timetable changes otherwise
  const forgetEndedSolve = () => {
    if (isFinished(solveJob?.status)) onSolveDiscarded(instance);
  };
  const repair = useRepair(http, instance, repairJobId, onRepairStarted, 1000, forgetEndedSolve);
  const repairJob = repair.job.data;
  // The instance's solve, started before the repair and still queued or running, is what a queued repair waits for
  const solveFirst =
    solveJobId !== null && repairJobId !== null && (startOrder.get(solveJobId) ?? 0) < (startOrder.get(repairJobId) ?? 0);
  const waitingFor = solveFirst && solveJob && !isFinished(solveJob.status) ? 'the solve of this instance' : null;
  const repairBase = repair.base.data;
  // The edge list the repair ran on (GET /jobs/{id}/edge-list): the accepted changes it was built with and its own
  const repairEdgeList = repair.edgeList.data;
  const proposal = useMemo<RepairProposal | null>(() => {
    const result = repairJob?.solution;
    if (repairJob?.status !== 'solved' || repairJob.accepted_at || !result || !repairBase || !repairEdgeList) return null;
    if (!isSolvedSolution(result) || !isSolvedSolution(repairBase)) return null;
    return { base: repairBase, result, changes: repairChanges(repairBase, result) };
  }, [repairJob, repairBase, repairEdgeList]);
  // A proposal is shown on the edge list it was made for; otherwise the grid, details, faculty view and
  // drop pre-check use the current one, so accepted absences, closures and substitutions are in them
  const edgeList = proposal && repairEdgeList ? repairEdgeList : currentEdgeList;
  const canRepair = caps.canSolve && solvable && http !== null;
  // one repair at a time: none while one runs or waits to be accepted or discarded (a job that can no longer be read does neither)
  const repairOpen =
    repair.start.isPending ||
    (repairJobId !== null && !repair.job.error && !isFinished(repairJob?.status)) ||
    (repairJob?.status === 'solved' && !repairJob.accepted_at);
  const startRepair = (change: RepairChange) => {
    setRejectionAlert(null);
    repair.accept.reset();
    // the ended repair goes, so its message and diagnosis never stand beside the new one's outcome
    onRepairDiscarded(instance);
    repair.start.mutate(change);
  };
  // Forget the job and what started it: the panel is back at its start, whatever way the repair ended
  const discardRepair = () => {
    repair.start.reset();
    repair.accept.reset();
    onRepairDiscarded(instance);
  };
  // "Accepted: ... now the official one" holds only until the official timetable changes again
  const forgetAcceptedRepair = () => {
    if (repairJob?.accepted_at) discardRepair();
  };
  // A repair started from the grid reports in the repair panel, far above where the drop happened
  const repairPanelRef = useRef<HTMLDivElement>(null);
  const startRepairFromGrid = (change: RepairChange) => {
    startRepair(change);
    repairPanelRef.current?.scrollIntoView?.({ block: 'start' });
  };
  // The mock validates moves against the example edge list only; a backend instance's moves are repairs
  const canDrag =
    caps.canDragAndDrop &&
    (isExample || (canRepair && !!publishedSolution && isSolvedSolution(publishedSolution) && !repairOpen));

  // Helper to toggle between solved timetable and infeasible diagnosis
  const handleToggleOutcome = async () => {
    mock?.setSimulatedOutcome(isSolvedSolution(solution) ? 'infeasible' : 'solved');
    await queryClient.refetchQueries({ queryKey: timetableQueryKey });
    setRejectionAlert(null);
  };

  // Helper to toggle rejection simulation
  const handleToggleRejectMode = () => {
    setRejectMoveMode((prev) => {
      const next = !prev;
      mock?.setRejectMode(next, next ? UI.trialRefusal : undefined);
      return next;
    });
  };

  // Placements on the grid: the printed timetable, a proposed repair, else the solved solution's
  const placed = useMemo<SessionAssignment[] | null>(
    () =>
      printed?.assignment ?? proposal?.result.assignment ?? (shown && isSolvedSolution(shown) ? shown.assignment : null),
    [printed, proposal, shown]
  );
  const quality = useMemo(
    () => printed?.quality ?? (shown && isSolvedSolution(shown) ? toQualityView(shown) : null),
    [printed, shown]
  );
  // The printed timetable's violating sessions: the picked violation's, else every one
  const flaggedSessionIds = useMemo(() => {
    if (proposal) {
      const substituted = repairJob?.change?.kind === 'substitute_faculty' ? [repairJob.change.session_id] : [];
      return new Set([...proposal.changes.map((c) => c.sessionId), ...substituted]);
    }
    if (!printed) return undefined;
    const picked = selectedViolation === null ? undefined : printed.violations[selectedViolation];
    return new Set((picked ? [picked] : printed.violations).flatMap((v) => v.session_ids));
  }, [printed, selectedViolation, proposal, repairJob]);

  // Enriched sessions if solved (or printed)
  const allSessions = useMemo(
    () => (placed ? buildEnrichedSessions(placed, edgeList, labels) : []),
    [placed, edgeList, labels]
  );

  // The official timetable on the current edge list (the accepted changes in force, D52, D56), never a
  // proposal: the faculty workload view, the loads before a substitution and the free/engaged view read it
  const officialSessions = useMemo(
    () => (shown && isSolvedSolution(shown) ? buildEnrichedSessions(shown.assignment, currentEdgeList, labels) : []),
    [shown, currentEdgeList, labels]
  );
  // A proposal's loads: before on the official timetable, after on the proposal and the job's edge list
  const proposalWorkload = useMemo(
    () => (proposal ? { before: officialSessions, after: allSessions } : undefined),
    [proposal, officialSessions, allSessions]
  );

  // Selected session lookup
  const selectedSession = useMemo<EnrichedSession | null>(() => {
    if (!selectedSessionId || !allSessions.length) return null;
    return allSessions.find((s) => s.sessionId === selectedSessionId) ?? null;
  }, [selectedSessionId, allSessions]);

  // D50: a faculty or student login linked to a teacher or cohort is locked to it
  const lockedFaculty = sessionRole === 'faculty' ? session?.facultyId ?? null : null;
  const lockedCohort = sessionRole === 'student' ? session?.cohortId ?? null : null;
  const facultyOptions = useMemo(() => {
    const options = new Map(allSessions.map((s) => [s.facultyId, sessionTeacher(s)]));
    // a linked teacher with no placed session is still the one shown
    if (lockedFaculty && !options.has(lockedFaculty)) options.set(lockedFaculty, facultyText(labels, lockedFaculty));
    return [...options].map(([id, label]) => ({ id, label })).sort((a, b) => a.label.localeCompare(b.label));
  }, [allSessions, lockedFaculty, labels]);
  const cohorts = useMemo(() => {
    const options = cohortOptions(edgeList, labels);
    return lockedCohort && !options.some((c) => c.id === lockedCohort)
      ? [...options, { id: lockedCohort, label: labels.cohort(lockedCohort) }]
      : options;
  }, [edgeList, labels, lockedCohort]);
  // A choice made on another instance falls back to this instance's first option
  const hasCohort = (id: string | null) => cohorts.some((c) => c.id === id);
  const selectedFaculty =
    lockedFaculty ??
    (facultyChoice !== null && facultyOptions.some((f) => f.id === facultyChoice)
      ? facultyChoice
      : facultyOptions[0]?.id ?? '');
  const selectedStudentDivision =
    lockedCohort ?? (studentChoice !== null && hasCohort(studentChoice) ? studentChoice : cohorts[0]?.id ?? 'all');
  const selectedCohortFilter = hasCohort(cohortFilter) ? cohortFilter : 'all';

  // Compute sessions for selected faculty (for faculty role view)
  const facultySessions = useMemo(() => {
    if (!allSessions.length) return [];
    return allSessions.filter((s) => s.facultyId === selectedFaculty);
  }, [allSessions, selectedFaculty]);
  // The workload view counts the printed timetable on the printed view, else the official one
  const workload = useMemo(
    () => facultyLoad(selectedFaculty, printed ? facultySessions : officialSessions, printed ? edgeList : currentEdgeList),
    [printed, facultySessions, officialSessions, selectedFaculty, edgeList, currentEdgeList]
  );

  // Determine effective cohort filter based on role
  const effectiveCohortFilter = useMemo(() => {
    if (currentRole === 'student') {
      return selectedStudentDivision;
    }
    if (currentRole === 'faculty') {
      return 'all'; // handled by session filtering or pass-through
    }
    return selectedCohortFilter;
  }, [currentRole, selectedStudentDivision, selectedCohortFilter]);

  // If role is faculty, derive the placements showing only this faculty's sessions
  const roleFilteredSolution = useMemo(() => {
    if (!placed) return null;
    if (currentRole !== 'faculty') return { assignment: placed };

    // Filter assignments to only those belonging to the selected faculty
    const facultySessionIds = new Set(facultySessions.map((s) => s.sessionId));
    return { assignment: placed.filter((a) => facultySessionIds.has(a.session_id)) };
  }, [placed, currentRole, facultySessions]);

  /**
   * Optimistic drag-and-drop handler with clean revert-on-reject.
   * Restores exact prior state including the session's original slot and UI selection.
   */
  const handleMoveSession = async (sessionId: string, targetDay: DayIndex, targetPeriod: number) => {
    // Only drag-enabled roles may move sessions
    if (!canDrag) {
      return;
    }

    // A backend instance: a clean move is posted as a repair; a clashing one offers to repair around it
    if (!isExample) {
      const from = allSessions.find((s) => s.sessionId === sessionId);
      if (!from || (from.day === targetDay && from.wallClockPeriod === targetPeriod)) return;
      const change: RepairChange = {
        kind: 'move_session',
        session_id: sessionId,
        day: targetDay,
        period: targetPeriod,
        room_id: from.roomId,
        ...(from.subRoomId ? { sub_room_id: from.subRoomId } : {}),
      };
      const check = checkMove(edgeList, labels, allSessions, sessionId, targetDay, targetPeriod);
      if (check === null) {
        startRepairFromGrid(change);
      } else {
        setRejectionAlert({
          reason: check.heading,
          clashes: check.clashes.map((c) => c.text),
          sessionId: entityName(sessionId, edgeList, labels),
          originalSlotLabel: slotText(from.day, from.wallClockPeriod),
          onRepair: () => startRepairFromGrid(change),
        });
      }
      return;
    }

    if (!isSolvedSolution(solution)) {
      return;
    }

    const currentAssignment = solution.assignment.find((a) => a.session_id === sessionId);
    if (!currentAssignment) return;

    const originalDay = currentAssignment.day;
    const originalPeriod = currentAssignment.period;

    // If dropped on same slot, no-op
    if (originalDay === targetDay && originalPeriod === targetPeriod) {
      return;
    }

    // 1. CAPTURE EXACT PRIOR STATE
    const priorSolution: SolvedSolution = JSON.parse(JSON.stringify(solution));
    const priorSelectedSessionId = selectedSessionId;
    const originalSlotLabel = slotText(originalDay, originalPeriod);
    const targetWallClockPeriod = targetPeriod;

    // 2. APPLY PROVISIONALLY (OPTIMISTIC)
    setProvisionalSessionId(sessionId);
    setRejectionAlert(null);

    const optimisticAssignment = solution.assignment.map((a) => {
      if (a.session_id === sessionId) {
        return {
          ...a,
          day: targetDay,
          period: targetWallClockPeriod,
        };
      }
      return a;
    });

    setSolution({
      ...solution,
      assignment: optimisticAssignment,
    });
    // Selection state is explicitly retained

    // 3. CALL MOCK API CLIENT
    try {
      const result = await moveSession.mutateAsync({
        request: {
          sessionId,
          targetDay,
          targetWallClockPeriod,
        },
        current: priorSolution,
      });

      if (result.success && result.solution) {
        // Backend confirmed move
        setSolution(result.solution);
        setProvisionalSessionId(null);
      } else {
        // REVERT CLEANLY TO EXACT PRIOR STATE
        setSolution(priorSolution);
        setSelectedSessionId(priorSelectedSessionId);
        setProvisionalSessionId(null);

        // SURFACE READABLE REASON TO USER
        const reason =
          result.rejectionReason || 'Move rejected by solver constraint validation.';
        setRejectionAlert({
          reason,
          sessionId: entityName(sessionId, edgeList, labels),
          originalSlotLabel,
        });
      }
    } catch (err: unknown) {
      // Revert cleanly on exception
      setSolution(priorSolution);
      setSelectedSessionId(priorSelectedSessionId);
      setProvisionalSessionId(null);
      setRejectionAlert({
        reason: (err instanceof Error && err.message) || 'Network exception during move validation.',
        sessionId: entityName(sessionId, edgeList, labels),
        originalSlotLabel,
      });
    }
  };

  const toggleDarkMode = () => {
    setDarkMode((prev) => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      return next;
    });
  };

  return (
    <div
      className={`min-h-screen bg-background text-foreground transition-colors duration-200 ${
        darkMode ? 'dark' : ''
      }`}
    >
      <div className="w-full px-4 py-8 space-y-5 lg:px-6">
        {/* Header Toolbar */}
        <TimetableHeader
          cohortFilter={selectedCohortFilter}
          onCohortFilterChange={setCohortFilter}
          cohortOptions={cohorts}
          instanceOptions={instances}
          instance={instance}
          onInstanceChange={(next) => {
            setCohortFilter('all');
            setSelectedViolation(null);
            onInstanceChange(next);
          }}
          instanceLocked={instanceLocked}
          showQualityCard={showQualityCard}
          onToggleQualityCard={() => setShowQualityCard((prev) => !prev)}
          darkMode={darkMode}
          onToggleDarkMode={toggleDarkMode}
          currentRole={currentRole}
          solutionStatus={printed ? 'printed' : shown?.status ?? null}
          onToggleOutcome={testControls ? handleToggleOutcome : undefined}
          rejectMoveMode={rejectMoveMode}
          onToggleRejectMode={testControls ? handleToggleRejectMode : undefined}
        />

        {/* Four Role-Differentiated Views Selector */}
        <RoleSelector
          currentRole={currentRole}
          onRoleChange={sessionRole ? undefined : setCurrentRole}
          selectedFaculty={selectedFaculty}
          onFacultyChange={setSelectedFaculty}
          selectedStudentDivision={selectedStudentDivision}
          onStudentDivisionChange={setSelectedStudentDivision}
          facultyOptions={facultyOptions}
          cohortOptions={cohorts}
          personaLocked={!!(lockedFaculty || lockedCohort)}
        />

        {/* Solve on the backend (administrator and coordinator; backend instances only) */}
        {caps.canSolve && solvable && client instanceof HttpChronosApiClient && (
          <SolvePanel
            key={`solve-${instance}`}
            client={client}
            instance={instance}
            jobId={solveJobs[instance] ?? null}
            onJobStarted={onSolveStarted}
            onJobDiscarded={onSolveDiscarded}
            onOfficial={forgetAcceptedRepair}
            appliedSolves={appliedSolves}
            jobClocks={jobClocks}
          />
        )}

        {/* Repair the official timetable (administrator and coordinator; backend instances only) */}
        {canRepair && (
          <div ref={repairPanelRef} className="scroll-mt-2">
            <RepairPanel
              key={`repair-${instance}`}
              repair={repair}
              jobId={repairJobId}
              proposal={proposal}
              edgeList={repairEdgeList ?? edgeList}
              labels={labels}
              workload={proposalWorkload}
              waitingFor={waitingFor}
              official={officialSessions}
              prefill={repairPrefill}
              onStart={startRepair}
              onDiscard={discardRepair}
              jobClocks={jobClocks}
            />
          </div>
        )}
        {canRepair && http && substituteFor?.instance === instance && (
          <SubstitutePanel
            key={substituteFor.sessionId}
            client={http}
            instance={instance}
            sessionId={substituteFor.sessionId}
            edgeList={edgeList}
            labels={labels}
            disabled={repairOpen}
            onPick={(facultyId) => {
              startRepair({ kind: 'substitute_faculty', session_id: substituteFor.sessionId, faculty_id: facultyId });
              setSubstituteFor(null);
            }}
            onRepairInstead={(facultyId) => {
              const held = officialSessions.find((s) => s.sessionId === substituteFor.sessionId);
              setRepairPrefill({ facultyId, slots: held?.periods.map((period) => ({ day: held.day, period })) ?? [] });
              setSubstituteFor(null);
              repairPanelRef.current?.scrollIntoView?.({ block: 'start' });
            }}
            onClose={() => setSubstituteFor(null)}
          />
        )}
        {canRepair && http && (
          <AcceptedChangesPanel
            key={`changes-${instance}`}
            client={http}
            instance={instance}
            edgeList={edgeList}
            labels={labels}
            canClear={currentRole === 'administrator'}
            onCleared={() => {
              forgetAcceptedRepair();
              forgetEndedSolve();
            }}
          />
        )}

        {/* Faculty Workload View (Visible only to Faculty Role) */}
        {currentRole === 'faculty' && quality && (
          <FacultyWorkloadCard
            facultyName={labels.faculty(selectedFaculty).name}
            facultyInitials={labels.faculty(selectedFaculty).initials}
            load={workload}
            loadRule={quality.rules.find((r) => r.rule_id === 'S-LOAD16')}
          />
        )}

        {/* Infeasible Diagnosis Panel (When solver outcome is infeasible) */}
        {shown && isInfeasibleSolution(shown) && (
          <InfeasibilityDiagnosisPanel
            infeasibleSolution={shown}
            edgeList={edgeList}
            labels={labels}
            onApplyRelaxation={testControls ? handleToggleOutcome : undefined}
            onSwitchToSolved={testControls ? handleToggleOutcome : undefined}
          />
        )}

        {/* Quality Score & Rules Breakdown (Admin / Coordinator only) */}
        {shown && caps.showQualityScore && isSolvedSolution(shown) && showQualityCard && (
          <QualityScoreCard quality={toQualityView(shown)} metadata={shown.metadata} nameOf={nameOf} />
        )}

        {/* The real instance's generated timetable beside the printed one */}
        {baseline && !printed && shown && caps.showQualityScore && isSolvedSolution(shown) && (
          <GeneratedVsPrintedCard
            generated={toQualityView(shown)}
            generatedHard={hardRuleViolations(shown.assignment, currentEdgeList)}
            printed={baseline}
          />
        )}

        {/* The printed timetable: its violations and score (not a solver output) */}
        {printed && caps.showQualityScore && (
          <section className="grid gap-5 lg:grid-cols-2">
            <PrintedViolationsPanel
              violations={printed.violations}
              selected={selectedViolation}
              onSelect={setSelectedViolation}
            />
            <QualityScoreCard quality={printed.quality} title="Printed timetable quality" nameOf={nameOf} />
          </section>
        )}

        {/* Empty state: solver returned a solved timetable with no sessions */}
        {shown && isSolvedSolution(shown) && shown.assignment.length === 0 && (
          <Card data-testid="timetable-empty">
            <CardHeader>
              <CardTitle>No sessions scheduled</CardTitle>
              <CardDescription>The solver returned a timetable with no session placements.</CardDescription>
            </CardHeader>
          </Card>
        )}

        {/* Main Weekly Grid (the edge list's periods and days; rendered when solved) */}
        {(!shown || (isSolvedSolution(shown) && shown.assignment.length > 0 && roleFilteredSolution)) && (
          <main id="timetable" tabIndex={-1} className="scroll-mt-2 space-y-2 outline-none">
            {/* Every card in the grid is a tab stop: the all-divisions view has hundreds */}
            <a href="#after-timetable" data-testid="skip-past-timetable" className={SKIP_LINK}>
              {SKIP_PAST_TIMETABLE}
            </a>

            <div className="flex flex-wrap items-baseline justify-between gap-2 px-1">
              <h2 className="text-xl font-semibold">Weekly timetable</h2>
              <p className="text-xs">
                {edgeList.slot_grid.teaching_periods.length} teaching periods, {edgeList.slot_grid.days} days,{' '}
                {caps.title.toLowerCase()} view. {gridHint(canDrag)}
              </p>
            </div>

            {proposal && (
              <p data-testid="proposal-note" className="px-1 font-semibold text-amber-900 dark:text-amber-200">
                Proposed repair: the sessions it changes are outlined in amber. Not official until accepted.
              </p>
            )}

            {!shown && !printed && (
              <p data-testid="no-solution-note" className="px-1">
                {UI.noTimetableNote}
              </p>
            )}

            {/* A refused drop: stuck to the top of the window, so it shows wherever the grid is scrolled to */}
            {rejectionAlert && (
              <RejectionAlert
                key={`${rejectionAlert.reason}|${rejectionAlert.sessionId}`}
                reason={rejectionAlert.reason}
                clashes={rejectionAlert.clashes}
                sessionId={rejectionAlert.sessionId}
                originalSlotLabel={rejectionAlert.originalSlotLabel}
                onDismiss={() => setRejectionAlert(null)}
                onRepair={rejectionAlert.onRepair}
              />
            )}

            <TimetableGrid
              edgeList={edgeList}
              solution={roleFilteredSolution}
              labels={labels}
              cohortFilter={effectiveCohortFilter}
              pinsOfFaculty={currentRole === 'faculty' ? selectedFaculty : undefined}
              canDragAndDrop={canDrag}
              selectedSessionId={selectedSessionId}
              provisionalSessionId={provisionalSessionId}
              onSelectSession={(id) => {
                setSelectedSessionId(id);
                setIsModalOpen(true);
              }}
              onMoveSession={handleMoveSession}
              flaggedSessionIds={flaggedSessionIds}
              flagTone={proposal ? 'change' : 'violation'}
            />
          </main>
        )}
        <div id="after-timetable" tabIndex={-1} className="outline-none" />

        {/* Room timetable and free rooms (whole-department roles; ROADMAP D15) */}
        {caps.viewScope === 'all' && (!shown || isSolvedSolution(shown)) && (
          <section key={instance} className="grid gap-5 lg:grid-cols-2">
            <RoomTimetable edgeList={edgeList} sessions={allSessions} labels={labels} />
            <FreeRoomsPanel edgeList={edgeList} sessions={allSessions} labels={labels} />
          </section>
        )}

        {/* Free and engaged faculty at a slot (administrator and coordinator; the official timetable only) */}
        {caps.viewScope === 'all' && !printed && (
          <FacultyAtSlotPanel
            key={`at-slot-${instance}`}
            edgeList={currentEdgeList}
            sessions={officialSessions}
            labels={labels}
            solved={!!shown && isSolvedSolution(shown)}
          />
        )}

        {/* Ingestion anomaly report (whole-department roles); "no report" when the instance has none */}
        {caps.viewScope === 'all' && (
          <AnomalyReportPanel report={anomalies} display={display} edgeList={committedEdgeList} />
        )}

        {/* The audit log (administrator only; the backend refuses anyone else) */}
        {currentRole === 'administrator' && client instanceof HttpChronosApiClient && (
          <AuditLog client={client} edgeList={currentEdgeList} labels={labels} session={session} />
        )}

        {/* Session Details Modal */}
        <SessionDetailModal
          session={isModalOpen ? selectedSession : null}
          labels={labels}
          onClose={() => setIsModalOpen(false)}
          onFindSubstitute={
            canRepair && !repairOpen && selectedSession
              ? () => {
                  setSubstituteFor({ instance, sessionId: selectedSession.sessionId });
                  setIsModalOpen(false);
                }
              : undefined
          }
        />

        {/* Institutional Traceability Footer */}
        <footer className="border-t border-border pt-6 text-xs">
          <p className="font-semibold">Chronos timetable scheduling, Sardar Patel Institute of Technology</p>
          <p>{UI.footerNote}</p>
        </footer>
      </div>
    </div>
  );
}

export default App;
