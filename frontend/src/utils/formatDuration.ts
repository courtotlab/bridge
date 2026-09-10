/**
 * Formats a mapper processing-time value (seconds) for display.
 * Precision tiers keep short mappings readable without noise on longer ones.
 */
export function formatProcessingTime(seconds: number): string {
  if (seconds > 0 && seconds < 0.01) return '< 0.01 s';
  if (seconds < 10) return `${roundTo(seconds, 2)} s`;
  if (seconds < 100) return `${roundTo(seconds, 1)} s`;
  return `${Math.round(seconds)} s`;
}

function roundTo(value: number, decimals: number): string {
  return Number(value.toFixed(decimals)).toString();
}
