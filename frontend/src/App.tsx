import { useState, useMemo } from 'react';
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
import { AnomalyReportPanel } from '@/components/timetable/AnomalyReport';
import { PrintedViolationsPanel } from '@/components/timetable/PrintedViolations';
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
} from '@/adapters/solution';
import {
  buildEnrichedSessions,
  cohortOptions,
  Display,
  EdgeList,
  EnrichedSession,
  DAY_NAMES,
  labelsFor,
} from '@/adapters/timetable';
import { AnomalyReport, PrintedBaseline } from '@/adapters/realInstance';
import { chronosApiClient, EdgeListInstance } from '@/api/chronosApi';
import { ContractValidationError } from '@/api/contractError';
import {
  timetableQueryKey,
  useAnomaliesQuery,
  useDisplayQuery,
  useEdgeListQuery,
  useInstanceSolutionQuery,
  useMoveSessionMutation,
  usePrintedBaselineQuery,
  useTimetableQuery,
} from '@/api/queries';

export function App() {
  // One client per App mount, so every render (and every test) starts with an empty cache.
  const [queryClient] = useState(() => new QueryClient());
  return (
    <QueryClientProvider client={queryClient}>
      <TimetableApp />
    </QueryClientProvider>
  );
}

function TimetableApp() {
  const [instance, setInstance] = useState<EdgeListInstance>('example');
  const timetable = useTimetableQuery();
  const edgeList = useEdgeListQuery(instance);
  const display = useDisplayQuery(instance);
  const published = useInstanceSolutionQuery(instance);
  const anomalies = useAnomaliesQuery(instance);
  const printed = usePrintedBaselineQuery(instance);
  const queries = [timetable, edgeList, display, published, anomalies, printed];

  if (
    timetable.status !== 'success' ||
    edgeList.status !== 'success' ||
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
      edgeList={edgeList.data}
      display={display.data}
      publishedSolution={published.data}
      anomalies={anomalies.data}
      printed={printed.data}
      instance={instance}
      onInstanceChange={setInstance}
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
  edgeList: EdgeList;
  /** D41 display sidecar; null for the contract examples */
  display: Display | null;
  /** The solution published beside a non-example instance's edge list; null when not solved yet */
  publishedSolution: SolutionContract | null;
  /** The instance's ingestion anomaly report; null for the contract examples */
  anomalies: AnomalyReport | null;
  /** The timetable as printed (the printed instance only); not a solution contract */
  printed: PrintedBaseline | null;
  instance: EdgeListInstance;
  onInstanceChange: (instance: EdgeListInstance) => void;
}

function TimetableWorkspace({
  solution,
  edgeList,
  display,
  publishedSolution,
  anomalies,
  printed,
  instance,
  onInstanceChange,
}: TimetableWorkspaceProps) {
  const [darkMode, setDarkMode] = useState<boolean>(false);
  const [currentRole, setCurrentRole] = useState<UserRole>('administrator');
  // Persona choices default to the first option the payload offers
  const [facultyChoice, setSelectedFaculty] = useState<string | null>(null);
  const [studentChoice, setSelectedStudentDivision] = useState<string | null>(null);
  const [cohortFilter, setCohortFilter] = useState<string>('all');
  const [showQualityCard, setShowQualityCard] = useState<boolean>(true);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [selectedViolation, setSelectedViolation] = useState<number | null>(null);

  // The query cache holds the solution; optimistic moves and reverts write straight into it
  const queryClient = useQueryClient();
  const moveSession = useMoveSessionMutation();
  const setSolution = (next: SolutionContract) => queryClient.setQueryData(timetableQueryKey, next);

  // Track provisional session ID during optimistic move validation
  const [provisionalSessionId, setProvisionalSessionId] = useState<string | null>(null);

  // Surface readable rejection message from mock backend
  const [rejectionAlert, setRejectionAlert] = useState<{
    reason: string;
    sessionId?: string;
    originalSlotLabel?: string;
  } | null>(null);

  // Toggle for testing rejection on move
  const [rejectMoveMode, setRejectMoveMode] = useState<boolean>(false);

  const caps = ROLE_CAPABILITIES[currentRole];

  // The solution examples were solved for the example instance; other instances show their own
  // published solution, or none (Not solved yet)
  const isExample = instance === 'example';
  const shown = isExample ? solution : publishedSolution;
  const labels = useMemo(() => labelsFor(display), [display]);
  // The mock validates moves against the example edge list only
  const canDrag = caps.canDragAndDrop && isExample;

  // Helper to toggle between solved timetable and infeasible diagnosis
  const handleToggleOutcome = async () => {
    chronosApiClient.setSimulatedOutcome(isSolvedSolution(solution) ? 'infeasible' : 'solved');
    await queryClient.refetchQueries({ queryKey: timetableQueryKey });
    setRejectionAlert(null);
  };

  // Helper to toggle rejection simulation
  const handleToggleRejectMode = () => {
    setRejectMoveMode((prev) => {
      const next = !prev;
      chronosApiClient.setRejectMode(
        next,
        next
          ? 'Mock Backend Rejection: Target slot causes faculty overlap and violates room capacity.'
          : undefined
      );
      return next;
    });
  };

  // Placements on the grid: the printed timetable, else the solved solution's
  const placed = useMemo<SessionAssignment[] | null>(
    () => printed?.assignment ?? (shown && isSolvedSolution(shown) ? shown.assignment : null),
    [printed, shown]
  );
  const quality = useMemo(
    () => printed?.quality ?? (shown && isSolvedSolution(shown) ? toQualityView(shown) : null),
    [printed, shown]
  );
  // The printed timetable's violating sessions: the picked violation's, else every one
  const flaggedSessionIds = useMemo(() => {
    if (!printed) return undefined;
    const picked = selectedViolation === null ? undefined : printed.violations[selectedViolation];
    return new Set((picked ? [picked] : printed.violations).flatMap((v) => v.session_ids));
  }, [printed, selectedViolation]);

  // Enriched sessions if solved (or printed)
  const allSessions = useMemo(
    () => (placed ? buildEnrichedSessions(placed, edgeList, labels) : []),
    [placed, edgeList, labels]
  );

  // Selected session lookup
  const selectedSession = useMemo<EnrichedSession | null>(() => {
    if (!selectedSessionId || !allSessions.length) return null;
    return allSessions.find((s) => s.sessionId === selectedSessionId) ?? null;
  }, [selectedSessionId, allSessions]);

  const facultyOptions = useMemo(
    () =>
      [...new Map(allSessions.map((s) => [s.facultyId, `${s.facultyName} (${s.facultyInitials})`]))]
        .map(([id, label]) => ({ id, label }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [allSessions]
  );
  const cohorts = useMemo(() => cohortOptions(edgeList, labels), [edgeList, labels]);
  // A choice made on another instance falls back to this instance's first option
  const hasCohort = (id: string | null) => cohorts.some((c) => c.id === id);
  const selectedFaculty =
    facultyChoice !== null && facultyOptions.some((f) => f.id === facultyChoice)
      ? facultyChoice
      : facultyOptions[0]?.id ?? '';
  const selectedStudentDivision =
    studentChoice !== null && hasCohort(studentChoice) ? studentChoice : cohorts[0]?.id ?? 'all';
  const selectedCohortFilter = hasCohort(cohortFilter) ? cohortFilter : 'all';

  // Compute sessions for selected faculty (for faculty role view)
  const facultySessions = useMemo(() => {
    if (!allSessions.length) return [];
    return allSessions.filter((s) => s.facultyId === selectedFaculty);
  }, [allSessions, selectedFaculty]);

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
          solutionStatus={shown?.status ?? null}
          onToggleOutcome={isExample ? handleToggleOutcome : undefined}
          rejectMoveMode={rejectMoveMode}
          onToggleRejectMode={handleToggleRejectMode}
        />

        {/* Four Role-Differentiated Views Selector */}
        <RoleSelector
          currentRole={currentRole}
          onRoleChange={setCurrentRole}
          selectedFaculty={selectedFaculty}
          onFacultyChange={setSelectedFaculty}
          selectedStudentDivision={selectedStudentDivision}
          onStudentDivisionChange={setSelectedStudentDivision}
          facultyOptions={facultyOptions}
          cohortOptions={cohorts}
        />

        {/* Rejection Alert Banner (when an optimistic move is rejected) */}
        {rejectionAlert && (
          <RejectionAlert
            reason={rejectionAlert.reason}
            sessionId={rejectionAlert.sessionId}
            originalSlotLabel={rejectionAlert.originalSlotLabel}
            onDismiss={() => setRejectionAlert(null)}
          />
        )}

        {/* Faculty Workload View (Visible only to Faculty Role) */}
        {currentRole === 'faculty' && quality && (
          <FacultyWorkloadCard
            facultyInitials={facultySessions[0]?.facultyInitials ?? ''}
            facultySessions={facultySessions}
            loadRule={quality.rules.find((r) => r.rule_id === 'S-LOAD16')}
          />
        )}

        {/* Infeasible Diagnosis Panel (When solver outcome is infeasible) */}
        {shown && isInfeasibleSolution(shown) && (
          <InfeasibilityDiagnosisPanel
            infeasibleSolution={shown}
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

        {/* Ingestion anomaly report (whole-department roles) */}
        {caps.viewScope === 'all' && anomalies && <AnomalyReportPanel report={anomalies} />}

        {/* Session Details Modal */}
        <SessionDetailModal
          session={isModalOpen ? selectedSession : null}
          onClose={() => setIsModalOpen(false)}
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
