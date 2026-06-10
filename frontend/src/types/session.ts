export type SessionType = 'validation' | 'term_search' | 'batch_map';
export type SessionStatus = 'in_progress' | 'complete' | 'error';

export interface InputSummary {
  filename?: string;
  row_count?: number;
  term?: string;
  codes?: string[];
  clinical_area?: string;
  target_ontology?: string;
  auto_accept_threshold?: number;
}

export interface EventRecord {
  timestamp: string;
  actor: 'user' | 'system';
  event_type: string;
  payload: Record<string, unknown>;
}

export interface SessionSummary {
  session_id: string;
  type: SessionType;
  created_at: string;
  updated_at: string;
  status: SessionStatus;
  input_summary: InputSummary;
  event_count: number;
}

export interface SessionRecord extends SessionSummary {
  events: EventRecord[];
  result_snapshot: unknown;
}
