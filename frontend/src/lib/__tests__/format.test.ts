import { describe, it, expect } from 'vitest';
import {
  displayText,
  formatClock,
  formatClockRange,
  formatDuration,
  formatSeconds,
  formatTimestamp,
  periodLabel,
  periodSpan,
} from '@/lib/format';

describe('formatDuration: times for people', () => {
  it('under a second: whole milliseconds', () => {
    expect(formatDuration(0)).toBe('0 ms');
    expect(formatDuration(0.4)).toBe('0 ms');
    expect(formatDuration(12)).toBe('12 ms');
    expect(formatDuration(212.4)).toBe('212 ms');
    expect(formatDuration(998.7)).toBe('999 ms');
  });

  it('a second or more: seconds with one decimal, never a raw float', () => {
    // rounds up to 1000 ms: a second
    expect(formatDuration(999.6)).toBe('1.0 s');
    expect(formatDuration(1000)).toBe('1.0 s');
    expect(formatDuration(1284.5)).toBe('1.3 s');
    // the browser check's raw value
    expect(formatDuration(30073.179800005164)).toBe('30.1 s');
    expect(formatDuration(300000)).toBe('300.0 s');
  });

  it('no time: a dash', () => {
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(undefined)).toBe('—');
    expect(formatDuration(Number.NaN)).toBe('—');
  });

  it('formatSeconds takes seconds (a job time limit)', () => {
    expect(formatSeconds(5)).toBe('5.0 s');
    expect(formatSeconds(0.25)).toBe('250 ms');
    expect(formatSeconds(undefined)).toBe('—');
  });
});

describe('periodLabel: periods are shown as T0..T9 (S14p)', () => {
  it('labels a wall-clock period index, the index itself unchanged', () => {
    expect(periodLabel(0)).toBe('T0');
    expect(periodLabel(9)).toBe('T9');
    expect(periodSpan(3, 3)).toBe('T3');
    expect(periodSpan(6, 7)).toBe('T6–T7');
  });
});

describe('displayText: backend, solver and ingestion text for display only', () => {
  it('rewrites a P-label as T, as a whole word: P and one digit', () => {
    expect(displayText('TE lunch, Mon P4')).toBe('TE lunch, Mon T4');
    expect(displayText('MDM - I LABs, Mon P0–P1')).toBe('MDM - I LABs, Mon T0–T1');
    expect(displayText('SE-Comp A t0 r4 c1 Mon P3-P4')).toBe('SE-Comp A t0 r4 c1 Mon T3-T4');
    expect(displayText("periods: class 'P7-P8' vs lab 'P0-P1'")).toBe("periods: class 'T7-T8' vs lab 'T0-T1'");
    expect(displayText('The change: obs-t0-r1-c2-l0 is moved to Mon P0 in room-601.')).toBe(
      'The change: obs-t0-r1-c2-l0 is moved to Mon T0 in room-601.'
    );
  });

  it('never touches words that only start with P, a P after a digit, or P with two digits', () => {
    for (const text of [
      'PCS / DN / 002',
      'PE-II-A',
      'PR3-I Main Project Stage I',
      'PSOOP / D3 / 003',
      "printed '4T+ 12P=16', computed 2T+8P=10",
      'P10',
      'AP0',
      'P0x',
    ]) {
      expect(displayText(text)).toBe(text);
    }
  });

  it("writes the solver's 24-hour period times as 12-hour ranges, leaving other numbers alone", () => {
    expect(displayText('coh-se-d-b: Thursday 10.00-11.00; coh-te-a-a: Wednesday 13.15-14.15')).toBe(
      'coh-se-d-b: Thursday 10:00 AM – 11:00 AM; coh-te-a-a: Wednesday 1:15 PM – 2:15 PM'
    );
    // printed source text quoted by the anomaly report, and plain numbers, stay as they are
    expect(displayText("time '9.00-11.00' fits no period")).toBe("time '9.00-11.00' fits no period");
    expect(displayText('printed 24/30 = 80.0 %, 86.67 %; -30.0 pts; 0.5')).toBe('printed 24/30 = 80.0 %, 86.67 %; -30.0 pts; 0.5');
  });
});

describe('formatClock: every time of day in 12-hour form with AM/PM', () => {
  it('reads 24-hour times with a colon or a dot', () => {
    expect(formatClock('09:00')).toBe('9:00 AM');
    expect(formatClock('00:05')).toBe('12:05 AM');
    expect(formatClock('11:15')).toBe('11:15 AM');
    expect(formatClock('12:15')).toBe('12:15 PM');
    expect(formatClock('13:15')).toBe('1:15 PM');
    expect(formatClock('18.15')).toBe('6:15 PM');
  });

  it('leaves anything else unchanged', () => {
    expect(formatClock('soon')).toBe('soon');
    expect(formatClock('9')).toBe('9');
  });

  it('formats a period range', () => {
    expect(formatClockRange('09:00', '10:00')).toBe('9:00 AM – 10:00 AM');
    expect(formatClockRange('17:15', '18:15')).toBe('5:15 PM – 6:15 PM');
  });

  it('formats a backend timestamp in the viewer’s time zone, 12-hour', () => {
    // built from local time, so the expectation holds in any time zone
    expect(formatTimestamp(new Date(2026, 9, 22, 15, 30).toISOString())).toBe('22 Oct 2026, 3:30 PM');
    expect(formatTimestamp(new Date(2026, 9, 30, 0, 7).toISOString())).toBe('30 Oct 2026, 12:07 AM');
    expect(formatTimestamp('not a time')).toBe('not a time');
  });
});
