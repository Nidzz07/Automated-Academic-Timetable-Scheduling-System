import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { TimetableGrid } from '../TimetableGrid';
import { getSolvedSolutionFixture } from '@/adapters/timetable';
import { SolvedSolution, SolutionContract } from '@/adapters/solution';
import { validateContract } from '@/api/contractValidation';
import d6GridExample from '@contracts/examples/edge_list_v1.d6_grid.example.json';

describe('TimetableGrid Component', () => {
  it('renders the edge list\'s 8 teaching periods x 5 days, with its break periods as break rows', () => {
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

    // edge_list_v1.example.json: teaching_periods [0, 1, 3, 4, 6, 7, 8, 9] of 10
    for (const p of [0, 1, 3, 4, 6, 7, 8, 9]) {
      expect(screen.getByTestId(`period-row-${p}`)).toHaveTextContent(`P${p}`);
    }
    expect(screen.getByTestId('break-row-2')).toBeInTheDocument();
    expect(screen.getByTestId('break-row-5')).toBeInTheDocument();
    expect(screen.queryByText(/\d\d:\d\d/)).not.toBeInTheDocument();
  });

  it('renders Case 1: A double-period lab block spanning two adjacent periods', () => {
    const fixture = getSolvedSolutionFixture();
    render(<TimetableGrid solution={fixture} />);

    // Find the parallel lab block
    const labBlock = screen.getByTestId('parallel-lab-block');
    expect(labBlock).toBeInTheDocument();
    expect(labBlock).toHaveAttribute('data-duration-periods', '2');

    // The cell spans P1, the P2 break row and P3: rowSpan 3
    const cell = screen.getByTestId('grid-cell-0-1');
    expect(cell).toHaveAttribute('data-rowspan', '3');
    expect(cell).toHaveAttribute('data-spans-adjacent', 'true');
    expect(cell).toContainElement(labBlock);

    // The banner states its periods and the break it straddles, from the edge list
    expect(within(labBlock).getByText(/2 periods \(P1–P3\)/i)).toBeInTheDocument();
    expect(within(labBlock).getByText(/4 batches in parallel/i)).toBeInTheDocument();
    expect(within(labBlock).getByText(/Spans break P2/i)).toBeInTheDocument();
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

    // pinned_occupancy Thursday P4: room 508, SE-Comp B (the edge list carries no label)
    expect(screen.getAllByTestId('pinned-block')).toHaveLength(2);
    const pinned = within(screen.getByTestId('grid-cell-3-4')).getByTestId('pinned-block');

    // Must carry pinned badges and distinct immovable indicators
    expect(within(pinned).getByText(/PINNED BLOCK/i)).toBeInTheDocument();
    expect(within(pinned).getByText(/Immovable/i)).toBeInTheDocument();
    expect(within(pinned).getByText(/Pinned occupancy/i)).toBeInTheDocument();
    expect(within(pinned).getByText(/Room 508/i)).toBeInTheDocument();
    expect(within(pinned).getByText(/Cohort: SE-Comp B/i)).toBeInTheDocument();
    expect(screen.queryByText(/MDM/i)).not.toBeInTheDocument();

    // Must have distinct styling (bg-pinned-pattern and border-slate)
    expect(pinned.className).toContain('bg-pinned-pattern');
    expect(pinned.className).toContain('border-slate');

    // Fixed pre-allocated solver session (sess-0008, ET Theory) also renders with fixed badge
    const sess8 = screen.getByTestId('session-cell-sess-0008');
    expect(sess8).toBeInTheDocument();
    expect(within(sess8).getByText(/Fixed Slot/i)).toBeInTheDocument();
    expect(sess8.className).toContain('bg-pinned-pattern');
  });

  it('validates TypeScript contract types mirror solution_v2.schema.json', () => {
    const solved: SolvedSolution = getSolvedSolutionFixture();
    expect(solved.schema_version).toBe('solution.v2');
    expect(solved.status).toBe('solved');
    expect(Array.isArray(solved.assignment)).toBe(true);
    expect(solved.assignment.length).toBe(8);
    expect(solved.quality.score).toBe(99.0);

    // Type checking: a solved payload always carries an assignment
    const testUnion: SolutionContract = solved;
    expect(testUnion.status === 'solved' && testUnion.assignment).toBeTruthy();
  });
});

describe('TimetableGrid on the D6 grid example (edge_list_v1.d6_grid.example.json)', () => {
  const d6 = validateContract('edge_list', d6GridExample);

  it('shows SE-Comp A with lunch at P5 every day and P4 as a teaching period', () => {
    render(<TimetableGrid edgeList={d6} solution={null} cohortFilter="coh-div-se-a" />);
    expect(screen.getByTestId('break-row-2')).toBeInTheDocument();
    expect(screen.getByTestId('period-row-4')).toBeInTheDocument();
    expect(screen.getByTestId('period-row-5')).toBeInTheDocument();
    for (const day of [0, 1, 2, 3, 4]) {
      expect(screen.getByTestId(`lunch-cell-${day}-5`)).toHaveTextContent('Lunch');
      expect(screen.queryByTestId(`lunch-cell-${day}-4`)).not.toBeInTheDocument();
    }
  });

  it('shows TE-Comp A with lunch at P4 every day, not P5', () => {
    render(<TimetableGrid edgeList={d6} solution={null} cohortFilter="coh-div-te-a" />);
    for (const day of [0, 1, 2, 3, 4]) {
      expect(screen.getByTestId(`lunch-cell-${day}-4`)).toHaveTextContent('Lunch');
      expect(screen.queryByTestId(`lunch-cell-${day}-5`)).not.toBeInTheDocument();
    }
  });

  it('shows both years\' lunches, each naming its cohorts, when unfiltered', () => {
    render(<TimetableGrid edgeList={d6} solution={null} />);
    expect(screen.getByTestId('lunch-cell-0-4')).toHaveTextContent('div-te-a');
    expect(screen.getByTestId('lunch-cell-0-5')).toHaveTextContent('div-se-a');
    expect(screen.queryAllByTestId('pinned-block')).toHaveLength(0);
  });
});
