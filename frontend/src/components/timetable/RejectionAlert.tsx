import React from 'react';
import { AlertCircle, X, RotateCcw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface RejectionAlertProps {
  reason: string;
  sessionId?: string;
  originalSlotLabel?: string;
  onDismiss: () => void;
}

export const RejectionAlert: React.FC<RejectionAlertProps> = ({
  reason,
  sessionId,
  originalSlotLabel,
  onDismiss,
}) => {
  return (
    <div
      data-testid="rejection-alert"
      role="alert"
      className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border-2 border-rose-500/40 bg-rose-500/10 p-3.5 shadow-md backdrop-blur-md animate-in fade-in slide-in-from-top-2 duration-200"
    >
      <div className="flex items-start gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-rose-500 text-white shadow-xs">
          <AlertCircle className="h-4 w-4" />
        </div>
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-rose-800 dark:text-rose-300">
              Schedule Move Rejected
            </span>
            <span className="inline-flex items-center gap-1 rounded bg-rose-200/60 dark:bg-rose-900/60 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-rose-900 dark:text-rose-200">
              <RotateCcw className="h-2.5 w-2.5" />
              State Cleanly Reverted
            </span>
          </div>
          <p
            data-testid="rejection-reason"
            className="text-xs font-semibold text-foreground/95"
          >
            {reason}
          </p>
          {(sessionId || originalSlotLabel) && (
            <p className="text-[11px] text-muted-foreground">
              {sessionId && <span>Session <strong>{sessionId}</strong> </span>}
              {originalSlotLabel && <span>restored to original slot: <strong>{originalSlotLabel}</strong>. Selection preserved.</span>}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 self-end sm:self-center shrink-0">
        <Button
          variant="outline"
          size="sm"
          onClick={onDismiss}
          className="text-xs h-7 px-2.5 border-rose-300 dark:border-rose-800 hover:bg-rose-500/10"
        >
          <X className="h-3.5 w-3.5 mr-1" />
          Dismiss
        </Button>
      </div>
    </div>
  );
};
