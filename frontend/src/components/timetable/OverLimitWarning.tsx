import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { overLimitText } from '@/lib/wording';

/**
 * A weekly load above the limit (D11, S-LOAD16), in red with an icon and words, never colour alone:
 * "Over 16 h limit: 17 h". Nothing when the load is within it or the limit is unknown.
 */
export const OverLimitWarning: React.FC<{ hours: number; limit: number | null; className?: string }> = ({
  hours,
  limit,
  className = '',
}) => {
  const text = overLimitText(hours, limit);
  if (!text) return null;
  return (
    <span
      data-testid="load-over-limit"
      className={`inline-flex items-center gap-1.5 font-semibold text-destructive dark:text-red-300 ${className}`}
    >
      <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
      {text}
    </span>
  );
};
