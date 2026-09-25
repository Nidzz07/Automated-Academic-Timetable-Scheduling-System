import { useState, useMemo } from 'react';
import { TimetableGrid } from '@/components/timetable/TimetableGrid';
import { TimetableHeader } from '@/components/timetable/TimetableHeader';
import { QualityScoreCard } from '@/components/timetable/QualityScoreCard';
import { SessionDetailModal } from '@/components/timetable/SessionDetailModal';
import { getSolvedSolutionFixture, buildEnrichedSessions, EnrichedSession } from '@/lib/timetableData';

export function App() {
  const [darkMode, setDarkMode] = useState<boolean>(false);
  const [cohortFilter, setCohortFilter] = useState<string>('all');
  const [showQualityCard, setShowQualityCard] = useState<boolean>(true);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const solution = useMemo(() => getSolvedSolutionFixture(), []);
  const allSessions = useMemo(() => buildEnrichedSessions(solution), [solution]);

  const selectedSession = useMemo<EnrichedSession | null>(() => {
    if (!selectedSessionId) return null;
    return allSessions.find((s) => s.sessionId === selectedSessionId) ?? null;
  }, [selectedSessionId, allSessions]);

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
    <div className={`min-h-screen bg-background text-foreground transition-colors duration-200 ${darkMode ? 'dark' : ''}`}>
      <div className="mx-auto max-w-7xl px-4 py-8 space-y-6 sm:px-6 lg:px-8">
        {/* Header Toolbar */}
        <TimetableHeader
          cohortFilter={cohortFilter}
          onCohortFilterChange={setCohortFilter}
          showQualityCard={showQualityCard}
          onToggleQualityCard={() => setShowQualityCard((prev) => !prev)}
          darkMode={darkMode}
          onToggleDarkMode={toggleDarkMode}
        />

        {/* Quality Score & Rules Breakdown */}
        {showQualityCard && (
          <QualityScoreCard
            quality={solution.quality}
            metadata={solution.metadata}
          />
        )}

        {/* Main 8-Period x 5-Day Weekly Grid */}
        <main className="space-y-2">
          <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
            <span className="font-semibold text-foreground">
              Weekly Timetable Schedule (8 Teaching Periods · 5 Days)
            </span>
            <span className="font-mono text-[11px]">
              Schema: solution.v1 · Status: {solution.status.toUpperCase()}
            </span>
          </div>

          <TimetableGrid
            solution={solution}
            cohortFilter={cohortFilter}
            onSelectSession={setSelectedSessionId}
          />
        </main>

        {/* Session Details Modal */}
        <SessionDetailModal
          session={selectedSession}
          onClose={() => setSelectedSessionId(null)}
        />

        {/* Institutional Traceability Footer */}
        <footer className="border-t border-border/60 pt-6 text-center text-xs text-muted-foreground space-y-1.5">
          <p className="font-semibold text-foreground">
            Chronos Timetable Scheduling System · Sardar Patel Institute of Technology
          </p>
          <p>
            Track C (Frontend & Validation) — Built with React 18, Vite, TypeScript, TailwindCSS, and shadcn/ui.
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
