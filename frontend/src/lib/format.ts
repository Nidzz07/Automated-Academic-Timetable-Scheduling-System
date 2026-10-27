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
