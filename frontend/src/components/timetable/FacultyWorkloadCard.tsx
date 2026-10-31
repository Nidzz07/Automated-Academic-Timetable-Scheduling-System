import React from 'react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card';
import { FacultyLoad, loadText } from '@/adapters/timetable';
import { QualityRule } from '@/adapters/solution';
import { loadLimitHours, loadPartsText, readableSolverText } from '@/lib/wording';
import { OverLimitWarning } from './OverLimitWarning';

interface FacultyWorkloadCardProps {
  facultyName: string;
  /** Empty for a teacher display.json gives none */
  facultyInitials: string;
  /** facultyLoad: counted as the solver's S-LOAD16 counts it, so the warning and the rule agree */
  load: FacultyLoad;
  /** The solver's S-LOAD16 entry (D11, D34); the only source of a load status and of the limit */
  loadRule?: QualityRule;
  /** A faculty id the solver's explanation names, by name; null keeps the id */
  nameOf?: (id: string) => string | null;
}

export const FacultyWorkloadCard: React.FC<FacultyWorkloadCardProps> = ({
  facultyName,
  facultyInitials,
  load,
  loadRule,
  nameOf,
}) => {
  // Two sessions in one slot (a printed clash) are one teaching hour, as the solver counts them
  const overlap = load.theory + load.practical - load.scheduled;

  return (
    <Card data-testid="faculty-workload-card">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>
              Weekly teaching load: {facultyInitials ? `${facultyName} (${facultyInitials})` : facultyName}
            </CardTitle>
            <CardDescription>Sessions placed in this timetable plus the fixed items this teacher holds.</CardDescription>
          </div>
          {/* The department's own notation, e.g. 6T + 8P = 14 */}
          <p data-testid="workload-formula-badge" className="font-serif text-xl font-semibold">
            {loadText(load)} hrs/wk
          </p>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-0">
        <p data-testid="workload-parts" className="font-semibold">
          {loadPartsText(load)}
        </p>
        <OverLimitWarning hours={load.total} limit={loadLimitHours(loadRule)} />
        {overlap > 0 && (
          <p data-testid="workload-overlap" className="text-xs">
            {overlap} h of these sessions overlap in this timetable and are counted once.
          </p>
        )}
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <div>
            <dt className="text-xs font-semibold">Theory (T)</dt>
            <dd className="text-base">{load.theory} hours a week</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Practical (P)</dt>
            <dd className="text-base">{load.practical} hours a week</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Fixed items</dt>
            <dd className="text-base">{load.fixed} hours a week</dd>
          </div>
          <div>
            <dt className="text-xs font-semibold">Total teaching</dt>
            <dd className="text-base font-semibold">{load.total} hours a week</dd>
          </div>
          <div className="col-span-2 sm:col-span-4">
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
