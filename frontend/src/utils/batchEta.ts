import type { RetrievalMode } from '../types/config';
import type { BatchRowResult } from '../types/mapping';

/**
 * Deterministic per-term fallback used before any current-batch timing
 * observations exist (pre-run estimate, and the live estimate's fallback
 * until at least one row completes with a valid processing_time_seconds).
 * Retrieval-enabled modes ("public"/"local") call out to a retriever in
 * addition to the LLM, so they get the slower fallback; "disabled" skips
 * retrieval entirely.
 */
const FALLBACK_SECONDS_PER_TERM_RETRIEVAL_ENABLED = 5;
const FALLBACK_SECONDS_PER_TERM_RETRIEVAL_DISABLED = 2;

export function getFallbackSecondsPerTerm(
  retrievalMode: RetrievalMode | null | undefined,
): number {
  return retrievalMode === 'disabled'
    ? FALLBACK_SECONDS_PER_TERM_RETRIEVAL_DISABLED
    : FALLBACK_SECONDS_PER_TERM_RETRIEVAL_ENABLED;
}

function isValidDuration(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

/**
 * Arithmetic mean of processing_time_seconds across completed rows, ignoring
 * rows with a missing/null/non-finite duration (failed rows). Returns null
 * when there are no valid observations yet, so callers can fall back to the
 * deterministic per-term estimate.
 */
export function calculateObservedSecondsPerTerm(
  results: Pick<BatchRowResult, 'processing_time_seconds'>[],
): number | null {
  const validDurations = results
    .map((row) => row.processing_time_seconds)
    .filter(isValidDuration);

  if (validDurations.length === 0) return null;

  const sum = validDurations.reduce((total, duration) => total + duration, 0);
  return sum / validDurations.length;
}

/**
 * Pre-run estimate: total rows in the batch times the deterministic
 * per-term fallback for the current retrieval configuration. Also reused
 * for the static "Estimated time" banner shown while a batch is running,
 * since that banner describes the whole batch, not the remaining work.
 */
export function calculatePreRunEstimateSeconds(params: {
  rowCount: number;
  retrievalMode: RetrievalMode | null | undefined;
}): number {
  const { rowCount, retrievalMode } = params;
  return Math.max(0, rowCount) * getFallbackSecondsPerTerm(retrievalMode);
}

/**
 * Live "estimated time remaining": observed mean per-term duration from the
 * current batch's completed rows (falling back to the deterministic
 * per-term estimate until at least one valid duration exists), times the
 * number of rows not yet completed.
 */
export function calculateRemainingSeconds(params: {
  total: number;
  completed: number;
  results: Pick<BatchRowResult, 'processing_time_seconds'>[];
  retrievalMode: RetrievalMode | null | undefined;
}): number {
  const { total, completed, results, retrievalMode } = params;
  const remainingRows = Math.max(0, total - completed);
  const observedSecondsPerTerm = calculateObservedSecondsPerTerm(results);
  const secondsPerTerm = observedSecondsPerTerm ?? getFallbackSecondsPerTerm(retrievalMode);
  return remainingRows * secondsPerTerm;
}
