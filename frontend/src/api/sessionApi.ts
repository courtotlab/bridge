import client from './client';

export type SessionType = 'validation' | 'term_search' | 'batch_map';

export interface InputSummary {
  filename?: string;
  row_count?: number;
  term?: string;
  codes?: string[];
  clinical_area?: string;
  target_ontology_column?: string | null;
  target_ontologies?: string[] | null;
  target_ontology?: string | null;
  auto_accept_threshold?: number;
}

export interface SessionEvent {
  timestamp: string;
  actor: 'user' | 'system';
  event_type: string;
  payload: Record<string, unknown>;
}

export async function createSession(
  type: SessionType,
  input_summary: InputSummary,
): Promise<{ session_id: string }> {
  const { data } = await client.post<{ session_id: string }>('/history', { type, input_summary });
  return data;
}

export async function appendEvent(sessionId: string, event: SessionEvent): Promise<void> {
  await client.patch(`/history/${sessionId}/event`, event);
}

export async function completeSession(
  sessionId: string,
  status: 'complete' | 'error' | 'interrupted',
  result_snapshot?: unknown,
): Promise<void> {
  await client.patch(`/history/${sessionId}/complete`, {
    status,
    result_snapshot: result_snapshot ?? null,
  });
}
