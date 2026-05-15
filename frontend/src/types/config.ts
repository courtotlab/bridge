export type RetrievalMode = 'public' | 'local' | 'disabled';
export type Provider = 'ollama' | 'ollama_cloud' | 'openai' | 'anthropic';
export type LayerState = 'ok' | 'warning' | 'disabled' | 'error';

export interface AppConfig {
  // Layer 1
  use_ner: boolean;

  // Layer 2
  retrieval_mode: RetrievalMode;
  bioportal_api_key: string | null;
  loinc_username: string | null;
  loinc_password: string | null;
  sapbert_server_url: string;
  rag_auto_accept_threshold: number; // 0.0–1.0

  // Layer 3
  provider: Provider;
  model: string;
  base_url: string;
  api_key: string | null;
}

export interface LayerStatus {
  layer1: LayerState;
  layer2: LayerState;
  layer3: LayerState;
}

export interface ConfigStatusResponse {
  config: AppConfig;
  status: LayerStatus;
}

export interface ConnectionTestResponse {
  success: boolean;
  message: string;
  latency_ms?: number;
  available_models?: string[];
  validation_level?: 'reachability' | 'generation';
  sapbert_status?: 'ok' | 'unreachable' | 'skipped' | null;
  sapbert_message?: string | null;
}

export interface OpenAIModelsResponse {
  models: string[];
  warning?: string;
  error?: string;
}

export interface AnthropicModelsResponse {
  models: string[];
  warning?: string;
  error?: string;
}
