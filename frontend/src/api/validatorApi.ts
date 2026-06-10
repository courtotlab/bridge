import type { ValidateCodeRequest, ValidateCodeResponse } from '../types/validator';
import client from './client';

export async function validateCodes(
  request: ValidateCodeRequest,
): Promise<ValidateCodeResponse> {
  const { data } = await client.post<ValidateCodeResponse>('/validate', request);
  return data;
}
