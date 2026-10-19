import React from 'react';
import { PrintedViolation } from '@/adapters/realInstance';
import { DAY_NAMES } from '@/adapters/timetable';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

interface PrintedViolationsProps {
  violations: PrintedViolation[];
  /** Index of the violation whose sessions the grid highlights; null highlights every violation */
  selected: number | null;
  onSelect: (index: number | null) => void;
}

/** The time-only check's violations on the timetable as printed (real_baseline.report.json). */
export const PrintedViolationsPanel: React.FC<PrintedViolationsProps> = ({ violations, selected, onSelect }) => (
  <Card data-testid="printed-violations">
    <CardHeader className="pb-3">
      <CardTitle className="text-base">Printed timetable: {violations.length} violations</CardTitle>
      <CardDescription>
        Sessions in a violation are outlined in red on the grid. Pick one to outline only its sessions.
      </CardDescription>
    </CardHeader>
    <CardContent className="max-h-[320px] space-y-1.5 overflow-auto pt-0 text-xs">
      {violations.map((v, i) => (
        <button
          key={i}
          type="button"
          data-testid={`printed-violation-${i}`}
          aria-pressed={selected === i}
          onClick={() => onSelect(selected === i ? null : i)}
          className={`block w-full rounded-md border p-2 text-left ${
            selected === i ? 'border-destructive bg-destructive/10' : 'border-border/60'
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="destructive" className="font-mono text-[10px]">
              {v.kind}
            </Badge>
            <span className="font-medium">
              {v.slots.map((s) => `${DAY_NAMES[s.day]} P${s.period}`).join(', ')}
            </span>
          </div>
          <ul className="mt-1 text-muted-foreground">
            {v.session_ids.map((id) => (
              <li key={id}>
                {v.sessions[id]?.cohort}: {v.sessions[id]?.printed ?? id}
              </li>
            ))}
          </ul>
        </button>
      ))}
    </CardContent>
  </Card>
);
