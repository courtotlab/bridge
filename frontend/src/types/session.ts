import type { BatchRowResult, SingleMappingResponse } from './mapping';
import type { ValidateCodeResult } from './validator';

export type SessionType = 'validation' | 'term_search' | 'batch_map';
export type SessionStatus = 'in_progress' | 'complete' | 'error' | 'interrupted';

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
  strict_target_ontology?: boolean | null;
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

export interface HistoryConfiguration {
  target_ontologies?: string[] | null;
  target_ontology_column?: string | null;
  auto_accept_threshold?: number | null;
  retrieval_method?: string | null;
  provider?: string | null;
  model?: string | null;
  rag_enabled?: boolean | null;
  strict_target_ontology?: boolean | null;
}

export interface HistoryFailure {
  message?: string | null;
}

interface HistoryBaseDetails {
  id: string;
  type: SessionType;
  status: SessionStatus;
  created_at: string;
  completed_at?: string | null;
  input: InputSummary & Record<string, unknown>;
  configuration?: HistoryConfiguration | null;
  failure?: HistoryFailure | null;
  legacy_message?: string | null;
}

export interface TermSearchHistoryDetails extends HistoryBaseDetails {
  type: 'term_search';
  result: {
    best_match?: SingleMappingResponse | null;
    alternatives: SingleMappingResponse['alternatives'];
  };
}

export interface BatchMapHistoryDetails extends HistoryBaseDetails {
  type: 'batch_map';
  result: {
    total?: number | null;
    completed?: number | null;
    status?: string | null;
    rows: BatchRowResult[];
    summary: {
      total_rows?: number | null;
      completed_count?: number | null;
      accepted_count: number;
      pending_count: number;
      rejected_count: number;
      unmapped_count: number;
    };
    error?: string | null;
  };
}

export interface ValidationHistoryDetails extends HistoryBaseDetails {
  type: 'validation';
  result: {
    results: ValidateCodeResult[];
    summary: {
      total_count: number;
      valid_count: number;
      deprecated_count: number;
      not_found_count: number;
      error_count: number;
    };
  };
}

export type HistoryDetails =
  | TermSearchHistoryDetails
  | BatchMapHistoryDetails
  | ValidationHistoryDetails;
