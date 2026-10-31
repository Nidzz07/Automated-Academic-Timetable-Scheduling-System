/**
 * A duration for people: under a second as whole milliseconds ("212 ms"), otherwise seconds
 * with one decimal ("30.1 s"); never a raw float. "—" when there is none.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return '—';
  const whole = Math.round(ms);
  // 999.6 ms rounds to 1000 ms: shown as 1.0 s
  return whole < 1000 ? `${whole} ms` : `${(ms / 1000).toFixed(1)} s`;
}

/** formatDuration for a value in seconds (a job's time_limit_s). */
export const formatSeconds = (s: number | null | undefined) =>
  formatDuration(s === null || s === undefined ? s : s * 1000);

/** A quality score or points, always with one decimal and a true minus sign: "−15.0", "26.5". */
export function formatScore(score: number): string {
  const digits = Math.abs(score).toFixed(1);
  return score < 0 && digits !== '0.0' ? `−${digits}` : digits;
}

/** A change of score: "+1.5", "−2.0", "+0.0". */
export const formatScoreChange = (change: number) => {
  const text = formatScore(change);
  return text.startsWith('−') ? text : `+${text}`;
};

/**
 * What a user sees for a wall-clock period: T0..T9 (the project guide's wording). The contracts,
 * the data and every internal number keep the period index; only this label changes.
 */
export const periodLabel = (period: number) => `T${period}`;

/** "T3", or "T3–T4" for a run of periods. */
export const periodSpan = (first: number, last: number) =>
  first === last ? periodLabel(first) : `${periodLabel(first)}–${periodLabel(last)}`;

/** A time of day, 24-hour "13:15" or "13.15" (as the solver writes it), as "1:15 PM"; else unchanged. */
export function formatClock(time: string): string {
  const m = time.match(/^(\d{1,2})[:.](\d{2})$/);
  if (!m) return time;
  const h = Number(m[1]);
  return `${h % 12 === 0 ? 12 : h % 12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`;
}

/** "9:00 AM – 10:00 AM" */
export const formatClockRange = (start: string, end: string) => `${formatClock(start)} – ${formatClock(end)}`;

/** A moment (an ISO timestamp from the backend) in the viewer's time zone: "22 Oct 2026, 3:30 PM". */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  return `${date}, ${formatClock(`${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`)}`;
}

/**
 * Text written by the backend, solver or ingestion, for display only: period labels P0..P9 become
 * T0..T9 (P and one digit as a whole word, so PCS, PE-II-A, 12P or P10 are untouched) and the
 * solver's 24-hour period times "13.15-14.15" become "1:15 PM – 2:15 PM". The stored text is unchanged.
 */
export const displayText = (text: string) =>
  text
    .replace(/\bP(\d)\b/g, (_, p: string) => periodLabel(Number(p)))
    .replace(/\b(\d{2}\.\d{2})-(\d{2}\.\d{2})\b/g, (_, a: string, b: string) => formatClockRange(a, b));
