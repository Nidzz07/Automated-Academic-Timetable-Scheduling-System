import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { UserRole, ROLE_CAPABILITIES } from '@/types/roles';
import {
  CalendarDays,
  Filter,
  Moon,
  Sun,
  ShieldCheck,
  AlertTriangle,
  RotateCcw,
  Sparkles,
} from 'lucide-react';

interface TimetableHeaderProps {
  cohortFilter: string;
  onCohortFilterChange: (filter: string) => void;
  showQualityCard: boolean;
  onToggleQualityCard: () => void;
  darkMode: boolean;
  onToggleDarkMode: () => void;
  currentRole: UserRole;
  solutionStatus: 'solved' | 'infeasible';
  onToggleOutcome?: () => void;
  rejectMoveMode: boolean;
  onToggleRejectMode?: () => void;
}

export const TimetableHeader: React.FC<TimetableHeaderProps> = ({
  cohortFilter,
  onCohortFilterChange,
  showQualityCard,
  onToggleQualityCard,
  darkMode,
  onToggleDarkMode,
  currentRole,
  solutionStatus,
  onToggleOutcome,
  rejectMoveMode,
  onToggleRejectMode,
}) => {
  const caps = ROLE_CAPABILITIES[currentRole];

  return (
    <header className="space-y-4">
      {/* Top row: Brand, Status & Action Controls */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border/60 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-tr from-primary to-indigo-600 text-white shadow-md shadow-primary/20">
            <CalendarDays className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-black tracking-tight text-foreground">
                Chronos
              </h1>
              <Badge variant="outline" className="font-mono text-[10px] uppercase">
                Phase 2 Track C
              </Badge>
              {solutionStatus === 'solved' ? (
                <Badge variant="success" data-testid="status-badge-solved" className="text-[10px]">
                  Solved · Conflict-Free
                </Badge>
              ) : (
                <Badge variant="destructive" data-testid="status-badge-infeasible" className="text-[10px]">
                  Infeasible Instance
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Academic Timetable Scheduling System · SPIT Computer Engineering (EVEN 2025–26)
            </p>
          </div>
        </div>

        {/* Action and Theme Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Cohort Filter for Admin & Coordinator */}
          {(currentRole === 'administrator' || currentRole === 'coordinator') && (
            <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-xs shadow-xs">
              <Filter className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="font-semibold text-muted-foreground">Division:</span>
              <select
                aria-label="Filter timetable by division"
                value={cohortFilter}
                onChange={(e) => onCohortFilterChange(e.target.value)}
                className="bg-transparent font-medium text-foreground outline-hidden cursor-pointer"
              >
                <option value="all">All Divisions & Cohorts</option>
                <option value="coh-div-se-b">SE-Comp B (Labs & Combined)</option>
                <option value="coh-div-se-c">SE-Comp C (Lectures & Combined)</option>
              </select>
            </div>
          )}

          {/* Toggle Quality Breakdown (if role has permission) */}
          {caps.showQualityScore && solutionStatus === 'solved' && (
            <Button
              variant={showQualityCard ? 'default' : 'outline'}
              size="sm"
              onClick={onToggleQualityCard}
              data-testid="toggle-quality-card-button"
              className="text-xs gap-1.5"
            >
              <ShieldCheck className="h-3.5 w-3.5" />
              <span>Score & Metrics</span>
            </Button>
          )}

          {/* Admin Simulation Toggles */}
          {caps.showSimulationControls && onToggleOutcome && (
            <Button
              variant="outline"
              size="sm"
              onClick={onToggleOutcome}
              data-testid="toggle-outcome-button"
              title="Toggle between Solved Timetable and Infeasible Diagnosis fixtures"
              className="text-xs gap-1.5 border-dashed"
            >
              <AlertTriangle className="h-3.5 w-3.5 text-amber-500" />
              <span>
                {solutionStatus === 'solved' ? 'Simulate Infeasible' : 'Show Solved'}
              </span>
            </Button>
          )}

          {caps.showSimulationControls && onToggleRejectMode && solutionStatus === 'solved' && (
            <Button
              variant={rejectMoveMode ? 'destructive' : 'outline'}
              size="sm"
              onClick={onToggleRejectMode}
              data-testid="toggle-reject-mode-button"
              title="When enabled, mock backend will reject any dragged move to test optimistic revert"
              className="text-xs gap-1.5"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>{rejectMoveMode ? 'Reject Moves: ON' : 'Test Revert on Move'}</span>
            </Button>
          )}

          {/* Dark Mode Toggle */}
          <Button
            variant="outline"
            size="icon"
            onClick={onToggleDarkMode}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            className="h-8 w-8"
          >
            {darkMode ? (
              <Sun className="h-4 w-4 text-amber-400" />
            ) : (
              <Moon className="h-4 w-4 text-slate-700" />
            )}
          </Button>
        </div>
      </div>

      {/* Legend Row highlighting cases and role capability */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs bg-muted/40 rounded-xl p-3 border border-border/50">
        <div className="flex items-center gap-1.5 font-bold text-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span>Interactive Primitives:</span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-emerald-500 bg-emerald-500/20" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Lab Block</strong> (Double-Period 4 Batches)
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-amber-500 bg-amber-500/20" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Combined Lecture</strong> (Union Cohort)
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-slate-400 bg-slate-300 dark:bg-slate-700 bg-pinned-pattern" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Pinned Block</strong> (Immovable)
            </span>
          </div>

          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-indigo-400 bg-indigo-500/20" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Theory Lecture</strong> ({caps.canDragAndDrop ? 'Draggable' : 'Read-Only'})
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
