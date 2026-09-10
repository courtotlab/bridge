import type { RetrievalMode } from '../types/config';
import type { MappingMetadata } from '../types/mapping';
import { formatProcessingTime } from './formatDuration';
import { formatRetrievalMode } from './retrievalMode';

export interface MappingDetailsInput {
  explanation?: string | null;
  notes?: string | null;
  retrievalMode?: RetrievalMode | string | null;
  retrievalSource?: string | null;
  configuredProvider?: string | null;
  configuredModel?: string | null;
  metadata?: MappingMetadata | null;
  processingTimeSeconds?: number | null;
}

export interface MappingDetailSection {
  label: string;
  value: string;
}

function cleanText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function formatMappingExplanation(value: unknown): string {
  return cleanText(value)
    .replace(/^Mapped\.\s*/i, '')
    .replace(/^Mapped$/i, '')
    .replace(/^RAG:\s*/i, '')
    .trim();
}

export function getMappingExplanation(details: MappingDetailsInput): string {
  return formatMappingExplanation(details.explanation ?? details.notes);
}

export function formatRetrievalSource(value: unknown): string {
  const source = cleanText(value);
  if (!source) return '';

  const labels: Record<string, string> = {
    rag: 'RAG',
    llm: 'LLM',
    direct: 'Direct',
  };
  return labels[source.toLowerCase()] ?? source;
}

export function getMappingDetailSections(
  details: MappingDetailsInput,
  explanationLabel = 'Why selected',
): MappingDetailSection[] {
  const sections: MappingDetailSection[] = [];
  const explanation = getMappingExplanation(details);
  const retrievalSource = formatRetrievalSource(details.retrievalSource);
  const provider = cleanText(details.configuredProvider) || cleanText(details.metadata?.provider);
  const model = cleanText(details.configuredModel) || cleanText(details.metadata?.model);

  if (explanation) {
    sections.push({ label: explanationLabel, value: explanation });
  }
  if (details.retrievalMode !== undefined && details.retrievalMode !== null) {
    sections.push({ label: 'Retrieval method', value: formatRetrievalMode(details.retrievalMode) });
  }
  if (retrievalSource) {
    sections.push({ label: 'Retrieval source', value: retrievalSource });
  }
  if (provider) {
    sections.push({ label: 'AI provider', value: provider });
  }
  if (model) {
    sections.push({ label: 'Model', value: model });
  }
  if (details.processingTimeSeconds != null) {
    sections.push({
      label: 'Processing time',
      value: formatProcessingTime(details.processingTimeSeconds),
    });
  }

  return sections;
}

export function hasMappingDetails(details: MappingDetailsInput): boolean {
  return getMappingDetailSections(details).length > 0;
}
