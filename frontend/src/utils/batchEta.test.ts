import { describe, expect, it } from 'vitest';
import {
  calculateObservedSecondsPerTerm,
  calculatePreRunEstimateSeconds,
  calculateRemainingSeconds,
  getFallbackSecondsPerTerm,
} from './batchEta';

describe('getFallbackSecondsPerTerm', () => {
  it('returns the slower fallback for retrieval-enabled modes', () => {
    expect(getFallbackSecondsPerTerm('public')).toBe(5);
    expect(getFallbackSecondsPerTerm('local')).toBe(5);
  });

  it('returns the faster fallback for retrieval-disabled mode', () => {
    expect(getFallbackSecondsPerTerm('disabled')).toBe(2);
  });

  it('treats unknown retrieval mode (null/undefined) as retrieval-enabled', () => {
    expect(getFallbackSecondsPerTerm(null)).toBe(5);
    expect(getFallbackSecondsPerTerm(undefined)).toBe(5);
  });
});

describe('calculatePreRunEstimateSeconds', () => {
  it('multiplies row count by the retrieval-enabled fallback', () => {
    expect(calculatePreRunEstimateSeconds({ rowCount: 10, retrievalMode: 'public' })).toBe(50);
  });

  it('multiplies row count by the retrieval-disabled fallback', () => {
    expect(calculatePreRunEstimateSeconds({ rowCount: 10, retrievalMode: 'disabled' })).toBe(20);
  });

  it('is never negative for a zero row count', () => {
    expect(calculatePreRunEstimateSeconds({ rowCount: 0, retrievalMode: 'public' })).toBe(0);
  });
});

describe('calculateObservedSecondsPerTerm', () => {
  it('returns null when there are no completed rows', () => {
    expect(calculateObservedSecondsPerTerm([])).toBeNull();
  });

  it('returns the single duration for one completed valid row', () => {
    expect(calculateObservedSecondsPerTerm([{ processing_time_seconds: 4 }])).toBe(4);
  });

  it('computes the arithmetic mean across multiple valid rows', () => {
    const mean = calculateObservedSecondsPerTerm([
      { processing_time_seconds: 4 },
      { processing_time_seconds: 6 },
    ]);
    expect(mean).toBe(5);
  });

  it('excludes null processing_time_seconds from the mean', () => {
    const mean = calculateObservedSecondsPerTerm([
      { processing_time_seconds: 4 },
      { processing_time_seconds: null },
      { processing_time_seconds: 8 },
    ]);
    expect(mean).toBe(6);
  });

  it('excludes undefined processing_time_seconds from the mean', () => {
    const mean = calculateObservedSecondsPerTerm([
      { processing_time_seconds: 4 },
      { processing_time_seconds: undefined },
    ]);
    expect(mean).toBe(4);
  });

  it('a failed row (null duration) counts toward nothing but does not become zero', () => {
    // A naive implementation might coerce null -> 0 and drag the mean down.
    const mean = calculateObservedSecondsPerTerm([
      { processing_time_seconds: 10 },
      { processing_time_seconds: null },
    ]);
    expect(mean).toBe(10);
  });

  it('returns null when every row has an invalid duration', () => {
    expect(
      calculateObservedSecondsPerTerm([
        { processing_time_seconds: null },
        { processing_time_seconds: undefined },
      ]),
    ).toBeNull();
  });

  it('ignores non-finite and negative durations, which should not realistically occur but must not corrupt the estimate', () => {
    const mean = calculateObservedSecondsPerTerm([
      { processing_time_seconds: 4 },
      { processing_time_seconds: Number.NaN },
      { processing_time_seconds: Number.POSITIVE_INFINITY },
      { processing_time_seconds: -1 },
    ]);
    expect(mean).toBe(4);
  });
});

describe('calculateRemainingSeconds', () => {
  it('matches the spec example: mean=5, remaining=8 -> 40s', () => {
    const seconds = calculateRemainingSeconds({
      total: 10,
      completed: 2,
      results: [{ processing_time_seconds: 4 }, { processing_time_seconds: 6 }],
      retrievalMode: 'public',
    });
    expect(seconds).toBe(40);
  });

  it('matches the spec example: null duration excluded, mean=6, remaining=7 -> 42s', () => {
    const seconds = calculateRemainingSeconds({
      total: 10,
      completed: 3,
      results: [
        { processing_time_seconds: 4 },
        { processing_time_seconds: null },
        { processing_time_seconds: 8 },
      ],
      retrievalMode: 'public',
    });
    expect(seconds).toBe(42);
  });

  it('falls back to the deterministic per-term estimate when no valid durations exist yet', () => {
    const seconds = calculateRemainingSeconds({
      total: 10,
      completed: 0,
      results: [],
      retrievalMode: 'public',
    });
    expect(seconds).toBe(50); // 10 remaining * 5s fallback
  });

  it('uses the retrieval-disabled fallback when no valid durations exist yet', () => {
    const seconds = calculateRemainingSeconds({
      total: 10,
      completed: 0,
      results: [],
      retrievalMode: 'disabled',
    });
    expect(seconds).toBe(20); // 10 remaining * 2s fallback
  });

  it('returns 0 remaining seconds once every row is completed', () => {
    const seconds = calculateRemainingSeconds({
      total: 5,
      completed: 5,
      results: [{ processing_time_seconds: 3 }],
      retrievalMode: 'public',
    });
    expect(seconds).toBe(0);
  });

  it('a failed row still counts toward completed but does not distort the observed mean', () => {
    const seconds = calculateRemainingSeconds({
      total: 4,
      completed: 2,
      results: [{ processing_time_seconds: 10 }, { processing_time_seconds: null }],
      retrievalMode: 'public',
    });
    // observed mean is 10 (the null row is excluded, not treated as 0), remaining = 2
    expect(seconds).toBe(20);
  });
});
