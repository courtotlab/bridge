import { describe, expect, it } from 'vitest';
import { formatProcessingTime } from './formatDuration';

describe('formatProcessingTime', () => {
  it('renders a tiny positive value as "< 0.01 s"', () => {
    expect(formatProcessingTime(0.004)).toBe('< 0.01 s');
  });

  it('renders sub-10s values with two decimal places', () => {
    expect(formatProcessingTime(0.37)).toBe('0.37 s');
    expect(formatProcessingTime(4.82)).toBe('4.82 s');
  });

  it('renders 10-100s values with one decimal place', () => {
    expect(formatProcessingTime(15.4)).toBe('15.4 s');
    expect(formatProcessingTime(87.2)).toBe('87.2 s');
  });

  it('renders values of 100s or more as whole seconds', () => {
    expect(formatProcessingTime(123)).toBe('123 s');
    expect(formatProcessingTime(241)).toBe('241 s');
  });

  it('avoids unnecessary trailing zeros', () => {
    expect(formatProcessingTime(4.8)).toBe('4.8 s');
    expect(formatProcessingTime(5)).toBe('5 s');
  });
});
