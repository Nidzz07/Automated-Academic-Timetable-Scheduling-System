import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { TimetableGrid } from '../TimetableGrid';
import { getSolvedSolutionFixture } from '@/lib/timetableData';
import { SolvedSolution, InfeasibleSolution, SolutionContract } from '@/types/solution';

describe('TimetableGrid Component', () => {
  it('renders an 8-period x 5-day week grid from the static fixture', () => {
    const fixture = getSolvedSolutionFixture();
    render(<TimetableGrid solution={fixture} />);

    // Assert grid is present
    expect(screen.getByTestId('timetable-grid')).toBeInTheDocument();

    // Assert 5 day headers (Monday to Friday)
    expect(screen.getByTestId('day-header-0')).toHaveTextContent(/monday/i);
    expect(screen.getByTestId('day-header-1')).toHaveTextContent(/tuesday/i);
    expect(screen.getByTestId('day-header-2')).toHaveTextContent(/wednesday/i);
    expect(screen.getByTestId('day-header-3')).toHaveTextContent(/thursday/i);
    expect(screen.getByTestId('day-header-4')).toHaveTextContent(/friday/i);

    // Assert 8 teaching periods
    for (let p = 0; p < 8; p++) {
      expect(screen.getByTestId(`period-row-${p}`)).toBeInTheDocument();
    }

    // Assert break rows are present
    expect(screen.getByTestId('break-row-short-break')).toBeInTheDocument();
    expect(screen.getByTestId('break-row-lunch-break')).toBeInTheDocument();
  });

  it('renders Case 1: A double-period lab block spanning two adjacent periods', () => {
    const fixture = getSolvedSolutionFixture();
    render(<TimetableGrid solution={fixture} />);

    // Find the parallel lab block
    const labBlock = screen.getByTestId('parallel-lab-block');
    expect(labBlock).toBeInTheDocument();
    expect(labBlock).toHaveAttribute('data-duration-periods', '2');

    // The cell holding this lab block must have rowSpan = 2 and spans adjacent flag
    const cell = screen.getByTestId('grid-cell-0-1');
    expect(cell).toHaveAttribute('data-rowspan', '2');
    expect(cell).toHaveAttribute('data-spans-adjacent', 'true');
    expect(cell).toContainElement(labBlock);

    // The banner indicates it spans 2 periods and straddles the short break
    expect(within(labBlock).getByText(/2 Periods \(10:00 – 12:15\)/i)).toBeInTheDocument();
    expect(within(labBlock).getByText(/Straddles 11:00 Short Break/i)).toBeInTheDocument();
  });

  it('renders Case 2: Four parallel batch sessions occupying the same lab slot in different sub-rooms', () => {
    const fixture = getSolvedSolutionFixture();
    render(<TimetableGrid solution={fixture} />);

    const labBlock = screen.getByTestId('parallel-lab-block');
    const batchesGrid = within(labBlock).getByTestId('parallel-batches-grid');
    expect(batchesGrid).toBeInTheDocument();

    // Verify all 4 parallel batch sessions from the contract fixture exist
    const sess1 = within(batchesGrid).getByTestId('batch-session-sess-0001');
    const sess2 = within(batchesGrid).getByTestId('batch-session-sess-0002');
    const sess3 = within(batchesGrid).getByTestId('batch-session-sess-0003');
    const sess4 = within(batchesGrid).getByTestId('batch-session-sess-0004');

    expect(sess1).toBeInTheDocument();
    expect(sess2).toBeInTheDocument();
    expect(sess3).toBeInTheDocument();
    expect(sess4).toBeInTheDocument();

    // Verify Batches A, B, C, D labels
    expect(sess1).toHaveAttribute('data-batch', 'Batch A');
    expect(sess2).toHaveAttribute('data-batch', 'Batch B');
    expect(sess3).toHaveAttribute('data-batch', 'Batch C');
    expect(sess4).toHaveAttribute('data-batch', 'Batch D');

    // Verify different sub-rooms
    expect(sess1).toHaveAttribute('data-subroom', '702-A');
    expect(sess2).toHaveAttribute('data-subroom', '702-B');
    expect(sess3).toHaveAttribute('data-subroom', '603-2');
    expect(sess4).toHaveAttribute('data-subroom', '608');

    // Verify subjects and faculty in each batch card
    expect(within(sess1).getByText(/OS Lab/i)).toBeInTheDocument();
    expect(within(sess1).getByText('AGN')).toBeInTheDocument();

    expect(within(sess2).getByText(/DAA Lab/i)).toBeInTheDocument();
    expect(within(sess2).getByText('NR')).toBeInTheDocument();

    expect(within(sess3).getByText(/CCN Lab/i)).toBeInTheDocument();
    expect(within(sess3).getByText('JS')).toBeInTheDocument();

    expect(within(sess4).getByText(/PCS Lab/i)).toBeInTheDocument();
    expect(within(sess4).getByText('DN')).toBeInTheDocument();
  });

  it('renders Case 3: A combined-division lecture as a single session spanning its full cohort', () => {
    const fixture = getSolvedSolutionFixture();
    render(<TimetableGrid solution={fixture} />);

    // sess-0005 is DAA on Day 1 Period 0 in Room 508 with cohort "SE C & D" (140 students)
    const combinedLectures = screen.getAllByTestId('combined-division-lecture');
    expect(combinedLectures.length).toBeGreaterThanOrEqual(1);

    const daaCombined = combinedLectures.find((el) => el.getAttribute('data-session-id') === 'sess-0005');
    expect(daaCombined).toBeDefined();

    if (daaCombined) {
      expect(daaCombined).toHaveAttribute('data-cohort', 'SE C & D');
      expect(within(daaCombined).getByText(/Combined Lecture/i)).toBeInTheDocument();
      expect(within(daaCombined).getByText(/Full Union Cohort: SE C & D/i)).toBeInTheDocument();
      expect(within(daaCombined).getByText(/140 students/i)).toBeInTheDocument();
      expect(within(daaCombined).getByText(/Room 508/i)).toBeInTheDocument();
      expect(within(daaCombined).getByText('NR')).toBeInTheDocument();
    }
  });

  it('renders Case 4: A pinned block (immovable occupancy) rendered distinctly from a solver-placed session', () => {
    const fixture = getSolvedSolutionFixture();
    render(<TimetableGrid solution={fixture} />);

    // Institutional pinned block (e.g. MDM - I THEORY)
    const pinnedBlocks = screen.getAllByTestId('pinned-block');
    expect(pinnedBlocks.length).toBeGreaterThanOrEqual(1);

    const mdmBlock = pinnedBlocks.find((el) => el.getAttribute('data-pinned-id') === 'pin-0001');
    expect(mdmBlock).toBeDefined();

    if (mdmBlock) {
      // Must carry pinned badges and distinct immovable indicators
      expect(within(mdmBlock).getByText(/PINNED BLOCK/i)).toBeInTheDocument();
      expect(within(mdmBlock).getByText(/Immovable/i)).toBeInTheDocument();
      expect(within(mdmBlock).getByText(/MDM - I THEORY/i)).toBeInTheDocument();
      expect(within(mdmBlock).getByText(/Room 508/i)).toBeInTheDocument();

      // Must have distinct styling (bg-pinned-pattern and border-slate)
      expect(mdmBlock.className).toContain('bg-pinned-pattern');
      expect(mdmBlock.className).toContain('border-slate');
    }

    // Fixed pre-allocated solver session (sess-0008, ET Theory) also renders with fixed badge
    const sess8 = screen.getByTestId('session-cell-sess-0008');
    expect(sess8).toBeInTheDocument();
    expect(within(sess8).getByText(/Fixed Slot/i)).toBeInTheDocument();
    expect(sess8.className).toContain('bg-pinned-pattern');
  });

  it('validates TypeScript contract types mirror solution_v1.schema.json', () => {
    const solved: SolvedSolution = getSolvedSolutionFixture();
    expect(solved.schema_version).toBe('solution.v1');
    expect(solved.status).toBe('solved');
    expect(Array.isArray(solved.assignment)).toBe(true);
    expect(solved.assignment.length).toBe(8);
    expect(solved.quality.score).toBe(93.2);

    // Type checking: an invalid status or missing assignment causes compile error
    const testUnion: SolutionContract = solved;
    if (testUnion.status === 'solved') {
      expect(testUnion.assignment).toBeDefined();
    } else {
      // Infeasible type test
      const infeasible: InfeasibleSolution = testUnion;
      expect(infeasible.diagnosis).toBeDefined();
    }
  });
});
