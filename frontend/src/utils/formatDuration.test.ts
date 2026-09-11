import { describe, expect, it } from 'vitest';
import { formatEtaDuration, formatProcessingTime } from './formatDuration';

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

describe('formatEtaDuration', () => {
  it('keeps the "~" prefix', () => {
    expect(formatEtaDuration(30)).toMatch(/^~/);
    expect(formatEtaDuration(90)).toMatch(/^~/);
  });

  it('shows whole seconds under the 1-minute boundary', () => {
    expect(formatEtaDuration(1)).toBe('~1 sec');
    expect(formatEtaDuration(45)).toBe('~45 sec');
    expect(formatEtaDuration(59)).toBe('~59 sec');
  });

  it('never displays "0 sec" while work remains', () => {
    expect(formatEtaDuration(0)).toBe('~1 sec');
    expect(formatEtaDuration(0.4)).toBe('~1 sec');
  });

  it('switches to minutes at the 60-second boundary', () => {
    expect(formatEtaDuration(60)).toBe('~1 min');
    expect(formatEtaDuration(61)).toBe('~1 min');
  });

  it('rounds minutes to the nearest whole minute', () => {
    expect(formatEtaDuration(89)).toBe('~1 min');
    expect(formatEtaDuration(90)).toBe('~2 min');
    expect(formatEtaDuration(119)).toBe('~2 min');
    expect(formatEtaDuration(120)).toBe('~2 min');
  });

  it('never displays "0 min"', () => {
    expect(formatEtaDuration(59.9)).not.toBe('~0 min');
  });
});
