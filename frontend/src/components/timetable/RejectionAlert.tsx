import React, { useEffect, useRef } from 'react';
import { AlertCircle, X, Wrench } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface RejectionAlertProps {
  reason: string;
  /** Every clash at the target, one per line, under the reason */
  clashes?: string[];
  sessionId?: string;
  originalSlotLabel?: string;
  onDismiss: () => void;
  /** Offered for a clashing drag on a backend instance: repair the timetable around the move (S14c) */
  onRepair?: () => void;
}

/**
 * Above the grid, and stuck to the top of the window while the grid is scrolled, so a refused drop
 * shows where the user is looking. It takes the focus (and gives it back when it goes) without
 * scrolling the page; role="alert" announces it.
 */
export const RejectionAlert: React.FC<RejectionAlertProps> = ({
  reason,
  clashes,
  sessionId,
  originalSlotLabel,
  onDismiss,
  onRepair,
}) => {
  const alert = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    alert.current?.focus({ preventScroll: true });
    return () => before?.focus({ preventScroll: true });
  }, []);

  return (
    <div
      ref={alert}
      tabIndex={-1}
      data-testid="rejection-alert"
      role="alert"
      className="sticky top-2 z-40 flex max-h-[60vh] flex-col justify-between gap-3 overflow-y-auto rounded-lg border-2 border-destructive/70 bg-red-50 p-4 shadow-lg outline-none dark:bg-red-950 sm:flex-row sm:items-start"
    >
      <div className="flex items-start gap-3">
        <AlertCircle aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
        <div className="space-y-1">
          <h2 className="text-lg font-semibold">This move is not allowed</h2>
          <p data-testid="rejection-reason" className="font-semibold">
            {reason}
          </p>
          {clashes && clashes.length > 0 && (
            <ul data-testid="rejection-clashes" className="list-disc pl-5">
              {clashes.map((c) => (
                <li key={c} data-testid="rejection-clash">
                  {c}
                </li>
              ))}
            </ul>
          )}
          {(sessionId || originalSlotLabel) && (
            <p className="text-xs">
              {sessionId && <span>Session <strong>{sessionId}</strong> </span>}
              {originalSlotLabel && <span>stays at its original slot: <strong>{originalSlotLabel}</strong>.</span>}
            </p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2 self-end sm:self-start">
        {onRepair && (
          <Button size="sm" onClick={onRepair} className="gap-1" data-testid="repair-around-this">
            <Wrench className="h-4 w-4" />
            Repair around this
          </Button>
        )}
        <Button variant="outline" size="sm" onClick={onDismiss} className="gap-1">
          <X className="h-4 w-4" />
          Dismiss
        </Button>
      </div>
    </div>
  );
};
