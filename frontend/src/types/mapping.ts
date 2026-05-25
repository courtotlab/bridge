export interface SingleMappingRequest {
  source_term: string;
  source_label?: string;
  source_type?: string;       // data type: numeric, text, boolean, etc.
  entity_type?: string;       // clinical area: phenotype, disease, etc.
  target_ontologies?: string; // undefined = auto-detect
}

export interface AlternativeResult {
  code: string;
  term: string;
  ontology: string;
  confidence: number;
  source?: string; // "llm" | "rag" | "direct"
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
  notes?: string;
  alternatives: AlternativeResult[];
  metadata?: MappingMetadata;
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
  suggested_code: string;
  suggested_term: string;
  ontology: string;
  confidence: number;
  logic_type: string;
  decision: 'accepted' | 'rejected' | 'pending';
  alternatives: AlternativeResult[];
}

export interface BatchJobStatus {
  job_id: string;
  total: number;
  completed: number;
  results: BatchRowResult[];
  status: 'running' | 'done' | 'cancelled';
}
