import React from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { EnrichedSession, facultyLoad } from '@/adapters/timetable';
import { QualityRule } from '@/adapters/solution';
import { School, BookOpen, Clock, Activity, CheckCircle } from 'lucide-react';

interface FacultyWorkloadCardProps {
  facultyInitials: string;
  facultySessions: EnrichedSession[];
  /** The solver's S-LOAD16 entry (D11, D34); the only source of a load status */
  loadRule?: QualityRule;
}

export const FacultyWorkloadCard: React.FC<FacultyWorkloadCardProps> = ({
  facultyInitials,
  facultySessions,
  loadRule,
}) => {
  // Compute Theory (T) and Practical (P) hours
  const { theory: theoryHours, practical: practicalHours, total: totalWeightedWorkload } = facultyLoad(facultySessions);
  const facultyName = facultySessions.find((s) => s.facultyName)?.facultyName ?? '';

  return (
    <Card
      data-testid="faculty-workload-card"
      className="border-primary/30 bg-primary/5 backdrop-blur-md shadow-sm"
    >
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
              <School className="h-4 w-4" />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <CardTitle className="text-sm font-bold">
                  Faculty Individual View: {facultyInitials}
                </CardTitle>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {facultyName || 'Department Faculty'}
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                Theory / practical hours placed in this timetable
              </p>
            </div>
          </div>

          {/* Institutional T/P Notation */}
          <div
            data-testid="workload-formula-badge"
            className="flex items-center gap-1.5 rounded-lg border border-primary/40 bg-background/80 px-3 py-1 font-mono text-xs font-bold text-primary shadow-xs"
          >
            <Activity className="h-3.5 w-3.5" />
            <span>
              {theoryHours}T + {practicalHours}P = {totalWeightedWorkload} hrs/wk
            </span>
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-2">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <div className="rounded-lg border border-border/60 bg-background/60 p-2">
            <div className="text-[10px] text-muted-foreground flex items-center gap-1">
              <BookOpen className="h-3 w-3 text-indigo-500" />
              Theory (T) Load
            </div>
            <div className="font-bold text-foreground mt-0.5">{theoryHours} hours / week</div>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/60 p-2">
            <div className="text-[10px] text-muted-foreground flex items-center gap-1">
              <Clock className="h-3 w-3 text-emerald-500" />
              Practical (P) Load
            </div>
            <div className="font-bold text-foreground mt-0.5">{practicalHours} hours / week</div>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/60 p-2">
            <div className="text-[10px] text-muted-foreground flex items-center gap-1">
              <Activity className="h-3 w-3 text-primary" />
              Total Teaching
            </div>
            <div className="font-bold text-foreground mt-0.5">{totalWeightedWorkload} hours / week</div>
          </div>

          <div className="rounded-lg border border-border/60 bg-background/60 p-2">
            <div className="text-[10px] text-muted-foreground flex items-center gap-1">
              <CheckCircle className="h-3 w-3 text-emerald-500" />
              S-LOAD16 (solver)
            </div>
            <div data-testid="load-status" className="font-semibold text-foreground mt-0.5">
              {!loadRule
                ? 'not reported by the solver'
                : loadRule.status === 'not_evaluated'
                  ? 'not evaluated'
                  : loadRule.explanation}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
