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

/**
 * Formats an ETA value (seconds) for display, e.g. "~42 sec" / "~2 min".
 * Coarser than formatProcessingTime on purpose — an estimate doesn't need
 * sub-second precision, and always shows at least 1 sec/min so "0" is never
 * displayed while work remains.
 */
export function formatEtaDuration(seconds: number): string {
  const clamped = Math.max(0, seconds);
  if (clamped < 60) {
    return `~${Math.max(1, Math.round(clamped))} sec`;
  }
  const minutes = Math.max(1, Math.round(clamped / 60));
  return `~${minutes} min`;
}
