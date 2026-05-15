import type { AnthropicModelsResponse, AppConfig, ConfigStatusResponse, ConnectionTestResponse, OpenAIModelsResponse } from '../types/config';
import client from './client';

export async function getConfig(): Promise<AppConfig> {
  const { data } = await client.get<AppConfig>('/config');
  return data;
}

export async function saveConfig(config: AppConfig): Promise<AppConfig> {
  const { data } = await client.post<AppConfig>('/config', config);
  return data;
}

export async function testConnection(config: AppConfig): Promise<ConnectionTestResponse> {
  const url = `${client.defaults.baseURL}/config/test`;
  console.log(
    '[configApi] testConnection → POST', url,
    '| provider=', config.provider,
    '| model=', config.model || '(empty)',
    '| api_key=', config.api_key ? 'set' : 'empty',
  );
  const { data } = await client.post<ConnectionTestResponse>('/config/test', config);
  console.log(
    '[configApi] testConnection ← success=', data.success,
    '| validation_level=', data.validation_level ?? 'n/a',
    '| models=', data.available_models?.length ?? 0,
    '| message=', data.message,
  );
  return data;
}

export async function getOllamaModels(): Promise<string[]> {
  const { data } = await client.get<string[]>('/config/ollama-models');
  return data;
}

export async function getOpenAIModels(): Promise<OpenAIModelsResponse> {
  const { data } = await client.get<OpenAIModelsResponse>('/config/openai-models');
  return data;
}

export async function getAnthropicModels(): Promise<AnthropicModelsResponse> {
  const { data } = await client.get<AnthropicModelsResponse>('/config/anthropic-models');
  return data;
}

export async function getStatus(): Promise<ConfigStatusResponse> {
  const { data } = await client.get<ConfigStatusResponse>('/config/status');
  return data;
}
