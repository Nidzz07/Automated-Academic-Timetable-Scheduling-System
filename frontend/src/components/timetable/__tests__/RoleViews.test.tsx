import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import App from '@/App';

describe('Role-Differentiated Views (Phase 2 Track C)', () => {
  it('renders administrator role by default with drag-enabled capabilities, department scope, and admin controls', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');

    // Assert Administrator role is active
    expect(screen.getByTestId('role-button-administrator')).toBeInTheDocument();
    expect(screen.getByTestId('capability-badge-drag')).toHaveTextContent(/Can move sessions/i);

    // Assert whole-department scope controls exist
    expect(screen.getByLabelText(/Filter timetable by division/i)).toBeInTheDocument();

    // Assert administrative simulation controls are present
    expect(screen.getByTestId('toggle-outcome-button')).toBeInTheDocument();
    expect(screen.getByTestId('toggle-reject-mode-button')).toBeInTheDocument();

    // Assert quality score card is visible
    expect(screen.getByText('Timetable quality')).toBeInTheDocument();

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
    await screen.findByTestId('timetable-grid');

    // Switch to coordinator role
    fireEvent.click(screen.getByTestId('role-button-coordinator'));

    // Assert Coordinator role badge and capabilities
    expect(screen.getByTestId('capability-badge-drag')).toHaveTextContent(/Can move sessions/i);
    expect(screen.getByText(/Manages the department timetable/i)).toBeInTheDocument();

    // Dragging remains enabled
    const sess6 = screen.getByTestId('session-cell-sess-0006');
    expect(sess6).toHaveAttribute('data-draggable', 'true');
  });

  it('differentiates faculty role: READ-ONLY, own sessions only, shows T/P workload formula, hides admin telemetry', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');

    // Switch to faculty role
    fireEvent.click(screen.getByTestId('role-button-faculty'));

    // 1. MUST BE READ-ONLY (DO capability difference)
    expect(screen.getByTestId('capability-badge-readonly')).toHaveTextContent(/Read only/i);
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

    // Verify the weekly hours are shown in words (e.g. 6 h lectures + 8 h practicals = 14 h)
    const formulaBadge = screen.getByTestId('workload-formula-badge');
    expect(formulaBadge).toBeInTheDocument();
    expect(formulaBadge.textContent).toMatch(/\d+ h lectures? \+ \d+ h practicals? = \d+ h$/);

    // Persona options are the faculty placed in the payload, as "Name (INITIALS)"; no invented names or titles
    const facultySelect = screen.getByLabelText('Select teacher') as HTMLSelectElement;
    expect([...facultySelect.options].map((o) => o.text)).toEqual([
      'A. G. Nikam (AGN)',
      'D. Naik (DN)',
      'J. Shinde (JS)',
      'K. K. Deshpande (KKD)',
      'N. Raut (NR)',
    ]);
    expect(screen.queryByText(/Abha|Dr\.|Prof\./)).not.toBeInTheDocument();

    // Load status comes only from the solver's S-LOAD16, which this payload did not evaluate
    expect(screen.getByTestId('load-status')).toHaveTextContent('not evaluated');
    expect(screen.queryByText(/Normal Load|5–18h/)).not.toBeInTheDocument();

    // 3. MUST HIDE ADMIN TELEMETRY & CONTROLS
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
    expect(screen.queryByText('Timetable quality')).not.toBeInTheDocument();
  });

  it('differentiates student role: STRICTLY READ-ONLY, division-specific schedule, hides quality penalties', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');

    // Switch to student role, viewing SE-Comp C (the default is the first cohort the payload names)
    fireEvent.click(screen.getByTestId('role-button-student'));
    fireEvent.change(screen.getByLabelText('Select class'), {
      target: { value: 'coh-div-se-c' },
    });

    // 1. MUST BE READ-ONLY
    expect(screen.getByTestId('capability-badge-readonly')).toHaveTextContent(/Read only/i);
    expect(screen.queryByTestId('capability-badge-drag')).not.toBeInTheDocument();

    // Sessions are NOT draggable
    const allSessionCells = screen.getAllByTestId(/^session-cell-/);
    allSessionCells.forEach((card) => {
      expect(card).toHaveAttribute('data-draggable', 'false');
    });

    // 2. MUST SEE OWN DIVISION COHORT
    expect(screen.getByTestId('student-division-selector')).toBeInTheDocument();
    // Options are the cohorts named in the edge list, labelled from the payload
    const cohortSelect = screen.getByLabelText('Select class') as HTMLSelectElement;
    expect([...cohortSelect.options].map((o) => o.text)).toContain('SE-Comp B');
    expect(screen.queryByText(/SE-Comp Division B/i)).not.toBeInTheDocument();

    // 3. MUST HIDE ADMIN QUALITY SCORE & TELEMETRY
    expect(screen.queryByText('Timetable quality')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-outcome-button')).not.toBeInTheDocument();
    expect(screen.queryByTestId('toggle-reject-mode-button')).not.toBeInTheDocument();
  });
});
