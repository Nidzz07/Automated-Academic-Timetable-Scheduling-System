import React from 'react';
import { AlertTriangle } from 'lucide-react';
import { loadLimitChange, overLimitText } from '@/lib/wording';

/** Red with an icon and words, never colour alone. */
const Warning: React.FC<{ text: string; className?: string }> = ({ text, className = '' }) => (
  <span
    data-testid="load-over-limit"
    className={`inline-flex items-center gap-1.5 font-semibold text-destructive dark:text-red-300 ${className}`}
  >
    <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0" />
    {text}
  </span>
);

/**
 * A weekly load above the limit (D11, S-LOAD16): "Over 16 h limit: 17 h". Nothing when the load is
 * within it or the limit is unknown.
 */
export const OverLimitWarning: React.FC<{ hours: number; limit: number | null; className?: string }> = ({ hours, limit, className }) => {
  const text = overLimitText(hours, limit);
  return text ? <Warning text={text} className={className} /> : null;
};

/**
 * One line for a load that changes around the limit: "18 h → 19 h, over the 16 h limit" as the one
 * warning, or plainly when it comes back within it. Nothing when neither side is above it.
 */
export const LoadLimitChange: React.FC<{ before: number; after: number; limit: number | null; className?: string }> = ({
  before,
  after,
  limit,
  className,
}) => {
  const change = loadLimitChange(before, after, limit);
  if (!change) return null;
  return change.over ? (
    <Warning text={change.text} className={className} />
  ) : (
    <span data-testid="load-back-within" className={className}>
      {change.text}
    </span>
  );
};
