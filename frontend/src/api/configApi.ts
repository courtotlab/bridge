import type { AppConfig, ConfigStatusResponse, ConnectionTestResponse } from '../types/config';
import client from './client';

export async function getConfig(): Promise<AppConfig> {
  const { data } = await client.get<AppConfig>('/config');
  return data;
}

export async function saveConfig(config: AppConfig): Promise<AppConfig> {
  const { data } = await client.post<AppConfig>('/config', config);
  return data;
}

export async function testConnection(): Promise<ConnectionTestResponse> {
  const { data } = await client.post<ConnectionTestResponse>('/config/test');
  return data;
}

export async function getOllamaModels(): Promise<string[]> {
  const { data } = await client.get<string[]>('/config/ollama-models');
  return data;
}

export async function getStatus(): Promise<ConfigStatusResponse> {
  const { data } = await client.get<ConfigStatusResponse>('/config/status');
  return data;
}
