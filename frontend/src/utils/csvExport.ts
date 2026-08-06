import type { BatchRowResult, SingleMappingResponse } from '../types/mapping';
import type { ValidateCodeResult } from '../types/validator';

export function escapeCsvCell(value: string | number | undefined | null): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return text.includes(',') || text.includes('"') || text.includes('\n')
    ? `"${text.replace(/"/g, '""')}"`
    : text;
}

export function rowsToCsv(headers: string[], rows: Array<Array<string | number | undefined | null>>): string {
  return [
    headers.map(escapeCsvCell).join(','),
    ...rows.map((row) => row.map(escapeCsvCell).join(',')),
  ].join('\n');
}

export function downloadTextFile(content: string, filename: string, type = 'text/csv;charset=utf-8;'): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function confidenceLevel(confidence: number): string {
  if (confidence >= 0.8) return 'High';
  if (confidence >= 0.5) return 'Medium';
  return 'Low';
}

export function buildTermMappingCsv(response: SingleMappingResponse, sessionDate?: string): string {
  return rowsToCsv(
    [
      'source_term',
      'source_label',
      'source_type',
      'target_code',
      'target_term',
      'ontology',
      'confidence',
      'confidence_level',
      'logic_type',
      'retrieval_method',
      'provider',
      'model',
      'notes',
      'session_date',
    ],
    [[
      response.source_term,
      response.source_label,
      response.source_type,
      response.target_code,
      response.target_term,
      response.ontology,
      response.confidence,
      confidenceLevel(response.confidence),
      response.logic_type,
      response.retrieval_mode,
      response.configured_provider,
      response.configured_model,
      response.explanation ?? response.notes,
      sessionDate,
    ]],
  );
}

export function downloadTermMappingCsv(response: SingleMappingResponse, sessionDate?: string): void {
  downloadTextFile(buildTermMappingCsv(response, sessionDate), `${response.source_term}_mapping.csv`);
}

export function buildValidationCsv(rows: ValidateCodeResult[], sessionDate?: string): string {
  return rowsToCsv(
    ['Code', 'Status', 'Term', 'Ontology', 'Session date'],
    rows.map((row) => [row.code, row.status, row.term ?? '', row.ontology ?? '', sessionDate]),
  );
}

export function downloadValidationCsv(rows: ValidateCodeResult[], sessionDate?: string): void {
  downloadTextFile(buildValidationCsv(rows, sessionDate), 'validator-results.csv');
}

export function buildBatchRowsCsv(rows: BatchRowResult[]): string {
  return rowsToCsv(
    [
      'field_name',
      'label',
      'suggested_code',
      'suggested_term',
      'ontology',
      'confidence',
      'decision',
    ],
    rows.map((row) => [
      row.field_name,
      row.label ?? '',
      row.suggested_code,
      row.suggested_term,
      row.ontology,
      `${Math.round(row.confidence * 100)}%`,
      row.decision,
    ]),
  );
}

export function downloadBatchRowsCsv(rows: BatchRowResult[], filename = 'batch-results.csv'): void {
  downloadTextFile(buildBatchRowsCsv(rows), filename);
}
