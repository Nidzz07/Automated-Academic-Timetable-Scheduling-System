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
import { RepairPanel, RepairProposal } from '@/components/timetable/RepairPanel';
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
  DAY_NAMES,
  entityName,
  facultyText,
  labelsFor,
} from '@/adapters/timetable';
import { AnomalyReport, PrintedBaseline } from '@/adapters/realInstance';
import {
  AuthSession,
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

interface AppProps {
  /** The API client; by default the one VITE_API_MODE picks */
  client?: MockChronosApiClient;
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

function SessionApp({ client, session }: { client: MockChronosApiClient; session: AuthSession | null }) {
  // One client per App mount, so every render (and every test) starts with an empty cache.
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      {session && (
        <div className="bg-background text-foreground">
          <div className="mx-auto flex max-w-7xl items-center justify-end gap-3 px-4 pt-4 text-xs sm:px-6 lg:px-8">
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

function TimetableApp({ client, session }: { client: MockChronosApiClient; session: AuthSession | null }) {
  // an account linked to a faculty member or cohort (D50) opens on the real timetable they are in
  const [instance, setInstance] = useState<EdgeListInstance>(
    session?.facultyId || session?.cohortId ? REAL_INSTANCE : 'example'
  );
  // The latest solve and repair job per instance, kept here so switching instance and back keeps tracking them
  const [solveJobs, setSolveJobs] = useState<Record<EdgeListInstance, string>>({});
  // The order this UI started its jobs in: a queued repair waits only for a job started before it
  const startOrder = useRef(new Map<string, number>());
  const onSolveStarted = useCallback((solved: EdgeListInstance, jobId: string) => {
    startOrder.current.set(jobId, startOrder.current.size);
    setSolveJobs((jobs) => ({ ...jobs, [solved]: jobId }));
  }, []);
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
  const instances = useInstancesQuery(client);
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
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
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
      onInstanceChange={setInstance}
      client={client}
      session={session}
      solveJobs={solveJobs}
      startOrder={startOrder.current}
      onSolveStarted={onSolveStarted}
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
            ? `Timetable payload failed ${error.schema} contract validation`
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
  client: MockChronosApiClient;
  /** Who is logged in (http mode): role and D50 link; null in static mode, where the RoleSelector picks the role */
  session: AuthSession | null;
  solveJobs: Record<EdgeListInstance, string>;
  /** The order this UI started its solve and repair jobs in, by job id */
  startOrder: ReadonlyMap<string, number>;
  onSolveStarted: (instance: EdgeListInstance, jobId: string) => void;
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
  client,
  session,
  solveJobs,
  startOrder,
  onSolveStarted,
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
  const shown = isExample ? solution : publishedSolution;
  // The printed view lays the printed timetable on the grid; the real instance compares with it
  const printed = instance === PRINTED_INSTANCE ? baseline : null;
  const solvable = instances.find((i) => i.id === instance)?.solvable ?? false;
  const labels = useMemo(() => labelsFor(display), [display]);

  // Repairs of a backend instance's official timetable (S14c; administrator and coordinator)
  const http = client instanceof HttpChronosApiClient ? client : null;
  const repair = useRepair(http, instance, repairJobId, onRepairStarted);
  const repairJob = repair.job.data;
  // The instance's solve, started before the repair and still queued or running, is what a queued repair waits for
  const solveJobId = http ? solveJobs[instance] ?? null : null;
  const solveJob = useJobQuery(http!, solveJobId, 1000).data;
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
  // one repair at a time: none while one runs or waits to be accepted or discarded
  const repairOpen =
    repair.start.isPending ||
    (repairJobId !== null && !isFinished(repairJob?.status)) ||
    (repairJob?.status === 'solved' && !repairJob.accepted_at);
  const startRepair = (change: RepairChange) => {
    setRejectionAlert(null);
    repair.accept.reset();
    repair.start.mutate(change);
  };
  const discardRepair = () => {
    repair.accept.reset();
    onRepairDiscarded(instance);
  };
  // The mock validates moves against the example edge list only; a backend instance's moves are repairs
  const canDrag =
    caps.canDragAndDrop &&
    (isExample || (canRepair && !!publishedSolution && isSolvedSolution(publishedSolution) && !repairOpen));

  // Helper to toggle between solved timetable and infeasible diagnosis
  const handleToggleOutcome = async () => {
    client.setSimulatedOutcome(isSolvedSolution(solution) ? 'infeasible' : 'solved');
    await queryClient.refetchQueries({ queryKey: timetableQueryKey });
    setRejectionAlert(null);
  };

  // Helper to toggle rejection simulation
  const handleToggleRejectMode = () => {
    setRejectMoveMode((prev) => {
      const next = !prev;
      client.setRejectMode(
        next,
        next
          ? 'Mock Backend Rejection: Target slot causes faculty overlap and violates room capacity.'
          : undefined
      );
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
    const options = new Map(
      allSessions.map((s) => [s.facultyId, s.facultyInitials ? `${s.facultyName} (${s.facultyInitials})` : s.facultyName])
    );
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
  const workloadSessions = useMemo(
    () => (printed ? facultySessions : officialSessions.filter((s) => s.facultyId === selectedFaculty)),
    [printed, facultySessions, officialSessions, selectedFaculty]
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
        startRepair(change);
      } else {
        setRejectionAlert({
          reason: check.heading,
          clashes: check.clashes.map((c) => c.text),
          sessionId: entityName(sessionId, edgeList, labels),
          originalSlotLabel: `${DAY_NAMES[from.day]} P${from.wallClockPeriod}`,
          onRepair: () => startRepair(change),
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
    const originalSlotLabel = `${DAY_NAMES[originalDay]} P${originalPeriod}`;
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
          sessionId,
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
        sessionId,
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
      <div className="mx-auto max-w-7xl px-4 py-8 space-y-5 sm:px-6 lg:px-8">
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
          showQualityCard={showQualityCard}
          onToggleQualityCard={() => setShowQualityCard((prev) => !prev)}
          darkMode={darkMode}
          onToggleDarkMode={toggleDarkMode}
          currentRole={currentRole}
          solutionStatus={printed ? 'printed' : shown?.status ?? null}
          onToggleOutcome={isExample ? handleToggleOutcome : undefined}
          rejectMoveMode={rejectMoveMode}
          onToggleRejectMode={handleToggleRejectMode}
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

        {/* Rejection Alert Banner (when an optimistic move is rejected) */}
        {rejectionAlert && (
          <RejectionAlert
            reason={rejectionAlert.reason}
            clashes={rejectionAlert.clashes}
            sessionId={rejectionAlert.sessionId}
            originalSlotLabel={rejectionAlert.originalSlotLabel}
            onDismiss={() => setRejectionAlert(null)}
            onRepair={rejectionAlert.onRepair}
          />
        )}

        {/* Solve on the backend (administrator and coordinator; backend instances only) */}
        {caps.canSolve && solvable && client instanceof HttpChronosApiClient && (
          <SolvePanel
            key={`solve-${instance}`}
            client={client}
            instance={instance}
            jobId={solveJobs[instance] ?? null}
            onJobStarted={onSolveStarted}
          />
        )}

        {/* Repair the official timetable (administrator and coordinator; backend instances only) */}
        {canRepair && (
          <RepairPanel
            key={`repair-${instance}`}
            repair={repair}
            jobId={repairJobId}
            proposal={proposal}
            edgeList={repairEdgeList ?? edgeList}
            labels={labels}
            workload={proposalWorkload}
            waitingFor={waitingFor}
            onDiscard={discardRepair}
          />
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
          />
        )}

        {/* Faculty Workload View (Visible only to Faculty Role) */}
        {currentRole === 'faculty' && quality && (
          <FacultyWorkloadCard
            facultyInitials={
              workloadSessions[0]?.facultyInitials ||
              workloadSessions[0]?.facultyName ||
              (selectedFaculty ? labels.faculty(selectedFaculty).initials || labels.faculty(selectedFaculty).name : '')
            }
            facultySessions={workloadSessions}
            loadRule={quality.rules.find((r) => r.rule_id === 'S-LOAD16')}
          />
        )}

        {/* Infeasible Diagnosis Panel (When solver outcome is infeasible) */}
        {shown && isInfeasibleSolution(shown) && (
          <InfeasibilityDiagnosisPanel
            infeasibleSolution={shown}
            edgeList={edgeList}
            labels={labels}
            onApplyRelaxation={isExample ? handleToggleOutcome : undefined}
            onSwitchToSolved={isExample ? handleToggleOutcome : undefined}
          />
        )}

        {/* Quality Score & Rules Breakdown (Admin / Coordinator only) */}
        {shown && caps.showQualityScore && isSolvedSolution(shown) && showQualityCard && (
          <QualityScoreCard
            quality={toQualityView(shown)}
            metadata={shown.metadata}
          />
        )}

        {/* The real instance's generated timetable beside the printed one */}
        {baseline && !printed && shown && caps.showQualityScore && isSolvedSolution(shown) && (
          <GeneratedVsPrintedCard generated={toQualityView(shown)} printed={baseline} />
        )}

        {/* The printed timetable: its violations and score (not a solver output) */}
        {printed && caps.showQualityScore && (
          <section className="grid gap-5 lg:grid-cols-2">
            <PrintedViolationsPanel
              violations={printed.violations}
              selected={selectedViolation}
              onSelect={setSelectedViolation}
            />
            <QualityScoreCard quality={printed.quality} title="Printed timetable quality" />
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
          <main className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
              <span className="font-semibold text-foreground">
                Weekly Timetable Schedule ({edgeList.slot_grid.teaching_periods.length} Teaching Periods ·{' '}
                {edgeList.slot_grid.days} Days) — {caps.title} View
              </span>
              <span className="font-mono text-[11px]">
                {canDrag ? 'Interactive: Drag Sessions to Reschedule' : 'Read-Only Schedule'}
              </span>
            </div>

            {proposal && (
              <p data-testid="proposal-note" className="px-1 text-xs font-medium text-amber-700 dark:text-amber-300">
                Proposed repair: the sessions it changes are outlined in amber. Not official until accepted.
              </p>
            )}

            {!shown && !printed && (
              <p data-testid="no-solution-note" className="px-1 text-xs text-muted-foreground">
                Not solved yet. No solution is published for this instance; the grid shows its
                periods, breaks and pinned occupancy only.
              </p>
            )}

            <TimetableGrid
              edgeList={edgeList}
              solution={roleFilteredSolution}
              labels={labels}
              cohortFilter={effectiveCohortFilter}
              showPinnedBlocks={currentRole !== 'faculty'}
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
        {currentRole === 'administrator' && client instanceof HttpChronosApiClient && <AuditLog client={client} />}

        {/* Session Details Modal */}
        <SessionDetailModal
          session={isModalOpen ? selectedSession : null}
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
        <footer className="border-t border-border/60 pt-6 text-center text-xs text-muted-foreground space-y-1.5">
          <p className="font-semibold text-foreground">
            Chronos Timetable Scheduling System · Sardar Patel Institute of Technology
          </p>
          <p>
            Track C (Frontend & Validation) — Phase 2: Role-Differentiated Views, Mock API & dnd-kit Drag-and-Drop.
          </p>
          <p className="text-[11px] font-mono text-muted-foreground/80">
            Validated against Frozen Contract 3 (solution_v1 / solution_v2 schemas) · Hand-written deterministic solver integration
          </p>
        </footer>
      </div>
    </div>
  );
}

export default App;
