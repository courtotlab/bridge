export interface SingleMappingRequest {
  source_term: string;
  source_label?: string;
  entity_type?: string;
}

export interface MappingAlternative {
  code: string;
  term: string;
  ontology: string;
  confidence: number;
}

export interface SingleMappingResponse {
  source_term: string;
  target_code: string;
  target_term: string;
  ontology: string;
  confidence: number;
  notes: string;
  alternatives: MappingAlternative[];
}
