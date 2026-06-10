import type { SingleMappingRequest, SingleMappingResponse } from '../types/mapping';
import client from './client';

export async function mapSingleTerm(
  request: SingleMappingRequest,
): Promise<SingleMappingResponse> {
  const { data } = await client.post<SingleMappingResponse>('/map/single', request);
  return data;
}
