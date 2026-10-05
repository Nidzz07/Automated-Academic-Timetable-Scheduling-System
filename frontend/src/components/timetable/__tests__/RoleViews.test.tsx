import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import App from '@/App';

describe('Role-Differentiated Views (Phase 2 Track C)', () => {
  it('renders administrator role by default with drag-enabled capabilities, department scope, and admin controls', async () => {
    render(<App />);

    // Assert Administrator role is active
    expect(screen.getByTestId('role-button-administrator')).toBeInTheDocument();
    expect(screen.getByTestId('capability-badge-drag')).toHaveTextContent(/Drag-and-Drop Enabled/i);

    // Assert whole-department scope controls exist
    expect(screen.getByLabelText(/Filter timetable by division/i)).toBeInTheDocument();

    // Assert administrative simulation controls are present
    expect(screen.getByTestId('toggle-outcome-button')).toBeInTheDocument();
    expect(screen.getByTestId('toggle-reject-mode-button')).toBeInTheDocument();

    // Assert quality score card is visible
    expect(screen.getByText(/Solver Quality Evaluation/i)).toBeInTheDocument();

    // Assert sessions are draggable
    const sessionCards = screen.getAllByTestId(/^session-cell-/);
    expect(sessionCards.length).toBeGreaterThan(0);
    // sess-0006 is standard theory lecture, should be draggable
    const sess6 = screen.getByTestId('session-cell-sess-0006');
    expect(sess6).toHaveAttribute('data-draggable', 'true');
    expect(within(sess6).getByTestId('drag-handle-sess-0006')).toBeInTheDocument();
  });

  it('renders coordinator role with drag-enabled capabilities and department management', async () => {
    render(<App />);

    // Switch to coordinator role
    fireEvent.click(screen.getByTestId('role-button-coordinator'));

    // Assert Coordinator role badge and capabilities
    expect(screen.getByTestId('capability-badge-drag')).toHaveTextContent(/Drag-and-Drop Enabled/i);
    expect(screen.getByText(/Department-wide timetable management and conflict resolution/i)).toBeInTheDocument();

    // Dragging remains enabled
    const sess6 = screen.getByTestId('session-cell-sess-0006');
    expect(sess6).toHaveAttribute('data-draggable', 'true');
  });

  it('differentiates faculty role: READ-ONLY, own sessions only, shows T/P workload formula, hides admin telemetry', async () => {
    render(<App />);

    // Switch to faculty role
    fireEvent.click(screen.getByTestId('role-button-faculty'));

    // 1. MUST BE READ-ONLY (DO capability difference)
    expect(screen.getByTestId('capability-badge-readonly')).toHaveTextContent(/Read-Only View/i);
    expect(screen.queryByTestId('capability-badge-drag')).not.toBeInTheDocument();

    // Sessions are NOT draggable (no drag handle, data-draggable="false")
    const allSessionCells = screen.getAllByTestId(/^session-cell-/);
    allSessionCells.forEach((card) => {
      expect(card).toHaveAttribute('data-draggable', 'false');
    });
    expect(screen.queryByTestId('drag-handle-sess-0006')).not.toBeInTheDocument();

    // 2. MUST SEE OWN SESSIONS AND WORKLOAD (SEE capability difference)
    expect(screen.getByTestId('faculty-persona-selector')).toBeInTheDocument();
    expect(screen.getByTestId('faculty-workload-card')).toBeInTheDocument();

    // Verify institutional T/P workload formula is shown (e.g. 6T + 8P = 14 or similar)
    const formulaBadge = screen.getByTestId('workload-formula-badge');
    expect(formulaBadge).toBeInTheDocument();
    expect(formulaBadge.textContent).toMatch(/\d+T \+ \d+P = \d+ hrs\/wk/);

    // 3. MUST HIDE ADMIN TELEMETRY & CONTROLS
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
    expect(screen.queryByText(/Solver Quality Evaluation/i)).not.toBeInTheDocument();
  });

  it('differentiates student role: STRICTLY READ-ONLY, division-specific schedule, hides quality penalties', async () => {
    render(<App />);

    // Switch to student role
    fireEvent.click(screen.getByTestId('role-button-student'));

    // 1. MUST BE READ-ONLY
    expect(screen.getByTestId('capability-badge-readonly')).toHaveTextContent(/Read-Only View/i);
    expect(screen.queryByTestId('capability-badge-drag')).not.toBeInTheDocument();

    // Sessions are NOT draggable
    const allSessionCells = screen.getAllByTestId(/^session-cell-/);
    allSessionCells.forEach((card) => {
      expect(card).toHaveAttribute('data-draggable', 'false');
    });

    // 2. MUST SEE OWN DIVISION COHORT
    expect(screen.getByTestId('student-division-selector')).toBeInTheDocument();
    expect(screen.getByText(/SE-Comp Division B/i)).toBeInTheDocument();

    // 3. MUST HIDE ADMIN QUALITY SCORE & TELEMETRY
    expect(screen.queryByText(/Solver Quality Evaluation/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
  });
});
