import React from 'react';
import { UI } from '@/lib/wording';

/**
 * metadata.algorithm as the solver writes it, for whoever asks: closed by default, small, and
 * wrapping only at its spaces and hyphens, never in the middle of a word.
 */
export const MethodDetails: React.FC<{ algorithm: string }> = ({ algorithm }) => (
  <details data-testid="method-details" className="text-[11px] text-muted-foreground">
    <summary className="cursor-pointer font-semibold">{UI.details}</summary>
    <code data-testid="quality-method-code" className="block whitespace-normal break-normal font-mono text-[11px]">
      {algorithm}
    </code>
  </details>
);
