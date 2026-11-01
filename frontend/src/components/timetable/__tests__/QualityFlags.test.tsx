import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { QualityScoreCard } from '../QualityScoreCard';
import { FacultyWorkloadCard } from '../FacultyWorkloadCard';
import { isSolvedSolution, toQualityView } from '@/adapters/solution';
import { parseSolution } from '@/api/contractValidation';
import solvedV2Fixture from '@contracts/examples/solution_v2.solved.example.json';
import solvedV1Fixture from '@contracts/examples/solution_v1.solved.example.json';

/** The shape S8 emits until S10: score 100.0, every rule not_evaluated at weight 0.0. */
function standIn() {
  const ids = ['S-GAP', 'S-B2B', 'S-LOAD16', 'FAC_LOAD_IMBALANCE'];
  return {
    ...JSON.parse(JSON.stringify(solvedV2Fixture)),
    quality: {
      score: 100.0,
      rules_version: 'none',
      not_evaluated_rule_ids: ids,
      breakdown: ids.map((rule_id) => ({
        rule_id,
        status: 'not_evaluated',
        weight: 0.0,
        reason: 'Quality rules are not loaded yet.',
      })),
    },
  };
}

function renderCard(raw: unknown) {
  const sol = parseSolution(raw);
  if (!isSolvedSolution(sol)) throw new Error('expected a solved payload');
  render(<QualityScoreCard quality={toQualityView(sol)} metadata={sol.metadata} />);
}

describe('Quality flags panel (D34: solver output, displayed as given)', () => {
  it('shows each of the four rules with the solver’s explanation and penalty', () => {
    renderCard(solvedV2Fixture);

    for (const id of ['S-GAP', 'S-B2B', 'FAC_LOAD_IMBALANCE']) {
      const row = screen.getByTestId(`quality-rule-${id}`);
      expect(within(row).getByTestId('rule-penalty')).toBeInTheDocument();
      expect(within(row).queryByTestId('rule-not-evaluated')).not.toBeInTheDocument();
    }
    // The solver names the affected faculty, division and days in its explanation
    expect(screen.getByTestId('quality-rule-FAC_LOAD_IMBALANCE')).toHaveTextContent(
      'AGN teaches 2 h on Monday (the SE-Comp B OS lab)'
    );
    expect(screen.getByTestId('quality-rule-FAC_LOAD_IMBALANCE')).toHaveTextContent('Found 2 h → −1.0 points (0.5 points each)');
    // plain title and meaning first, the rule id only as secondary text
    expect(screen.getByTestId('quality-rule-FAC_LOAD_IMBALANCE')).toHaveTextContent('Uneven teaching days');
  });

  it('shows a not_evaluated rule as "not evaluated" with its reason, never a number', () => {
    renderCard(solvedV2Fixture);

    const row = screen.getByTestId('quality-rule-S-LOAD16');
    expect(within(row).getByTestId('rule-not-evaluated')).toHaveTextContent('Not checked');
    expect(row).toHaveTextContent(/not a full department week/);
    expect(within(row).queryByTestId('rule-penalty')).not.toBeInTheDocument();
    expect(row).not.toHaveTextContent(/point|Found/);

    expect(screen.getByTestId('quality-partial')).toHaveTextContent('Partial: Teachers over the weekly limit not checked');
    expect(screen.getByText(/rules version 1/)).toBeInTheDocument();
  });

  it('shows the score with a Partial badge when some rules are evaluated', () => {
    renderCard(solvedV2Fixture);
    expect(screen.getByTestId('quality-score')).toHaveTextContent('99');
    expect(screen.queryByTestId('quality-score-unavailable')).not.toBeInTheDocument();
  });

  it('hides the stand-in score when every rule is not_evaluated', () => {
    renderCard(standIn());
    expect(screen.getByTestId('quality-score-unavailable')).toHaveTextContent(
      'Score not available until rules are evaluated'
    );
    expect(screen.queryByTestId('quality-score')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quality-partial')).not.toBeInTheDocument();
    expect(screen.queryByText('100')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('rule-not-evaluated')).toHaveLength(4);
  });

  it('shows a v1 breakdown as evaluated, with no partial flag', () => {
    renderCard(solvedV1Fixture);
    expect(screen.queryByTestId('rule-not-evaluated')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quality-partial')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('rule-penalty')).toHaveLength(2);
  });
});

describe('Faculty load status (S-LOAD16 only)', () => {
  const load = { theory: 2, practical: 4, scheduled: 6, fixed: 0, total: 6 };

  it('shows the solver’s explanation when S-LOAD16 was evaluated', () => {
    const rule = {
      rule_id: 'S-LOAD16',
      status: 'evaluated' as const,
      weight: 1,
      raw: 0,
      penalty: 0,
      explanation: 'No faculty member teaches more than 16 h a week.',
    };
    render(<FacultyWorkloadCard facultyName="A. G. Nikam" facultyInitials="AGN" load={load} loadRule={rule} />);
    expect(screen.getByTestId('load-status')).toHaveTextContent(`Within the 16 h limit.`);
  });

  it('shows "not evaluated", or that the solver reported nothing, otherwise', () => {
    const rule = { rule_id: 'S-LOAD16', status: 'not_evaluated' as const, weight: 0, reason: 'r' };
    const { unmount } = render(
      <FacultyWorkloadCard facultyName="A. G. Nikam" facultyInitials="AGN" load={load} loadRule={rule} />
    );
    expect(screen.getByTestId('load-status')).toHaveTextContent('not evaluated');
    unmount();

    render(<FacultyWorkloadCard facultyName="A. G. Nikam" facultyInitials="AGN" load={load} />);
    expect(screen.getByTestId('load-status')).toHaveTextContent('not reported by the solver');
  });
});
