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

export type ConnectionTestErrorType =
  | 'invalid_api_key'
  | 'subscription_required'
  | 'model_unavailable'
  | 'quota_exceeded'
  | 'permission_denied'
  | 'model_not_supported'
  | 'model_test_failed'
  | 'network_error'
  | 'unknown';

export interface ConnectionTestResponse {
  success: boolean;
  message: string;
  latency_ms?: number;
  available_models?: string[];
  validation_level?: 'api_key' | 'discovery' | 'reachability' | 'generation';
  sapbert_status?: 'ok' | 'unreachable' | 'skipped' | null;
  sapbert_message?: string | null;
  provider_ok?: boolean | null;
  api_key_ok?: boolean | null;
  model_ok?: boolean | null;
  error_type?: ConnectionTestErrorType | null;
  warning?: string | null;
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
