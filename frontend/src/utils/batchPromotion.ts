import type { AlternativeResult, BatchRowResult } from '../types/mapping';

function candidateKey(candidate: { code?: string; suggested_code?: string; ontology?: string }): string {
  const code = candidate.code ?? candidate.suggested_code ?? '';
  return `${candidate.ontology ?? ''}::${code}`.trim().toLowerCase();
}

function isUnmappedCode(code: string): boolean {
  return code.toUpperCase().includes('UNMAPPED');
}

function rowToAlternative(row: BatchRowResult): AlternativeResult {
  return {
    code: row.suggested_code,
    term: row.suggested_term,
    ontology: row.ontology,
    confidence: row.confidence,
    source: row.logic_type,
    explanation: row.notes,
  };
}

export function promoteBatchAlternative(
  row: BatchRowResult,
  alternative: AlternativeResult,
): BatchRowResult {
  const promotedKey = candidateKey(alternative);
  const currentPrimary = rowToAlternative(row);
  const shouldDemotePrimary = !isUnmappedCode(row.suggested_code);

  const alternatives = row.alternatives.reduce<AlternativeResult[]>((acc, candidate) => {
    const currentKey = candidateKey(candidate);
    if (currentKey === promotedKey) {
      if (shouldDemotePrimary) {
        acc.push(currentPrimary);
      }
      return acc;
    }
    if (shouldDemotePrimary && currentKey === candidateKey(currentPrimary)) {
      return acc;
    }
    acc.push(candidate);
    return acc;
  }, []);

  return {
    ...row,
    suggested_code: alternative.code,
    suggested_term: alternative.term,
    ontology: alternative.ontology,
    confidence: alternative.confidence,
    logic_type: alternative.source ?? row.logic_type,
    notes: alternative.explanation,
    decision: 'pending',
    alternatives,
  };
}
