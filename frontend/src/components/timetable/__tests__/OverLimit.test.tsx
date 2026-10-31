import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FacultyWorkloadCard } from '../FacultyWorkloadCard';
import { OverLimitWarning } from '../OverLimitWarning';
import type { QualityRule } from '@/adapters/solution';

// S14p: a weekly load above the S-LOAD16 limit (D11) is a red warning with an icon and words
const load = (theory: number, labs: number, fixed = 0) => ({
  theory,
  practical: labs * 2,
  scheduled: theory + labs * 2,
  fixed,
  total: theory + labs * 2 + fixed,
});
const card = (l: ReturnType<typeof load>, rule?: QualityRule) => (
  <FacultyWorkloadCard facultyName="Jignesh Sisodia" facultyInitials="JS" load={l} loadRule={rule} />
);

// the solver's own sentence: the frontend takes the limit from it, not from a constant of its own
const loadRule: QualityRule = {
  rule_id: 'S-LOAD16',
  status: 'evaluated',
  weight: 1,
  raw: 6,
  penalty: 6,
  explanation: '6 faculty members above 16 h a week - fac-jignesh-sisodia 17 h.',
};

describe('over the weekly limit (S-LOAD16)', () => {
  it('shows a load above the limit in words with an icon, in red', () => {
    render(card(load(9, 4), loadRule));
    expect(screen.getByTestId('workload-formula-badge')).toHaveTextContent('9T + 8P = 17 h');
    const warning = screen.getByTestId('load-over-limit');
    expect(warning).toHaveTextContent('Over 16 h limit: 17 h');
    expect(warning.querySelector('svg')).not.toBeNull();
    expect(warning.className).toContain('text-destructive');
  });

  it('shows nothing at or below the limit', () => {
    render(card(load(8, 4), loadRule));
    expect(screen.getByTestId('workload-formula-badge')).toHaveTextContent('= 16 h');
    expect(screen.queryByTestId('load-over-limit')).not.toBeInTheDocument();
  });

  it('shows nothing when the solver did not evaluate S-LOAD16, so no limit is known', () => {
    const notEvaluated: QualityRule = { rule_id: 'S-LOAD16', status: 'not_evaluated', weight: 1, reason: 'r' };
    render(card(load(20, 0), notEvaluated));
    expect(screen.queryByTestId('load-over-limit')).not.toBeInTheDocument();
  });

  it('counts fixed items: 6 h of sessions and 12 h of fixed items is over the limit, and says both parts', () => {
    render(card(load(6, 0, 12), loadRule));
    expect(screen.getByTestId('workload-formula-badge')).toHaveTextContent('6T + 0P + 12 fixed = 18 h');
    expect(screen.getByTestId('workload-parts')).toHaveTextContent('18 h: 6 h scheduled + 12 h fixed items');
    expect(screen.getByTestId('load-over-limit')).toHaveTextContent('Over 16 h limit: 18 h');
  });

  it('OverLimitWarning on its own (the substitution before → after uses it too)', () => {
    const { rerender } = render(<OverLimitWarning hours={18} limit={16} />);
    expect(screen.getByTestId('load-over-limit')).toHaveTextContent('Over 16 h limit: 18 h');
    rerender(<OverLimitWarning hours={15} limit={16} />);
    expect(screen.queryByTestId('load-over-limit')).not.toBeInTheDocument();
  });
});
