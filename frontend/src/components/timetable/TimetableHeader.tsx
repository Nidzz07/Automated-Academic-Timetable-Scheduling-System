import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  CalendarDays,
  Filter,
  Moon,
  Sun,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

interface TimetableHeaderProps {
  cohortFilter: string;
  onCohortFilterChange: (filter: string) => void;
  showQualityCard: boolean;
  onToggleQualityCard: () => void;
  darkMode: boolean;
  onToggleDarkMode: () => void;
}

export const TimetableHeader: React.FC<TimetableHeaderProps> = ({
  cohortFilter,
  onCohortFilterChange,
  showQualityCard,
  onToggleQualityCard,
  darkMode,
  onToggleDarkMode,
}) => {
  return (
    <header className="space-y-4">
      {/* Top row: Brand & Action Controls */}
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
                Phase 1 Track C
              </Badge>
              <Badge variant="success" className="text-[10px]">
                Solved · Conflict-Free
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              Academic Timetable Scheduling System · SPIT Computer Engineering (EVEN 2025–26)
            </p>
          </div>
        </div>

        {/* Filter and Theme Controls */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Cohort / Division Filter */}
          <div className="flex items-center gap-1.5 rounded-lg border border-border bg-card px-2.5 py-1 text-xs shadow-xs">
            <Filter className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="font-semibold text-muted-foreground">View:</span>
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

          {/* Toggle Quality Breakdown */}
          <Button
            variant={showQualityCard ? 'default' : 'outline'}
            size="sm"
            onClick={onToggleQualityCard}
            className="text-xs gap-1.5"
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            <span>Score & Metrics</span>
          </Button>

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

      {/* Legend Row highlighting the four required cases */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs bg-muted/40 rounded-xl p-3 border border-border/50">
        <div className="flex items-center gap-1.5 font-bold text-foreground">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <span>Contract Rendering Primitives:</span>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Case 1 & 2 */}
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-emerald-500 bg-emerald-500/20" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Double-Period Lab Block</strong> (4 Parallel Sub-room Batches)
            </span>
          </div>

          {/* Case 3 */}
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-amber-500 bg-amber-500/20" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Combined-Division Lecture</strong> (Full Union Cohort)
            </span>
          </div>

          {/* Case 4 */}
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-slate-400 bg-slate-300 dark:bg-slate-700 bg-pinned-pattern" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Pinned Block</strong> (Immovable Occupancy)
            </span>
          </div>

          {/* Standard */}
          <div className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-xs border border-indigo-400 bg-indigo-500/20" />
            <span className="text-muted-foreground">
              <strong className="text-foreground">Solver Placement</strong> (Standard Theory)
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
