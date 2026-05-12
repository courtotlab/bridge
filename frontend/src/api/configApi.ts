import type { ConfigTestRequest, ConfigTestResponse } from '../types/config';
import client from './client';

export async function testConfig(request: ConfigTestRequest): Promise<ConfigTestResponse> {
  const { data } = await client.post<ConfigTestResponse>('/config/test', request);
  return data;
}
