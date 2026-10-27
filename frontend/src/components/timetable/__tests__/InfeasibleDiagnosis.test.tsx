import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { InfeasibilityDiagnosisPanel } from '../InfeasibilityDiagnosisPanel';
import infeasibleFixture from '@contracts/examples/solution_v1.infeasible.example.json';
import infeasibleV2Fixture from '@contracts/examples/solution_v2.infeasible.example.json';
import presolveFixture from '@contracts/examples/solution_v2.presolve.example.json';
import { isInfeasibleSolution } from '@/adapters/solution';
import { parseSolution } from '@/api/contractValidation';

describe('Infeasibility Diagnosis Panel on a presolve certificate (contract row 9, D43)', () => {
  it('renders solution_v2.presolve.example.json with the presolve label and its conflicting set', () => {
    const presolve = parseSolution(presolveFixture);
    if (!isInfeasibleSolution(presolve)) throw new Error('expected an infeasible payload');
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={presolve} />);

    expect(screen.getByTestId('diagnosis-method')).toHaveTextContent('Presolve');
    expect(screen.getByText('Proved infeasible by a counting check (not minimal)')).toBeInTheDocument();
    for (const c of presolve.diagnosis.minimal_conflicting_set) {
      expect(screen.getByTestId(`conflicting-constraint-${c.constraint_id}`)).toBeInTheDocument();
    }
  });
});

describe('Infeasibility Diagnosis Panel', () => {
  const infeasibleSolution = parseSolution(infeasibleFixture);
  if (!isInfeasibleSolution(infeasibleSolution)) throw new Error('expected an infeasible payload');

  it('renders the infeasible status and solver metadata strip', () => {
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={infeasibleSolution} />);

    // Assert main panel and heading
    expect(screen.getByTestId('infeasibility-panel')).toBeInTheDocument();
    expect(screen.getByText(/Infeasible Timetable Instance/i)).toBeInTheDocument();
    expect(screen.getByText(/Status: INFEASIBLE/i)).toBeInTheDocument();

    // Assert solver diagnostic metadata
    expect(screen.getByText(/backtracking\(forward-checking, mrv\) \+ mus-extraction\(deletion-based\)/i)).toBeInTheDocument();
    expect(screen.getByText('1.3 s')).toBeInTheDocument();
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

    // solution.v1 states no method and carries no partial placement
    expect(screen.getByTestId('diagnosis-method')).toHaveTextContent(/Method not stated/i);
    expect(screen.queryByTestId('partial-placement')).not.toBeInTheDocument();
  });
});

describe('Infeasibility Diagnosis Panel (solution.v2)', () => {
  const parse = (raw: unknown) => {
    const sol = parseSolution(raw);
    if (!isInfeasibleSolution(sol)) throw new Error('expected an infeasible payload');
    return sol;
  };

  it('shows the mus method, constraint cells, the typed relaxation with its verification and the partial placement', () => {
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={parse(infeasibleV2Fixture)} />);

    expect(screen.getByTestId('diagnosis-method')).toHaveTextContent('MUS Extraction');
    expect(screen.getByTestId('constraint-kind-ROOM_OCCUPANCY')).toBeInTheDocument();
    expect(screen.getByTestId('constraint-slots-lab-rooms.monday-10.00')).toHaveTextContent(
      'Cells: Monday P1, Monday P3'
    );
    expect(screen.queryByTestId('constraint-slots-labblk-0001.contiguity')).not.toBeInTheDocument();
    expect(screen.getByTestId('relaxation-action')).toHaveTextContent(
      'Action: RECLASSIFY_ROOM · verification: restored (212 ms)'
    );

    const partial = screen.getByTestId('partial-placement');
    expect(partial).toHaveTextContent(/diagnostic only — not a timetable\): 4 placed, 4 unplaced/i);
    expect(partial).toHaveTextContent('sess-0005 (Tuesday P0)');
    expect(screen.getByTestId('unplaced-sessions')).toHaveTextContent(
      'Unplaced: sess-0001, sess-0002, sess-0003, sess-0004'
    );
  });

  it('shows search exhaustion with no conflicting set and no relaxation', () => {
    const raw = JSON.parse(JSON.stringify(infeasibleV2Fixture));
    raw.diagnosis.method = 'search_exhaustion';
    raw.diagnosis.minimal_conflicting_set = [];
    delete raw.diagnosis.suggested_relaxation;
    render(<InfeasibilityDiagnosisPanel infeasibleSolution={parse(raw)} onApplyRelaxation={() => {}} />);

    expect(screen.getByTestId('diagnosis-method')).toHaveTextContent('Search Exhaustion');
    expect(screen.getByText(/no explanation was extracted/i)).toBeInTheDocument();
    expect(screen.queryByTestId('minimal-conflicting-set')).not.toBeInTheDocument();
    expect(screen.queryByTestId('suggested-relaxation')).not.toBeInTheDocument();
    expect(screen.getByTestId('partial-placement')).toBeInTheDocument();
  });
});
