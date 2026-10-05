import React from 'react';
import { InfeasibleSolution } from '@/types/solution';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  AlertTriangle,
  Lightbulb,
  Cpu,
  Timer,
  GitBranch,
  Layers,
  ArrowRight,
  Info,
} from 'lucide-react';

interface InfeasibilityDiagnosisPanelProps {
  infeasibleSolution: InfeasibleSolution;
  onApplyRelaxation?: (constraintId: string) => void;
  onSwitchToSolved?: () => void;
}

export const InfeasibilityDiagnosisPanel: React.FC<InfeasibilityDiagnosisPanelProps> = ({
  infeasibleSolution,
  onApplyRelaxation,
  onSwitchToSolved,
}) => {
  const { diagnosis, metadata } = infeasibleSolution;
  const { minimal_conflicting_set, suggested_relaxation } = diagnosis;

  return (
    <div
      data-testid="infeasibility-panel"
      className="space-y-4 rounded-2xl border-2 border-rose-500/30 bg-rose-500/5 p-4 sm:p-6 backdrop-blur-md"
    >
      {/* Top Banner Alert */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-rose-500/20 pb-4">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-rose-500 text-white shadow-md shadow-rose-500/20">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-black tracking-tight text-foreground">
                Infeasible Timetable Instance
              </h2>
              <Badge variant="destructive" className="font-mono text-[10px] uppercase">
                Status: INFEASIBLE
              </Badge>
              <Badge variant="outline" className="font-mono text-[10px]">
                MUS Extraction
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              The hand-written solver core proved no conflict-free assignment exists under the current constraints.
              A Minimal Unsatisfiable Subset (MUS) has been isolated.
            </p>
          </div>
        </div>

        {onSwitchToSolved && (
          <Button
            variant="outline"
            size="sm"
            onClick={onSwitchToSolved}
            className="text-xs gap-1 border-rose-300 dark:border-rose-800"
          >
            <span>View Solved Baseline</span>
            <ArrowRight className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>

      {/* Solver Diagnostics Metadata Strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/60 p-2.5">
          <Cpu className="h-4 w-4 text-rose-500 shrink-0" />
          <div className="overflow-hidden">
            <div className="text-[10px] text-muted-foreground">Diagnostic Algorithm</div>
            <div className="font-semibold truncate text-[11px]" title={metadata.algorithm}>
              {metadata.algorithm}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/60 p-2.5">
          <Timer className="h-4 w-4 text-amber-500 shrink-0" />
          <div>
            <div className="text-[10px] text-muted-foreground">Diagnosis Runtime</div>
            <div className="font-semibold text-[11px]">{metadata.runtime_ms} ms</div>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/60 p-2.5">
          <Layers className="h-4 w-4 text-primary shrink-0" />
          <div>
            <div className="text-[10px] text-muted-foreground">Placements Tested</div>
            <div className="font-semibold text-[11px]">
              {metadata.sessions_assigned} / {metadata.sessions_total} sessions placed
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-background/60 p-2.5">
          <GitBranch className="h-4 w-4 text-purple-500 shrink-0" />
          <div>
            <div className="text-[10px] text-muted-foreground">Backtracking Steps</div>
            <div className="font-semibold text-[11px]">{metadata.backtracks?.toLocaleString()} backtracks</div>
          </div>
        </div>
      </div>

      {/* Minimal Conflicting Subset (MUS) */}
      <Card className="border-rose-500/30 bg-card/80">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-rose-500/15 text-rose-600 dark:text-rose-400">
                <AlertTriangle className="h-3.5 w-3.5" />
              </span>
              <CardTitle className="text-sm font-bold">
                Minimal Conflicting Subset ({minimal_conflicting_set.length} Constraints)
              </CardTitle>
            </div>
            <span className="text-[11px] text-muted-foreground">
              Removing any single constraint restores satisfiability
            </span>
          </div>
        </CardHeader>

        <CardContent className="space-y-2.5 pt-0">
          <div
            data-testid="minimal-conflicting-set"
            className="space-y-2"
          >
            {minimal_conflicting_set.map((constraint) => (
              <div
                key={constraint.constraint_id}
                data-testid={`conflicting-constraint-${constraint.constraint_id}`}
                className="rounded-xl border border-rose-200 dark:border-rose-950/60 bg-rose-50/50 dark:bg-rose-950/20 p-3 space-y-1.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-1.5">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="destructive"
                      data-testid={`constraint-kind-${constraint.kind}`}
                      className="text-[10px] py-0 uppercase font-mono"
                    >
                      {constraint.kind}
                    </Badge>
                    <span className="font-mono text-xs font-semibold text-foreground">
                      {constraint.constraint_id}
                    </span>
                  </div>
                  <div className="text-[10px] font-mono text-muted-foreground">
                    Involves {constraint.entity_ids.length} entities
                  </div>
                </div>

                {/* Institutional Terms Description */}
                <p className="text-xs text-foreground/90 font-medium leading-relaxed">
                  {constraint.description}
                </p>

                {/* Entity IDs tag pills */}
                <div className="flex flex-wrap items-center gap-1 pt-1">
                  <span className="text-[10px] font-medium text-muted-foreground flex items-center gap-0.5">
                    <Info className="h-2.5 w-2.5" /> Entities:
                  </span>
                  {constraint.entity_ids.map((id) => (
                    <span
                      key={id}
                      className="inline-flex items-center rounded bg-background/80 px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground border border-border/50"
                    >
                      {id}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Suggested Relaxation */}
      <div
        data-testid="suggested-relaxation"
        className="rounded-xl border-2 border-emerald-500/50 bg-gradient-to-br from-emerald-500/10 via-emerald-500/5 to-transparent p-4 shadow-sm"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-emerald-500 text-white">
                <Lightbulb className="h-3.5 w-3.5" />
              </span>
              <span className="text-xs font-bold uppercase tracking-wider text-emerald-900 dark:text-emerald-300">
                Smallest Feasible Relaxation
              </span>
              <Badge
                variant="outline"
                data-testid="relaxation-constraint-id"
                className="font-mono text-[10px] border-emerald-400 text-emerald-800 dark:text-emerald-300"
              >
                Target: {suggested_relaxation.constraint_id}
              </Badge>
            </div>
            <p className="text-xs text-foreground font-medium pt-1">
              {suggested_relaxation.description}
            </p>
          </div>

          {onApplyRelaxation && (
            <Button
              size="sm"
              variant="default"
              onClick={() => onApplyRelaxation(suggested_relaxation.constraint_id)}
              className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs shrink-0 gap-1.5"
            >
              <Lightbulb className="h-3.5 w-3.5" />
              <span>Simulate Relaxation</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};
