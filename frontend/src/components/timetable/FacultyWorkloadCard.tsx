import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { EnrichedSession, facultyLoad } from '@/adapters/timetable';
import { QualityRule } from '@/adapters/solution';
import { loadLimitHours, readableSolverText } from '@/lib/wording';
import { OverLimitWarning } from './OverLimitWarning';

interface FacultyWorkloadCardProps {
  facultyInitials: string;
  facultySessions: EnrichedSession[];
  /** The solver's S-LOAD16 entry (D11, D34); the only source of a load status and of the limit */
  loadRule?: QualityRule;
  /** A faculty id the solver's explanation names, by name; null keeps the id */
  nameOf?: (id: string) => string | null;
}

export const FacultyWorkloadCard: React.FC<FacultyWorkloadCardProps> = ({
  facultyInitials,
  facultySessions,
  loadRule,
  nameOf,
}) => {
  // Theory (T) and practical (P) hours
  const { theory: theoryHours, practical: practicalHours, total: totalWeightedWorkload } = facultyLoad(facultySessions);
  const facultyName = facultySessions.find((s) => s.facultyName)?.facultyName ?? '';

  return (
    <Card data-testid="faculty-workload-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>
              Weekly teaching load: {facultyName ? `${facultyName} (${facultyInitials})` : facultyInitials}
            </CardTitle>
            <CardDescription>Theory and practical hours placed in this timetable.</CardDescription>
          </div>
          {/* The department's own notation, e.g. 6T + 8P = 14 */}
          <p data-testid="workload-formula-badge" className="font-serif text-xl font-semibold">
            {theoryHours}T + {practicalHours}P = {totalWeightedWorkload} hrs/wk
          </p>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-0">
        <OverLimitWarning hours={totalWeightedWorkload} limit={loadLimitHours(loadRule)} />
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <div>
            <dt className="text-xs font-semibold">Theory (T)</dt>
            <dd className="text-base">{theoryHours} hours a week</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Practical (P)</dt>
            <dd className="text-base">{practicalHours} hours a week</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Total teaching</dt>
            <dd className="text-base font-semibold">{totalWeightedWorkload} hours a week</dd>
          </div>
          <div className="col-span-2 sm:col-span-1">
            <dt className="text-xs font-semibold">
              Solver's weekly-limit check <span className="font-mono">S-LOAD16</span>
            </dt>
            <dd data-testid="load-status" className="text-xs">
              {!loadRule
                ? 'not reported by the solver'
                : loadRule.status === 'not_evaluated'
                  ? 'not evaluated'
                  : readableSolverText(loadRule.explanation, nameOf)}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
};
