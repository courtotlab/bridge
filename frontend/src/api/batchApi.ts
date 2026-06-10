import client from './client';
import type { BatchUploadPreview, BatchJobStatus } from '../types/mapping';

export async function uploadPreview(file: File): Promise<BatchUploadPreview> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await client.post<BatchUploadPreview>('/batch/upload-preview', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function startBatch(params: {
  file: File;
  columnMap: Record<string, string | null>;
  clinicalArea: string | null;
  useRag: boolean;
  autoAcceptThreshold: number;
}): Promise<{ job_id: string; total: number }> {
  const form = new FormData();
  form.append('file', params.file);
  form.append('column_map_json', JSON.stringify(params.columnMap));
  if (params.clinicalArea) form.append('clinical_area', params.clinicalArea);
  form.append('use_rag', String(params.useRag));
  form.append('auto_accept_threshold', String(params.autoAcceptThreshold));
  const { data } = await client.post('/batch/start', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function getBatchStatus(jobId: string): Promise<BatchJobStatus> {
  const { data } = await client.get<BatchJobStatus>(`/batch/status/${jobId}`);
  return data;
}

export async function cancelBatch(jobId: string): Promise<void> {
  await client.post(`/batch/cancel/${jobId}`);
}

export async function setDecision(
  jobId: string,
  rowIndex: number,
  decision: 'accepted' | 'rejected' | 'pending',
): Promise<void> {
  await client.patch(`/batch/decision/${jobId}/${rowIndex}`, { decision });
}

export function exportUrl(jobId: string): string {
  return `http://localhost:8000/api/batch/export/${jobId}`;
}
