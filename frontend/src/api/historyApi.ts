import client from './client';
import type { HistoryDetails, SessionSummary } from '../types/session';

export async function getSessions(): Promise<SessionSummary[]> {
  const { data } = await client.get<SessionSummary[]>('/history');
  return data;
}

export async function getSession(id: string): Promise<HistoryDetails> {
  const { data } = await client.get<HistoryDetails>(`/history/${id}`);
  return data;
}

export async function deleteSession(id: string): Promise<void> {
  await client.delete(`/history/${id}`);
}

export function exportUrl(id: string): string {
  return `http://localhost:8000/api/history/${id}/export`;
}

export function batchCsvExportUrl(id: string): string {
  return `http://localhost:8000/api/history/${id}/batch-csv`;
}
