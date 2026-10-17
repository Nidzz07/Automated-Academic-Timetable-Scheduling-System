import { describe, it, expect } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import App from '@/App';
import { FreeRoomsPanel, RoomTimetable } from '../RoomViews';
import {
  buildEnrichedSessions,
  getExampleEdgeList,
  getSolvedSolutionFixture,
} from '@/adapters/timetable';

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
    expect(screen.getByTestId('lunch-cell-0-5')).toHaveTextContent('div-se-a');
    expect(screen.getByTestId('lunch-cell-0-4')).toHaveTextContent('div-te-a');
    expect(within(screen.getByTestId('free-rooms')).getByTestId('batch-places-702')).toHaveTextContent(
      '2 of 2 batch places free (702-A, 702-B)'
    );

    fireEvent.click(screen.getByTestId('role-button-student'));
    expect(screen.queryByTestId('room-timetable')).not.toBeInTheDocument();
  });
});
