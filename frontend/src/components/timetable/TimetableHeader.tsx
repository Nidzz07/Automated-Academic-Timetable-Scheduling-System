import React from 'react';
import { Button } from '@/components/ui/button';
import { UserRole, ROLE_CAPABILITIES } from '@/types/roles';
import { UI } from '@/lib/wording';
import type { EdgeListInstance, InstanceOption } from '@/api/chronosApi';
import { Moon, Sun, AlertTriangle, RotateCcw } from 'lucide-react';

interface TimetableHeaderProps {
  cohortFilter: string;
  onCohortFilterChange: (filter: string) => void;
  /** Cohorts named in the edge list */
  cohortOptions: Array<{ id: string; label: string }>;
  /** The instances the API client offers */
  instanceOptions: InstanceOption[];
  instance: EdgeListInstance;
  onInstanceChange: (instance: EdgeListInstance) => void;
  /** The account is linked to one teacher or class (D50): it stays on the real timetable */
  instanceLocked?: boolean;
  showQualityCard: boolean;
  onToggleQualityCard: () => void;
  darkMode: boolean;
  onToggleDarkMode: () => void;
  currentRole: UserRole;
  /** null: the instance has no solution yet; 'printed': it shows the timetable as printed */
  solutionStatus: 'solved' | 'infeasible' | 'printed' | null;
  onToggleOutcome?: () => void;
  rejectMoveMode: boolean;
  onToggleRejectMode?: () => void;
}

const STATUS: Record<'solved' | 'infeasible' | 'printed' | 'unsolved', { text: string; className: string }> = {
  solved: { text: 'Solved, no clashes', className: 'border-emerald-700 text-emerald-900 dark:text-emerald-200' },
  infeasible: { text: 'No timetable possible', className: 'border-destructive text-destructive dark:text-red-300' },
  printed: { text: 'Printed timetable (SPIT)', className: 'border-border' },
  unsolved: { text: 'Not solved yet', className: 'border-border' },
};

const fieldClass = 'flex items-center gap-1.5 rounded-md border border-input bg-card px-2.5 py-1.5';

/** A swatch beside its meaning, for the grid's four kinds of item */
const Key: React.FC<{ swatch: string; name: string; note: string }> = ({ swatch, name, note }) => (
  <span className="flex items-center gap-1.5">
    <span aria-hidden="true" className={`h-3.5 w-3.5 rounded-sm border border-l-4 ${swatch}`} />
    <span>
      <strong>{name}</strong> ({note})
    </span>
  </span>
);

export const TimetableHeader: React.FC<TimetableHeaderProps> = ({
  cohortFilter,
  onCohortFilterChange,
  cohortOptions,
  instanceOptions,
  instance,
  onInstanceChange,
  instanceLocked = false,
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
  const status = STATUS[solutionStatus ?? 'unsolved'];

  return (
    <header className="space-y-4">
      <div className="flex flex-col justify-between gap-4 border-b border-border pb-4 lg:flex-row lg:items-end">
        <div>
          <div className="flex flex-wrap items-baseline gap-3">
            <h1 className="text-2xl font-bold">Chronos</h1>
            <span
              data-testid={`status-badge-${solutionStatus ?? 'unsolved'}`}
              className={`rounded border px-2 py-0.5 text-xs font-semibold ${status.className}`}
            >
              {status.text}
            </span>
          </div>
          <p>Academic timetable scheduling, SPIT Computer Engineering, even semester 2025–26</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {/* Division filter for administrator and coordinator */}
          {(currentRole === 'administrator' || currentRole === 'coordinator') && (
            <label className={fieldClass}>
              <span className="font-semibold">Division:</span>
              <select
                aria-label="Filter timetable by division"
                value={cohortFilter}
                onChange={(e) => onCohortFilterChange(e.target.value)}
                className="cursor-pointer bg-transparent font-medium outline-none"
              >
                <option value="all">All divisions and cohorts</option>
                {cohortOptions.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {/* Timetable picker: every role, except an account linked to one teacher or class (D50) */}
          <label className={fieldClass}>
            <span className="font-semibold">{UI.timetablePicker}</span>
            <select
              aria-label="Select timetable"
              disabled={instanceLocked}
              value={instance}
              onChange={(e) => onInstanceChange(e.target.value)}
              className="cursor-pointer bg-transparent font-medium outline-none disabled:cursor-default"
            >
              {instanceOptions.map((i) => (
                <option key={i.id} value={i.id}>
                  {i.label}
                </option>
              ))}
            </select>
          </label>

          {caps.showQualityScore && solutionStatus === 'solved' && (
            <Button
              variant={showQualityCard ? 'default' : 'outline'}
              size="sm"
              onClick={onToggleQualityCard}
              data-testid="toggle-quality-card-button"
              aria-pressed={showQualityCard}
            >
              {showQualityCard ? 'Hide quality score' : 'Show quality score'}
            </Button>
          )}

          {/* Test controls (static mode's bundled example only: App passes the handlers there and nowhere else) */}
          {caps.showSimulationControls && onToggleOutcome && (
            <Button
              variant="outline"
              size="sm"
              onClick={onToggleOutcome}
              data-testid="toggle-outcome-button"
              title={UI.tryNoTimetableHint}
              className="gap-1.5 border-dashed"
            >
              <AlertTriangle className="h-4 w-4" />
              <span>{solutionStatus === 'solved' ? UI.tryNoTimetable : UI.showSolved}</span>
            </Button>
          )}

          {caps.showSimulationControls && onToggleRejectMode && solutionStatus === 'solved' && (
            <Button
              variant={rejectMoveMode ? 'destructive' : 'outline'}
              size="sm"
              onClick={onToggleRejectMode}
              data-testid="toggle-reject-mode-button"
              title={UI.tryRefusedMoveHint}
              className="gap-1.5"
            >
              <RotateCcw className="h-4 w-4" />
              <span>{rejectMoveMode ? UI.refusingMoves : UI.tryRefusedMove}</span>
            </Button>
          )}

          <Button
            variant="outline"
            size="icon"
            onClick={onToggleDarkMode}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >
            {darkMode ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </div>

      {/* Key to the grid */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
        <span className="font-semibold">Key:</span>
        <Key swatch="border-emerald-300 border-l-emerald-800 bg-emerald-50" name="Lab block" note={UI.labBlockNote} />
        <Key swatch="border-amber-300 border-l-amber-700 bg-amber-50" name="Combined lecture" note="two or more divisions together" />
        <Key swatch="border-slate-400 border-l-slate-700 bg-slate-100" name="Fixed item" note="cannot be moved" />
        <Key
          swatch="border-blue-200 border-l-blue-800 bg-blue-50"
          name="Lecture"
          note={caps.canDragAndDrop ? 'can be dragged' : 'read only'}
        />
      </div>
    </header>
  );
};
