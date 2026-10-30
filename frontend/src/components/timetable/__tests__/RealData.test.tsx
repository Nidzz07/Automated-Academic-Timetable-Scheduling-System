import { describe, it, expect, beforeAll } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import App from '@/App';
import { TimetableGrid } from '../TimetableGrid';
import { AnomalyReportPanel } from '../AnomalyReport';
import { EdgeList, Labels, labelsFor } from '@/adapters/timetable';
import { AnomalyReport, NEEDS_HUMAN, PrintedBaseline, toPrintedBaseline } from '@/adapters/realInstance';
import { MockChronosApiClient, PRINTED_INSTANCE, REAL_INSTANCE } from '@/api/chronosApi';

// S12f: the real EVEN 2025-26 instance's display.json membership and initials,
// anomalies.json and the printed baseline (real_baseline.*.json)
let edgeList: EdgeList;
let labels: Labels;
let anomalies: AnomalyReport;
let printed: PrintedBaseline;
beforeAll(async () => {
  const client = new MockChronosApiClient();
  edgeList = await client.getEdgeList(REAL_INSTANCE);
  labels = labelsFor(await client.getDisplay(REAL_INSTANCE));
  anomalies = (await client.getAnomalies(REAL_INSTANCE))!;
  printed = (await client.getPrintedBaseline(PRINTED_INSTANCE))!;
});

const sessionOf = (cohort: string) => edgeList.sessions.find((s) => s.cohort_id === cohort)!.id;
const rendered = (id: string) => screen.queryAllByTestId(new RegExp(`(session-cell|batch-session)-${id}$`)).length > 0;

describe('division filter on the real instance (display.json batch membership)', () => {
  it('a division overlaps its own batches only', () => {
    expect(labels.overlap('coh-se-a', 'coh-se-a-a')).toBe(true);
    expect(labels.overlap('coh-se-a-a', 'coh-se-a')).toBe(true);
    expect(labels.overlap('coh-se-a', 'coh-se-b-a')).toBe(false);
    expect(labels.overlap('coh-se-a-a', 'coh-se-a-b')).toBe(false);
  });

  it('shows the division’s batch sessions on the grid, and no other division’s', () => {
    render(<TimetableGrid edgeList={edgeList} labels={labels} solution={printed} cohortFilter="coh-se-a" />);
    expect(rendered(sessionOf('coh-se-a'))).toBe(true);
    expect(rendered(sessionOf('coh-se-a-a'))).toBe(true);
    expect(rendered(sessionOf('coh-se-b-a'))).toBe(false);
  });
});

describe('anomaly report viewer', () => {
  it('lists every anomaly with the decision that resolves it', () => {
    render(<AnomalyReportPanel report={anomalies} />);
    expect(screen.getAllByTestId('anomaly-row')).toHaveLength(anomalies.counts.total);
    expect(screen.getByTestId('anomaly-count')).toHaveTextContent(`${anomalies.counts.total} of ${anomalies.counts.total} shown`);
  });

  it('filters by category and by needs human', () => {
    render(<AnomalyReportPanel report={anomalies} />);
    fireEvent.click(screen.getByLabelText('Needs human only'));
    const human = screen.getAllByTestId('anomaly-row');
    expect(human).toHaveLength(anomalies.counts.needs_human);
    human.forEach((row) => expect(row).toHaveTextContent(NEEDS_HUMAN));

    fireEvent.click(screen.getByLabelText('Needs human only'));
    fireEvent.change(screen.getByLabelText('Anomaly category'), { target: { value: 'frozen_d44' } });
    const d44 = screen.getAllByTestId('anomaly-row');
    expect(d44).toHaveLength(anomalies.anomalies.filter((a) => a.category === 'frozen_d44').length);
    d44.forEach((row) => expect(row).toHaveTextContent('D44'));
  });
});

describe('printed baseline adapter', () => {
  it('places every edge-list session as printed, with the report’s violations and score', () => {
    expect(printed.assignment).toHaveLength(edgeList.sessions.length);
    expect(printed.violations).toHaveLength(36);
    expect(printed.quality.score).toBe(21.5);
    expect(printed.quality.rules.map((r) => r.rule_id)).toEqual(['S-GAP', 'S-B2B', 'S-LOAD16', 'FAC_LOAD_IMBALANCE']);
    // a printed room outside the edge list's room set (D10, D29) has no room id
    expect(printed.assignment.some((a) => a.room_id === '')).toBe(true);
  });

  it('refuses files naming a session the edge list does not have', () => {
    const assignment = { assignment: { 'obs-nope': { day: 0, period: 0, room_id: null, sub_room_id: null } } };
    const report = { violations: [], quality: { score: 0, rules_version: '1', not_evaluated_rule_ids: [], breakdown: [] } };
    expect(() => toPrintedBaseline(assignment, report, edgeList)).toThrow(/obs-nope/);
  });
});

describe('the EVEN 2025-26 printed (real) instance in the app', () => {
  const openPrinted = async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: PRINTED_INSTANCE } });
    await screen.findByTestId('printed-violations');
  };
  const flaggedIds = () =>
    [...document.querySelectorAll('[data-flagged="true"]')].map(
      (el) => (el.getAttribute('data-testid') ?? el.querySelector('[data-testid]')?.getAttribute('data-testid'))!
    );

  it('renders the printed timetable with its violations outlined and its score breakdown', async () => {
    await openPrinted();
    expect(screen.getByTestId('printed-violations')).toHaveTextContent('36 violations');
    expect(screen.getByText('Printed timetable quality')).toBeInTheDocument();
    expect(screen.getByTestId('quality-score')).toHaveTextContent('21.5');
    expect(screen.getByTestId('quality-rule-S-B2B')).toHaveTextContent('Found 23 pairs of periods → −23 points (1 point each)');
    expect(screen.queryByTestId('no-solution-note')).not.toBeInTheDocument();
    expect(flaggedIds().length).toBeGreaterThan(2);

    // picking a violation outlines only its sessions (Kailas Devadkar's OS clash, Tuesday P0)
    fireEvent.click(screen.getByTestId('printed-violation-0'));
    expect(flaggedIds().sort()).toEqual(['session-cell-obs-t0-r1-c2-l0', 'session-cell-obs-t2-r1-c2-l0']);
  });

  it('shows faculty as "Name (INITIALS)" and the anomaly report', async () => {
    await openPrinted();
    expect(screen.getAllByTestId('anomaly-row')).toHaveLength(anomalies.counts.total);
    fireEvent.click(screen.getByTestId('role-button-faculty'));
    const persona = screen.getByLabelText('Select faculty persona') as HTMLSelectElement;
    expect([...persona.options].map((o) => o.text)).toContain('Kailas Devadkar (KKD)');
    expect(within(screen.getByTestId('faculty-workload-card')).getByText(/Weekly teaching load/)).toBeInTheDocument();
  });
});
