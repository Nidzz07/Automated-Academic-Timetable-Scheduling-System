import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import App from '@/App';
import { MockChronosApiClient, chronosApiClient } from '@/api/chronosApi';

describe('Drag-and-Drop Interaction and Revert-on-Reject Flow', () => {
  beforeEach(() => {
    // Reset mock API client state before each test
    const mock = chronosApiClient as MockChronosApiClient;
    mock.setRejectMode(false);
    mock.setSimulatedOutcome('solved');
  });

  it('performs a successful drag: applies provisionally, confirmed by backend, updates grid placement', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');

    // sess-0006 is initially on Day 2 (Wednesday), P3
    const initialCell = screen.getByTestId('grid-cell-2-3');
    expect(within(initialCell).getByTestId('session-cell-sess-0006')).toBeInTheDocument();

    // Target cell: Day 0 (Monday), P6
    const targetCell = screen.getByTestId('grid-cell-0-6');
    expect(within(targetCell).queryByTestId('session-cell-sess-0006')).not.toBeInTheDocument();

    // Trigger drop of sess-0006 onto Monday P6
    fireEvent.drop(targetCell, {
      dataTransfer: {
        getData: () => 'sess-0006',
      },
    });

    // Wait for the mock backend response to resolve and update placement
    await waitFor(() => {
      expect(within(targetCell).getByTestId('session-cell-sess-0006')).toBeInTheDocument();
    });

    // Assert prior cell no longer has sess-0006
    expect(within(initialCell).queryByTestId('session-cell-sess-0006')).not.toBeInTheDocument();

    // Assert no rejection alert is surfaced
    expect(screen.queryByTestId('rejection-alert')).not.toBeInTheDocument();
  });

  it('performs a rejected drag: reverts cleanly to exact prior state and preserves UI selection', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');

    // 1. Initial State: sess-0006 is on Day 2 (Wednesday), P3
    const originalCell = screen.getByTestId('grid-cell-2-3');
    const sessCard = within(originalCell).getByTestId('session-cell-sess-0006');
    expect(sessCard).toBeInTheDocument();

    // 2. User selects sess-0006 in UI
    fireEvent.click(sessCard);

    // Detail modal opens, close it to inspect grid selection
    const closeBtn = screen.getByText('Close');
    fireEvent.click(closeBtn);

    // Assert session is marked as selected in UI state
    expect(screen.getByTestId('session-cell-sess-0006')).toHaveAttribute('data-selected', 'true');

    // 3. Target an invalid slot: Wednesday P7, pinned_occupancy for SE-Comp C in room 002
    const conflictCell = screen.getByTestId('grid-cell-2-7');
    expect(within(conflictCell).getByTestId('pinned-block')).toBeInTheDocument();

    // 4. Trigger drag-and-drop onto the conflicting slot
    fireEvent.drop(conflictCell, {
      dataTransfer: {
        getData: () => 'sess-0006',
      },
    });

    // 5. Backend rejects the move with a readable reason
    await waitFor(() => {
      expect(screen.getByTestId('rejection-alert')).toBeInTheDocument();
    });

    // Assert the readable reason surfaced comes from the mock backend response
    const reasonEl = screen.getByTestId('rejection-reason');
    expect(reasonEl).toHaveTextContent(/Wednesday T7 is held by a fixed item/i);

    // 6. EXACT PRIOR STATE RESTORED:
    // a. sess-0006 must be back in its original slot (Wednesday P3)
    expect(within(originalCell).getByTestId('session-cell-sess-0006')).toBeInTheDocument();

    // b. Conflicting slot must NOT contain sess-0006
    expect(within(conflictCell).queryByTestId('session-cell-sess-0006')).not.toBeInTheDocument();

    // c. The UI selection is PRESERVED!
    const restoredCard = within(originalCell).getByTestId('session-cell-sess-0006');
    expect(restoredCard).toHaveAttribute('data-selected', 'true');
  });

  it('reverts and surfaces custom reason when backend reject mode is simulated', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');

    // Enable simulated rejection via the UI button
    const toggleRejectBtn = screen.getByTestId('toggle-reject-mode-button');
    fireEvent.click(toggleRejectBtn);
    expect(toggleRejectBtn).toHaveTextContent(/Refusing every move/i);

    // Attempt to drop sess-0006 onto Monday P6
    const originalCell = screen.getByTestId('grid-cell-2-3');
    const targetCell = screen.getByTestId('grid-cell-0-6');

    fireEvent.drop(targetCell, {
      dataTransfer: {
        getData: () => 'sess-0006',
      },
    });

    // Await rejection alert
    await waitFor(() => {
      expect(screen.getByTestId('rejection-alert')).toBeInTheDocument();
    });

    // Verify rejection reason from simulated response
    const reasonEl = screen.getByTestId('rejection-reason');
    expect(reasonEl).toHaveTextContent(/A trial refusal: every move is set to be refused/i);

    // Verify session remains in original slot
    expect(within(originalCell).getByTestId('session-cell-sess-0006')).toBeInTheDocument();
    expect(within(targetCell).queryByTestId('session-cell-sess-0006')).not.toBeInTheDocument();

    // Dismiss rejection alert
    const dismissBtn = screen.getByText('Dismiss');
    fireEvent.click(dismissBtn);
    expect(screen.queryByTestId('rejection-alert')).not.toBeInTheDocument();
  });
});
