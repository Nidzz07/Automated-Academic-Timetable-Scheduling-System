import React from 'react';
import { QualityEvaluation, SolutionMetadata } from '@/types/solution';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { CheckCircle2, Cpu, Timer, ShieldCheck, Activity } from 'lucide-react';

interface QualityScoreCardProps {
  quality: QualityEvaluation;
  metadata: SolutionMetadata;
}

export const QualityScoreCard: React.FC<QualityScoreCardProps> = ({
  quality,
  metadata,
}) => {
  return (
    <Card className="border-border/60 bg-card/60 backdrop-blur-md shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-600 dark:text-emerald-400">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div>
              <CardTitle className="text-base font-bold">Solver Quality Evaluation</CardTitle>
              <p className="text-xs text-muted-foreground">
                Itemised breakdown per quality_rules.yaml
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-baseline gap-1 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1">
              <span className="text-xs font-semibold text-emerald-800 dark:text-emerald-300">
                Score:
              </span>
              <span className="text-lg font-black text-emerald-600 dark:text-emerald-400">
                {quality.score}
              </span>
              <span className="text-xs text-muted-foreground">/ 100</span>
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-0">
        {/* Run statistics metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
          <div className="flex items-center gap-2 rounded-md border border-border/50 bg-muted/40 p-2">
            <Cpu className="h-4 w-4 text-primary shrink-0" />
            <div className="overflow-hidden">
              <div className="text-[10px] text-muted-foreground">Algorithm</div>
              <div className="font-semibold truncate" title={metadata.algorithm}>
                {metadata.algorithm}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-md border border-border/50 bg-muted/40 p-2">
            <Timer className="h-4 w-4 text-emerald-500 shrink-0" />
            <div>
              <div className="text-[10px] text-muted-foreground">Solve Time</div>
              <div className="font-semibold">{metadata.runtime_ms} ms</div>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-md border border-border/50 bg-muted/40 p-2">
            <CheckCircle2 className="h-4 w-4 text-blue-500 shrink-0" />
            <div>
              <div className="text-[10px] text-muted-foreground">Placement</div>
              <div className="font-semibold">
                {metadata.sessions_assigned} / {metadata.sessions_total} (100%)
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-md border border-border/50 bg-muted/40 p-2">
            <Activity className="h-4 w-4 text-purple-500 shrink-0" />
            <div>
              <div className="text-[10px] text-muted-foreground">Chromatic & Backtracks</div>
              <div className="font-semibold">
                {metadata.slots_used ?? 'N/A'} slots · {metadata.backtracks ?? 0} backtracks
              </div>
            </div>
          </div>
        </div>

        {/* Penalty Breakdown */}
        <div className="rounded-lg border border-border/60 bg-background/50 p-2.5">
          <div className="text-[11px] font-bold text-muted-foreground uppercase tracking-wider mb-2">
            Penalty Rule Contributions
          </div>
          <div className="space-y-2">
            {quality.breakdown.map((item) => (
              <div
                key={item.rule_id}
                className="flex flex-col sm:flex-row sm:items-center justify-between gap-1.5 rounded-md border border-border/40 bg-card p-2 text-xs"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-semibold text-foreground">
                      {item.rule_id}
                    </span>
                    <Badge variant="outline" className="text-[10px] py-0">
                      weight: {item.weight}
                    </Badge>
                    <Badge variant="destructive" className="text-[10px] py-0">
                      -{item.penalty.toFixed(1)} pts
                    </Badge>
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-0.5">
                    {item.explanation}
                  </p>
                </div>
                <div className="font-mono text-[11px] text-muted-foreground shrink-0 sm:text-right">
                  raw: {item.raw}
                </div>
              </div>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
