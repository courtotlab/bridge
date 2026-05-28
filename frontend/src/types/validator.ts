export type ValidateStatus = 'valid' | 'not-found' | 'deprecated';

export interface ValidateCodeRequest {
  codes: string[];
}

export interface ValidateCodeResult {
  code: string;
  status: ValidateStatus;
  term?: string;
  ontology?: string;
}

export interface ValidateCodeResponse {
  results: ValidateCodeResult[];
}
