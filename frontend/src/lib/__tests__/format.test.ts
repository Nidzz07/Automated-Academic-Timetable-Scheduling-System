import { describe, it, expect } from 'vitest';
import { formatDuration, formatSeconds } from '@/lib/format';

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
