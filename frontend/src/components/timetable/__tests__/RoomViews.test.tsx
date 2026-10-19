import { describe, it, expect, vi, afterEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import App from '@/App';
import { FreeRoomsPanel, RoomTimetable } from '../RoomViews';
import {
  buildEnrichedSessions,
  cohortOptions,
  getExampleEdgeList,
  getSolvedSolutionFixture,
  labelsFor,
} from '@/adapters/timetable';
import { isSolvedSolution } from '@/adapters/solution';
import { chronosApiClient, MockChronosApiClient } from '@/api/chronosApi';

const edgeList = getExampleEdgeList();
const assignment = getSolvedSolutionFixture().assignment;
const sessions = buildEnrichedSessions(assignment, edgeList);

describe('Room timetable', () => {
  it('shows one room’s week, with sub-room use, from the edge list and the solution', () => {
    render(<RoomTimetable edgeList={edgeList} sessions={sessions} />);
    fireEvent.change(screen.getByLabelText('Select room'), { target: { value: 'room-702' } });

    // The SE-Comp B lab block holds 702-A and 702-B at P1 and, after the P2 break, P3
    for (const period of [1, 3]) {
      const cell = screen.getByTestId(`room-cell-0-${period}`);
      expect(cell).toHaveTextContent('OS · SE-Comp B / A · AGN (702-A)');
      expect(cell).toHaveTextContent('DAA · SE-Comp B / B · NR (702-B)');
    }
    expect(screen.getByTestId('room-cell-0-2')).toHaveTextContent('Break');
    expect(screen.getByTestId('room-cell-1-1')).toBeEmptyDOMElement();
  });

  it('shows pinned occupancy in its room', () => {
    render(<RoomTimetable edgeList={edgeList} sessions={sessions} />);
    fireEvent.change(screen.getByLabelText('Select room'), { target: { value: 'room-508' } });
    expect(screen.getByTestId('room-cell-3-4')).toHaveTextContent('Pinned');
  });
});

describe('Free rooms', () => {
  it('lists the rooms free at a chosen day and period', () => {
    render(<FreeRoomsPanel edgeList={edgeList} sessions={sessions} />);
    fireEvent.change(screen.getByLabelText('Free rooms period'), { target: { value: '1' } });

    const list = screen.getByTestId('free-rooms');
    expect(within(list).getByTestId('free-room-002')).toHaveTextContent('Classroom · capacity 80');
    expect(within(list).getByTestId('free-room-509 new CSE')).toHaveTextContent('Lab');
    expect(within(list).queryByTestId('free-room-702')).not.toBeInTheDocument();
    expect(within(list).queryByTestId('free-room-603')).not.toBeInTheDocument();
  });

  it('shows the batch places left in a partly occupied lab', () => {
    const partial = buildEnrichedSessions(
      assignment.filter((a) => a.session_id !== 'sess-0002'),
      edgeList
    );
    render(<FreeRoomsPanel edgeList={edgeList} sessions={partial} />);
    fireEvent.change(screen.getByLabelText('Free rooms period'), { target: { value: '3' } });

    expect(screen.getByTestId('batch-places-702')).toHaveTextContent(
      '1 of 2 batch places free (702-B)'
    );
  });
});

describe('Room views in the app', () => {
  it('are shown to whole-department roles and follow the D6 instance', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');
    expect(screen.getByTestId('room-timetable')).toBeInTheDocument();
    expect(screen.getByTestId('free-rooms')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: 'd6_grid' } });
    expect(await screen.findByTestId('no-solution-note')).toBeInTheDocument();
    expect(within(screen.getByTestId('free-rooms')).getByTestId('batch-places-702')).toHaveTextContent(
      '2 of 2 batch places free (702-A, 702-B)'
    );

    fireEvent.click(screen.getByTestId('role-button-student'));
    expect(screen.queryByTestId('room-timetable')).not.toBeInTheDocument();
  });
});

describe('The real EVEN 2025-26 instance in the app', () => {
  afterEach(() => vi.restoreAllMocks());

  const openRealInstance = async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: 'even_2025_26' } });
    await screen.findByTestId('period-clock-0');
  };

  it('shows the solved room view from solution.json', async () => {
    const client = new MockChronosApiClient();
    const [real, display, solution] = await Promise.all([
      client.getEdgeList('even_2025_26'),
      client.getDisplay('even_2025_26'),
      client.getInstanceSolution('even_2025_26'),
    ]);
    if (!solution || !isSolvedSolution(solution)) throw new Error('Expected a solved solution.json');
    const labels = labelsFor(display);
    const placed = buildEnrichedSessions(solution.assignment, real, labels);
    const roomId = placed[0].roomId;
    const code = new Map(real.rooms.map((r) => [r.id, labels.room(r)]));

    await openRealInstance();
    expect(screen.queryByTestId('no-solution-note')).not.toBeInTheDocument();
    const rooms = screen.getByTestId('room-timetable');
    fireEvent.change(within(rooms).getByLabelText('Select room'), { target: { value: roomId } });
    for (const s of placed.filter((p) => p.roomId === roomId)) {
      for (const period of s.periods) {
        const cell = within(rooms).getByTestId(`room-cell-${s.day}-${period}`);
        expect(cell).toHaveTextContent(`${s.subjectCode} · ${s.cohortLabel} · ${s.facultyInitials}`);
        if (s.subRoomId) expect(cell).toHaveTextContent(`(${code.get(s.subRoomId)})`);
      }
    }
  });

  it('says Not solved yet when no solution is published, and shows its lunches and pins', async () => {
    vi.spyOn(chronosApiClient, 'getInstanceSolution').mockResolvedValue(null);
    await openRealInstance();
    expect(screen.getByTestId('no-solution-note')).toHaveTextContent('Not solved yet');
    expect(screen.getByTestId('status-badge-unsolved')).toHaveTextContent('Not solved yet');
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.getAllByText('SE lunch')).toHaveLength(5);
    expect(screen.getAllByText('TE lunch')).toHaveLength(5);
  });

  it('shows pinned rooms in the room timetable and free rooms from display.json', async () => {
    await openRealInstance();
    const rooms = screen.getByTestId('room-timetable');
    fireEvent.change(within(rooms).getByLabelText('Select room'), { target: { value: 'room-703' } });
    // Tuesday P7: the D24 frozen MDM-III lab holds batch place 703-A
    expect(within(rooms).getByTestId('room-cell-1-7')).toHaveTextContent('MDM-III Lab (CC) /A /SB (703-A)');

    const free = screen.getByTestId('free-rooms');
    fireEvent.change(within(free).getByLabelText('Free rooms day'), { target: { value: '1' } });
    fireEvent.change(within(free).getByLabelText('Free rooms period'), { target: { value: '7' } });
    expect(within(free).getByTestId('batch-places-703')).toHaveTextContent('1 of 2 batch places free (703-B)');
    // 603 is held whole by a frozen MDM-DBMS lab, 509 by an out-of-scope M.Tech lab
    expect(within(free).queryByTestId('free-room-603')).not.toBeInTheDocument();
    expect(within(free).queryByTestId('free-room-509')).not.toBeInTheDocument();
  });

  it('resets role selections that do not exist in the instance switched to', async () => {
    await openRealInstance();
    fireEvent.click(screen.getByTestId('role-button-student'));
    fireEvent.change(screen.getByLabelText('Select student division'), { target: { value: 'coh-se-a-a' } });
    expect(screen.getByLabelText('Select student division')).toHaveValue('coh-se-a-a');

    // back to the example instance (cached, so the workspace keeps its state)
    fireEvent.click(screen.getByTestId('role-button-administrator'));
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: 'example' } });
    fireEvent.click(screen.getByTestId('role-button-student'));

    const first = cohortOptions(getExampleEdgeList())[0].id;
    expect(screen.getByLabelText('Select student division')).toHaveValue(first);
    // the grid is not empty: before the fix it filtered by a cohort the example does not have
    const grid = screen.getByTestId('timetable-grid');
    expect(within(grid).getAllByTestId(/^(session-cell-|batch-session-|combined-division-lecture)/).length).toBeGreaterThan(0);
  });

  it('shows the quality card once a solution is published beside the edge list', async () => {
    // stand-in payload: only checks the card follows the instance's own solution
    vi.spyOn(chronosApiClient, 'getInstanceSolution').mockResolvedValue(getSolvedSolutionFixture());
    await openRealInstance();
    const rule = getSolvedSolutionFixture().quality.breakdown[0].rule_id;
    expect(screen.getByTestId(`quality-rule-${rule}`)).toBeInTheDocument();
    expect(screen.queryByTestId('no-solution-note')).not.toBeInTheDocument();
  });
});
