import { useState, useMemo } from 'react';
import { TimetableGrid } from '@/components/timetable/TimetableGrid';
import { TimetableHeader } from '@/components/timetable/TimetableHeader';
import { QualityScoreCard } from '@/components/timetable/QualityScoreCard';
import { SessionDetailModal } from '@/components/timetable/SessionDetailModal';
import { RoleSelector } from '@/components/timetable/RoleSelector';
import { FacultyWorkloadCard } from '@/components/timetable/FacultyWorkloadCard';
import { InfeasibilityDiagnosisPanel } from '@/components/timetable/InfeasibilityDiagnosisPanel';
import { RejectionAlert } from '@/components/timetable/RejectionAlert';
import { UserRole, ROLE_CAPABILITIES } from '@/types/roles';
import {
  SolutionContract,
  SolvedSolution,
  isSolvedSolution,
  isInfeasibleSolution,
  DayIndex,
} from '@/types/solution';
import {
  buildEnrichedSessions,
  getSolvedSolutionFixture,
  EnrichedSession,
  DAYS,
  TEACHING_PERIODS,
  wallClockToTeachingPeriod,
} from '@/lib/timetableData';
import { chronosApiClient } from '@/api/chronosApi';

export function App() {
  const [darkMode, setDarkMode] = useState<boolean>(false);
  const [currentRole, setCurrentRole] = useState<UserRole>('administrator');
  const [selectedFaculty, setSelectedFaculty] = useState<string>('AGN');
  const [selectedStudentDivision, setSelectedStudentDivision] = useState<string>('coh-div-se-b');
  const [cohortFilter, setCohortFilter] = useState<string>('all');
  const [showQualityCard, setShowQualityCard] = useState<boolean>(true);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);

  // Solution contract state: can be SolvedSolution or InfeasibleSolution
  const [solution, setSolution] = useState<SolutionContract>(() => getSolvedSolutionFixture());

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

  // Helper to toggle between solved timetable and infeasible diagnosis
  const handleToggleOutcome = async () => {
    if (isSolvedSolution(solution)) {
      chronosApiClient.setSimulatedOutcome('infeasible');
      const inf = await chronosApiClient.getInfeasibleSolution();
      setSolution(inf);
    } else {
      chronosApiClient.setSimulatedOutcome('solved');
      const sol = await chronosApiClient.getSolvedSolution();
      setSolution(sol);
    }
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

  // Enriched sessions if solved
  const allSessions = useMemo(() => {
    if (!isSolvedSolution(solution)) return [];
    return buildEnrichedSessions(solution);
  }, [solution]);

  // Selected session lookup
  const selectedSession = useMemo<EnrichedSession | null>(() => {
    if (!selectedSessionId || !allSessions.length) return null;
    return allSessions.find((s) => s.sessionId === selectedSessionId) ?? null;
  }, [selectedSessionId, allSessions]);

  // Compute sessions for selected faculty (for faculty role view)
  const facultySessions = useMemo(() => {
    if (!allSessions.length) return [];
    return allSessions.filter((s) => s.facultyInitials === selectedFaculty);
  }, [allSessions, selectedFaculty]);

  // Determine effective cohort filter based on role
  const effectiveCohortFilter = useMemo(() => {
    if (currentRole === 'student') {
      return selectedStudentDivision;
    }
    if (currentRole === 'faculty') {
      return 'all'; // handled by session filtering or pass-through
    }
    return cohortFilter;
  }, [currentRole, selectedStudentDivision, cohortFilter]);

  // If role is faculty, derive solution subset showing only this faculty's sessions
  const roleFilteredSolution = useMemo<SolvedSolution | null>(() => {
    if (!isSolvedSolution(solution)) return null;
    if (currentRole !== 'faculty') return solution;

    // Filter assignments to only those belonging to the selected faculty
    const facultySessionIds = new Set(facultySessions.map((s) => s.sessionId));
    const filteredAssignments = solution.assignment.filter((a) =>
      facultySessionIds.has(a.session_id)
    );

    return {
      ...solution,
      assignment: filteredAssignments,
    };
  }, [solution, currentRole, facultySessions]);

  /**
   * Optimistic drag-and-drop handler with clean revert-on-reject.
   * Restores exact prior state including the session's original slot and UI selection.
   */
  const handleMoveSession = async (
    sessionId: string,
    targetDay: DayIndex,
    targetTeachingPeriod: number
  ) => {
    // Only drag-enabled roles may move sessions
    if (!caps.canDragAndDrop) {
      return;
    }

    if (!isSolvedSolution(solution)) {
      return;
    }

    const currentAssignment = solution.assignment.find((a) => a.session_id === sessionId);
    if (!currentAssignment) return;

    const originalDay = currentAssignment.day;
    const originalPeriod = currentAssignment.period;
    const originalTeachingPeriod = wallClockToTeachingPeriod(originalPeriod);

    // If dropped on same slot, no-op
    if (originalDay === targetDay && originalTeachingPeriod === targetTeachingPeriod) {
      return;
    }

    // 1. CAPTURE EXACT PRIOR STATE
    const priorSolution: SolvedSolution = JSON.parse(JSON.stringify(solution));
    const priorSelectedSessionId = selectedSessionId;
    const originalDayName = DAYS.find((d) => d.day === originalDay)?.label ?? `Day ${originalDay}`;
    const originalSlotLabel = `${originalDayName} Period ${originalTeachingPeriod + 1} (${TEACHING_PERIODS[originalTeachingPeriod]?.timeLabel ?? ''})`;

    const targetWallClockPeriod =
      TEACHING_PERIODS[targetTeachingPeriod]?.wallClockPeriod ?? targetTeachingPeriod;

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
      const result = await chronosApiClient.moveSession(
        {
          sessionId,
          targetDay,
          targetTeachingPeriod,
          targetWallClockPeriod,
        },
        priorSolution
      );

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
    } catch (err: any) {
      // Revert cleanly on exception
      setSolution(priorSolution);
      setSelectedSessionId(priorSelectedSessionId);
      setProvisionalSessionId(null);
      setRejectionAlert({
        reason: err?.message || 'Network exception during move validation.',
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
          cohortFilter={cohortFilter}
          onCohortFilterChange={setCohortFilter}
          showQualityCard={showQualityCard}
          onToggleQualityCard={() => setShowQualityCard((prev) => !prev)}
          darkMode={darkMode}
          onToggleDarkMode={toggleDarkMode}
          currentRole={currentRole}
          solutionStatus={solution.status}
          onToggleOutcome={handleToggleOutcome}
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
        {currentRole === 'faculty' && isSolvedSolution(solution) && (
          <FacultyWorkloadCard
            facultyInitials={selectedFaculty}
            facultySessions={facultySessions}
          />
        )}

        {/* Infeasible Diagnosis Panel (When solver outcome is infeasible) */}
        {isInfeasibleSolution(solution) && (
          <InfeasibilityDiagnosisPanel
            infeasibleSolution={solution}
            onApplyRelaxation={handleToggleOutcome}
            onSwitchToSolved={handleToggleOutcome}
          />
        )}

        {/* Quality Score & Rules Breakdown (Admin / Coordinator only) */}
        {caps.showQualityScore && isSolvedSolution(solution) && showQualityCard && (
          <QualityScoreCard
            quality={solution.quality}
            metadata={solution.metadata}
          />
        )}

        {/* Main 8-Period x 5-Day Weekly Grid (Rendered when solved) */}
        {isSolvedSolution(solution) && roleFilteredSolution && (
          <main className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
              <span className="font-semibold text-foreground">
                Weekly Timetable Schedule (8 Teaching Periods · 5 Days) — {caps.title} View
              </span>
              <span className="font-mono text-[11px]">
                {caps.canDragAndDrop ? 'Interactive: Drag Sessions to Reschedule' : 'Read-Only Schedule'}
              </span>
            </div>

            <TimetableGrid
              solution={roleFilteredSolution}
              cohortFilter={effectiveCohortFilter}
              showPinnedBlocks={currentRole !== 'faculty'}
              canDragAndDrop={caps.canDragAndDrop}
              selectedSessionId={selectedSessionId}
              provisionalSessionId={provisionalSessionId}
              onSelectSession={(id) => {
                setSelectedSessionId(id);
                setIsModalOpen(true);
              }}
              onMoveSession={handleMoveSession}
            />
          </main>
        )}

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
            Validated against Frozen Contract 3 (solution_v1.schema.json) · Hand-written deterministic solver integration
          </p>
        </footer>
      </div>
    </div>
  );
}

export default App;
