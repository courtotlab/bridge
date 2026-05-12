export interface ConfigTestRequest {
  provider: string;
  model: string;
  base_url?: string;
  use_retrieval_grounding: boolean;
  selected_ontologies: string[];
  confidence_threshold: number;
}

export interface ConfigTestResponse {
  success: boolean;
  message: string;
}
