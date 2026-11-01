import React from 'react';
import { UI } from '@/lib/wording';

const SMALL_CODE = 'block whitespace-normal break-normal font-mono text-[11px]';

/**
 * Internal codes, for whoever asks: closed by default, small, and wrapping only at spaces and
 * hyphens, never in the middle of a word. The main text around it stays plain sentences.
 */
export const CodeDetails: React.FC<{ testId?: string; children: React.ReactNode }> = ({ testId, children }) => (
  <details data-testid={testId} className="text-[11px] text-muted-foreground">
    <summary className="cursor-pointer font-semibold">{UI.details}</summary>
    {children}
  </details>
);

/** metadata.algorithm as the solver writes it, and how a diagnosis was reached (diagnosis.method) if it has one. */
export const MethodDetails: React.FC<{ algorithm: string; diagnosisMethod?: string }> = ({ algorithm, diagnosisMethod }) => (
  <CodeDetails testId="method-details">
    <code data-testid="quality-method-code" className={SMALL_CODE}>
      {algorithm}
    </code>
    {diagnosisMethod && (
      <code data-testid="diagnosis-method" className={SMALL_CODE}>
        {diagnosisMethod}
      </code>
    )}
  </CodeDetails>
);

/** One line of codes inside CodeDetails. */
export const CodeLine: React.FC<{ testId?: string; children: React.ReactNode }> = ({ testId, children }) => (
  <code data-testid={testId} className={SMALL_CODE}>
    {children}
  </code>
);
