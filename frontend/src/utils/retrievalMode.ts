import type { RetrievalMode } from '../types/config';

export const RETRIEVAL_MODE_LABELS: Record<RetrievalMode, string> = {
  public: 'Public ontology databases (grounded)',
  local: 'Local retrieval (grounded)',
  disabled: 'Disabled (ungrounded)',
};

export const RETRIEVAL_MODE_TOOLTIP =
  'Grounded mappings use candidates retrieved from ontology sources before the AI selects a match. Ungrounded mappings rely on the AI model without candidate retrieval.';

export function isRetrievalMode(value: unknown): value is RetrievalMode {
  return value === 'public' || value === 'local' || value === 'disabled';
}

export function formatRetrievalMode(value: unknown): string {
  return isRetrievalMode(value) ? RETRIEVAL_MODE_LABELS[value] : 'Not recorded';
}
