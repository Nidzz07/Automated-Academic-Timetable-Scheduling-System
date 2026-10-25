import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import App from '@/App';
import { AnomalyReportPanel } from '../AnomalyReport';
import { Display, EdgeList, entityName, labelsFor } from '@/adapters/timetable';
import { AnomalyReport, NEEDS_HUMAN } from '@/adapters/realInstance';
import { HttpChronosApiClient, MockChronosApiClient, REAL_INSTANCE, setSession } from '@/api/chronosApi';
import type { UserRole } from '@/types/roles';

// S11c: the anomaly panel on the real report (data/instances/even-2025-26/anomalies.json)
const files = new MockChronosApiClient();
let report: AnomalyReport;
let display: Display;
let edgeList: EdgeList;
beforeAll(async () => {
  report = (await files.getAnomalies(REAL_INSTANCE))!;
  display = (await files.getDisplay(REAL_INSTANCE))!;
  edgeList = await files.getEdgeList(REAL_INSTANCE);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setSession(null);
});

const groups = () => screen.getAllByTestId('anomaly-group');
const rowsIn = (group: HTMLElement) => within(group).queryAllByTestId('anomaly-row');
const groupOf = (category: string) => groups().find((g) => g.dataset.category === category)!;

describe('AnomalyReportPanel on the real report', () => {
  it('groups every row by category, each with the report’s own count, equal to its rows', () => {
    render(<AnomalyReportPanel report={report} display={display} edgeList={edgeList} />);
    const byCategory = report.counts.by_category!;
    const listed = new Set(report.anomalies.map((a) => a.category));
    expect(groups().map((g) => g.dataset.category).sort()).toEqual([...listed].sort());
    expect(Object.keys(byCategory).sort()).toEqual([...listed].sort());
    for (const group of groups()) {
      const category = group.dataset.category!;
      const rows = report.anomalies.filter((a) => a.category === category);
      expect(rowsIn(group)).toHaveLength(rows.length);
      expect(within(group).getByTestId('anomaly-group-count')).toHaveTextContent(String(byCategory[category]));
      expect(byCategory[category]).toBe(rows.length);
    }
    expect(screen.getAllByTestId('anomaly-row')).toHaveLength(report.anomalies.length);
    expect(screen.queryByTestId('anomaly-count-mismatch')).not.toBeInTheDocument();
  });

  it('shows each row’s source file, location, message and resolution as the report gives them', () => {
    render(<AnomalyReportPanel report={report} display={display} edgeList={edgeList} />);
    const rows = screen.getAllByTestId('anomaly-row');
    // groups list rows in report order, so the n-th row of a group is that category's n-th anomaly
    for (const group of groups()) {
      const expected = report.anomalies.filter((a) => a.category === group.dataset.category);
      rowsIn(group).forEach((row, i) => {
        const cells = row.querySelectorAll('td');
        expect(cells[1].textContent).toBe(expected[i].source_file);
        expect(cells[2].textContent).toBe(expected[i].location);
        expect(cells[3].firstChild?.textContent).toBe(expected[i].message);
        expect(cells[4].textContent).toBe(expected[i].resolution);
      });
    }
    expect(rows).toHaveLength(report.counts.total);
  });

  it('shows "needs human" exactly as the report spells it', () => {
    render(<AnomalyReportPanel report={report} display={display} edgeList={edgeList} />);
    fireEvent.click(screen.getByLabelText('Needs human only'));
    const human = screen.getAllByTestId('anomaly-row');
    expect(human).toHaveLength(report.anomalies.filter((a) => a.resolution === NEEDS_HUMAN).length);
    human.forEach((row) => expect(row.querySelectorAll('td')[4].textContent).toBe(NEEDS_HUMAN));
    expect(within(screen.getByRole('table')).queryByText('Needs human')).not.toBeInTheDocument();
  });

  it('filters by category, keeping the group and its count', () => {
    render(<AnomalyReportPanel report={report} display={display} edgeList={edgeList} />);
    fireEvent.change(screen.getByLabelText('Anomaly category'), { target: { value: 'load_mismatch' } });
    expect(groups()).toHaveLength(1);
    const rows = report.anomalies.filter((a) => a.category === 'load_mismatch');
    expect(rowsIn(groupOf('load_mismatch'))).toHaveLength(rows.length);
    expect(screen.getByTestId('anomaly-count')).toHaveTextContent(`${rows.length} of ${report.counts.total} shown`);

    // with needs human only, the group shows its needs-human rows, its count stays the report's
    fireEvent.click(screen.getByLabelText('Needs human only'));
    const human = rows.filter((a) => a.resolution === NEEDS_HUMAN);
    expect(rowsIn(groupOf('load_mismatch'))).toHaveLength(human.length);
    expect(within(groupOf('load_mismatch')).getByTestId('anomaly-group-count')).toHaveTextContent(String(rows.length));
  });
});

describe('AnomalyReportPanel: counts that differ from the rows', () => {
  it('shows both numbers and says so, never adjusting either', () => {
    const [first] = report.anomalies;
    const counted = report.counts.by_category![first.category] + 1;
    const skewed: AnomalyReport = {
      ...report,
      counts: { ...report.counts, by_category: { ...report.counts.by_category, [first.category]: counted } },
    };
    render(<AnomalyReportPanel report={skewed} />);
    const group = groupOf(first.category);
    const rows = report.anomalies.filter((a) => a.category === first.category).length;
    expect(within(group).getByTestId('anomaly-group-count')).toHaveTextContent(String(counted));
    expect(within(group).getByTestId('anomaly-count-mismatch')).toHaveTextContent(
      `The report counts ${counted} but lists ${rows}; they differ and neither is adjusted.`
    );
    expect(rowsIn(group)).toHaveLength(rows);
    expect(screen.getAllByTestId('anomaly-count-mismatch')).toHaveLength(1);
  });

  it('says so when the total differs from the rows listed', () => {
    const skewed: AnomalyReport = { ...report, counts: { ...report.counts, total: report.counts.total + 2 } };
    render(<AnomalyReportPanel report={skewed} />);
    expect(screen.getByTestId('anomaly-count-mismatch')).toHaveTextContent(
      `The report counts ${report.counts.total + 2} in total but lists ${report.anomalies.length}`
    );
    expect(screen.getAllByTestId('anomaly-row')).toHaveLength(report.anomalies.length);
  });
});

describe('AnomalyReportPanel: ids named from display.json', () => {
  // The real report names no display.json id, so this test report does: each text is kept as given
  it('shows a name beside each id, the id kept visible, and the message unchanged', () => {
    const session = edgeList.sessions[0].id;
    const message = `fac-swapnali-kurhade teaches ${session} for coh-se-a-a in room-509`;
    const named: AnomalyReport = {
      counts: { total: 1, needs_human: 1, by_category: { test_ids: 1 } },
      anomalies: [{ category: 'test_ids', source_file: 'test', location: 'test', message, resolution: NEEDS_HUMAN }],
    };
    render(<AnomalyReportPanel report={named} display={display} edgeList={edgeList} />);
    const row = screen.getByTestId('anomaly-row');
    expect(row.querySelectorAll('td')[3].firstChild?.textContent).toBe(message);
    expect(within(row).getAllByTestId('anomaly-name').map((n) => n.textContent)).toEqual([
      'Swapnali Kurhade (SK) · fac-swapnali-kurhade',
      `${entityName(session, edgeList, labelsFor(display))} · ${session}`,
      'SE-Comp A batch A · coh-se-a-a',
      'Room 509 · room-509',
    ]);
  });

  it('names nothing in the real report, which carries no display.json id', () => {
    render(<AnomalyReportPanel report={report} display={display} edgeList={edgeList} />);
    expect(screen.queryByTestId('anomaly-name')).not.toBeInTheDocument();
  });
});

describe('AnomalyReportPanel: no report, empty report', () => {
  it('a missing report reads "No anomaly report for this instance."', () => {
    render(<AnomalyReportPanel report={null} />);
    expect(screen.getByTestId('anomaly-report-status')).toHaveTextContent('No anomaly report for this instance.');
    expect(screen.queryByTestId('anomaly-row')).not.toBeInTheDocument();
  });

  it('an empty report reads "The report lists no anomalies."', () => {
    render(<AnomalyReportPanel report={{ counts: { total: 0, needs_human: 0, by_category: {} }, anomalies: [] }} />);
    expect(screen.getByTestId('anomaly-report-status')).toHaveTextContent('The report lists no anomalies.');
    expect(screen.queryByTestId('anomaly-count-mismatch')).not.toBeInTheDocument();
  });
});

describe('The anomaly panel in the app (static mode)', () => {
  const openReal = async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('period-clock-0');
  };

  it.each([
    ['administrator', true],
    ['coordinator', true],
    ['faculty', false],
    ['student', false],
  ] as const)('the %s sees it: %s', async (role, shown) => {
    await openReal();
    fireEvent.click(screen.getByTestId(`role-button-${role}`));
    expect(!!screen.queryByTestId('anomaly-report')).toBe(shown);
    if (shown) expect(screen.getAllByTestId('anomaly-row')).toHaveLength(report.anomalies.length);
  });

  it('the contract examples have no report', async () => {
    render(<App />);
    await screen.findByTestId('timetable-grid');
    expect(screen.getByTestId('anomaly-report-status')).toHaveTextContent('No anomaly report for this instance.');
  });
});

describe('The anomaly panel in the app (http mode, fetch mocked)', () => {
  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

  /** The backend serving the real instance; `anomalies` undefined answers 404. */
  async function openReal(role: UserRole, anomalies: AnomalyReport | undefined) {
    const served: Record<string, unknown> = {
      'edge-list': edgeList,
      'edge-list/current': edgeList,
      display,
      solution: await files.getInstanceSolution(REAL_INSTANCE),
      ...(anomalies ? { anomalies } : {}),
    };
    const fetchMock = vi.fn(async (url: string) => {
      if (url === '/api/instances') return json([{ id: REAL_INSTANCE }]);
      const file = url.match(new RegExp(`^/api/instances/${REAL_INSTANCE}/(.+)$`))?.[1];
      return file && file in served ? json(served[file]) : json({ detail: 'Not Found' }, 404);
    });
    vi.stubGlobal('fetch', fetchMock);
    setSession({ username: `test-${role}`, token: `token-${role}`, role });
    render(<App client={new HttpChronosApiClient('/api')} />);
    await screen.findByTestId('timetable-grid');
    fireEvent.change(screen.getByLabelText('Select instance'), { target: { value: REAL_INSTANCE } });
    await screen.findByTestId('period-clock-0');
    return fetchMock;
  }

  it.each(['administrator', 'coordinator'] as const)('the %s sees the served report, grouped', async (role) => {
    const fetchMock = await openReal(role, report);
    expect(fetchMock.mock.calls.map(([url]) => url)).toContain(`/api/instances/${REAL_INSTANCE}/anomalies`);
    expect(screen.getAllByTestId('anomaly-row')).toHaveLength(report.anomalies.length);
    expect(groups()).toHaveLength(new Set(report.anomalies.map((a) => a.category)).size);
  });

  it.each(['faculty', 'student'] as const)('the %s never sees it', async (role) => {
    await openReal(role, report);
    expect(screen.queryByTestId('anomaly-report')).not.toBeInTheDocument();
  });

  it('a 404 reads as no report', async () => {
    await openReal('administrator', undefined);
    expect(screen.getByTestId('anomaly-report-status')).toHaveTextContent('No anomaly report for this instance.');
  });

  it('an empty report reads as such', async () => {
    await openReal('coordinator', { counts: { total: 0, needs_human: 0, by_category: {} }, anomalies: [] });
    expect(screen.getByTestId('anomaly-report-status')).toHaveTextContent('The report lists no anomalies.');
  });
});
