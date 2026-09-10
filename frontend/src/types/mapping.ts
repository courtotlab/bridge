import type { RetrievalMode } from './config';

export interface SingleMappingRequest {
  source_term: string;
  source_label?: string;
  source_description?: string;
  source_type?: string;       // data type: numeric, text, boolean, etc.
  entity_type?: string;       // clinical area: phenotype, disease, etc.
  target_ontologies?: string[] | null; // null/undefined = automatic routing
  strict_target_ontology?: boolean;
}

export interface AlternativeResult {
  code: string;
  term: string;
  ontology: string;
  confidence: number;
  source?: string; // "llm" | "rag" | "direct"
  explanation?: string;
  url?: string | null; // derived ontology entity link — backend-computed
}

export interface MappingMetadata {
  model: string;
  provider: string;
  latency_ms?: number;
  timestamp?: string;
  prompt_tokens?: number;
  completion_tokens?: number;
}

export interface SingleMappingResponse {
  source_term: string;
  source_label?: string;
  source_type?: string;
  target_code: string;
  target_term: string;
  ontology: string;
  confidence: number;
  logic_type: string;
  notes?: string;        // top-level best-match explanation (from backend)
  explanation?: string;  // set on synthetic promoted responses (client-side only)
  alternatives: AlternativeResult[];
  metadata?: MappingMetadata;
  configured_provider?: string;
  configured_model?: string;
  retrieval_mode?: RetrievalMode | null;
  target_url?: string | null; // derived ontology entity link — backend-computed
}

export interface BatchUploadPreview {
  filename: string;
  row_count: number;
  columns: string[];
  preview: Record<string, string>[];
}

export interface BatchRowResult {
  row_index: number;
  field_name: string;
  label?: string;
  source_description?: string | null;
  original_row?: Record<string, unknown>;
  original_columns?: string[];
  requested_target_ontology?: string | null;
  suggested_code: string;
  suggested_term: string;
  ontology: string;
  confidence: number;
  logic_type: string;
  decision: 'accepted' | 'rejected' | 'pending';
  alternatives: AlternativeResult[];
  notes?: string;
  configured_provider?: string;
  configured_model?: string;
  retrieval_mode?: RetrievalMode | null;
  suggested_url?: string | null; // derived ontology entity link — backend-computed
}

export interface BatchJobStatus {
  job_id: string;
  total: number;
  completed: number;
  results: BatchRowResult[];
  status: 'running' | 'done' | 'interrupted' | 'failed';
  error?: string | null;
}
