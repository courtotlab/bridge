import client from './client';
import type { AlternativeResult, BatchJobStatus, BatchRowResult, BatchUploadPreview } from '../types/mapping';
import { appendTargetOntologiesJson } from '../utils/ontologyPayloads';

function apiErrorMessage(error: unknown, fallback: string): string {
  if (
    typeof error === 'object'
    && error !== null
    && 'response' in error
    && typeof error.response === 'object'
    && error.response !== null
    && 'data' in error.response
  ) {
    const data = error.response.data;
    if (
      typeof data === 'object'
      && data !== null
      && 'detail' in data
      && typeof data.detail === 'string'
    ) {
      return data.detail;
    }
  }
  return error instanceof Error ? error.message : fallback;
}

export async function uploadPreview(file: File): Promise<BatchUploadPreview> {
  const form = new FormData();
  form.append('file', file);
  try {
    const { data } = await client.post<BatchUploadPreview>('/batch/upload-preview', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  } catch (error) {
    throw new Error(apiErrorMessage(error, 'Could not parse file.'));
  }
}

export async function startBatch(params: {
  file: File;
  columnMap: Record<string, string | null>;
  clinicalArea?: string | null;
  targetOntologyColumn?: string | null;
  targetOntologies?: string[];
  useRag: boolean;
  autoAcceptThreshold: number;
  sessionId?: string | null;
  strictTargetOntology?: boolean;
}): Promise<{ job_id: string; total: number }> {
  const form = new FormData();
  form.append('file', params.file);
  form.append('column_map_json', JSON.stringify(params.columnMap));
  if (params.clinicalArea) form.append('clinical_area', params.clinicalArea);
  if (params.targetOntologyColumn) {
    form.append('target_ontology_column', params.targetOntologyColumn);
  }
  appendTargetOntologiesJson(form, params.targetOntologies);
  form.append('use_rag', String(params.useRag));
  form.append('auto_accept_threshold', String(params.autoAcceptThreshold));
  if (params.sessionId) form.append('session_id', params.sessionId);
  form.append('strict_target_ontology', String(params.strictTargetOntology ?? false));
  try {
    const { data } = await client.post('/batch/start', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return data;
  } catch (error) {
    throw new Error(apiErrorMessage(error, 'Failed to start batch job.'));
  }
}

export async function getBatchStatus(jobId: string): Promise<BatchJobStatus> {
  const { data } = await client.get<BatchJobStatus>(`/batch/status/${jobId}`);
  return data;
}

export async function cancelBatch(
  jobId: string,
  timeoutMs = 5000,
): Promise<{ interrupted: boolean }> {
  const { data } = await client.post<{ interrupted: boolean }>(
    `/batch/cancel/${jobId}`,
    undefined,
    { timeout: timeoutMs },
  );
  return data;
}

export function cancelBatchKeepalive(jobId: string): boolean {
  const url = `${client.defaults.baseURL}/batch/cancel/${jobId}`;
  if (navigator.sendBeacon) {
    return navigator.sendBeacon(url, new Blob([], { type: 'application/json' }));
  }

  fetch(url, { method: 'POST', keepalive: true }).catch(() => {});
  return true;
}

export async function setDecision(
  jobId: string,
  rowIndex: number,
  decision: 'accepted' | 'rejected' | 'pending',
): Promise<void> {
  await client.patch(`/batch/decision/${jobId}/${rowIndex}`, { decision });
}

export async function promoteAlternative(
  jobId: string,
  rowIndex: number,
  alternative: Pick<AlternativeResult, 'code' | 'ontology'>,
): Promise<BatchRowResult> {
  const { data } = await client.patch<{ updated: true; row: BatchRowResult }>(
    `/batch/promote/${jobId}/${rowIndex}`,
    {
      code: alternative.code,
      ontology: alternative.ontology,
    },
  );
  return data.row;
}

export function exportUrl(jobId: string): string {
  return `http://localhost:8000/api/batch/export/${jobId}`;
}
