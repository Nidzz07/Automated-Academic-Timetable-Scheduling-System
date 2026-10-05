import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { InfeasibilityDiagnosisPanel } from '../InfeasibilityDiagnosisPanel';
import infeasibleFixture from '@/fixtures/solution_v1.infeasible.example.json';
import { InfeasibleSolution } from '@/types/solution';

describe('Infeasibility Diagnosis Panel', () => {
  const infeasibleSolution = infeasibleFixture as unknown as InfeasibleSolution;

  it('renders the infeasible status and solver metadata strip', () => {
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={infeasibleSolution} />);

    // Assert main panel and heading
    expect(screen.getByTestId('infeasibility-panel')).toBeInTheDocument();
    expect(screen.getByText(/Infeasible Timetable Instance/i)).toBeInTheDocument();
    expect(screen.getByText(/Status: INFEASIBLE/i)).toBeInTheDocument();

    // Assert solver diagnostic metadata
    expect(screen.getByText(/backtracking\(forward-checking, mrv\) \+ mus-extraction\(deletion-based\)/i)).toBeInTheDocument();
    expect(screen.getByText(/1284.5 ms/i)).toBeInTheDocument();
    expect(screen.getByText(/5 \/ 8 sessions placed/i)).toBeInTheDocument();
    expect(screen.getByText(/9,417 backtracks/i)).toBeInTheDocument();
  });

  it('renders all constraints in the minimal conflicting subset (MUS) with kinds and entity ids', () => {
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={infeasibleSolution} />);

    const musContainer = screen.getByTestId('minimal-conflicting-set');
    expect(musContainer).toBeInTheDocument();

    const expectedConstraints = infeasibleSolution.diagnosis.minimal_conflicting_set;
    expect(expectedConstraints.length).toBe(3);

    expectedConstraints.forEach((c) => {
      const card = screen.getByTestId(`conflicting-constraint-${c.constraint_id}`);
      expect(card).toBeInTheDocument();

      // Check kind badge
      expect(within(card).getByTestId(`constraint-kind-${c.kind}`)).toHaveTextContent(c.kind);

      // Check institutional description
      expect(within(card).getByText(c.description)).toBeInTheDocument();

      // Check entity ids
      c.entity_ids.forEach((id) => {
        expect(within(card).getAllByText(id).length).toBeGreaterThanOrEqual(1);
      });
    });

    // Check specific institutional constraint kinds from real data
    expect(screen.getByTestId('constraint-kind-LAB_CONTIGUITY')).toBeInTheDocument();
    expect(screen.getByTestId('constraint-kind-ROOM_CAPACITY')).toBeInTheDocument();
    expect(screen.getByTestId('constraint-kind-PINNED_BLOCK')).toBeInTheDocument();
  });

  it('renders the suggested relaxation identifying the constraint to drop or loosen in institutional terms', () => {
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={infeasibleSolution} />);

    const relaxationBox = screen.getByTestId('suggested-relaxation');
    expect(relaxationBox).toBeInTheDocument();

    // Must name the target constraint_id
    const targetBadge = within(relaxationBox).getByTestId('relaxation-constraint-id');
    expect(targetBadge).toHaveTextContent('Target: lab-rooms.monday-10.00');

    // Must display readable institutional description (e.g. room 606 unsure)
    expect(
      within(relaxationBox).getByText(/Classify room 606 as a lab/i)
    ).toBeInTheDocument();
    expect(
      within(relaxationBox).getByText(/The room inventory records its usage as 'unsure'/i)
    ).toBeInTheDocument();
  });
});
