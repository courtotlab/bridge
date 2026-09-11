import { describe, expect, it } from 'vitest';
import type { AlternativeResult, BatchRowResult } from '../types/mapping';
import { promoteBatchAlternative } from './batchPromotion';

function row(overrides: Partial<BatchRowResult> = {}): BatchRowResult {
  return {
    row_index: 7,
    field_name: 'bp',
    label: 'Blood pressure',
    suggested_code: 'LOINC:8480-6',
    suggested_term: 'Systolic blood pressure',
    ontology: 'LOINC',
    confidence: 0.91,
    logic_type: 'rag',
    decision: 'accepted',
    notes: 'Primary explanation.',
    configured_provider: 'ollama',
    configured_model: 'llama3.2',
    retrieval_mode: 'public',
    alternatives: [
      alternative({
        code: 'HP:0000822',
        term: 'Hypertension',
        confidence: 0.74,
        source: 'llm',
        explanation: 'Alternative explanation.',
      }),
      alternative({
        code: 'HP:0002615',
        term: 'Hypotension',
        confidence: 0.52,
      }),
    ],
    ...overrides,
  };
}

function alternative(overrides: Partial<AlternativeResult> = {}): AlternativeResult {
  return {
    code: 'HP:0000001',
    term: 'All',
    ontology: 'HPO',
    confidence: 0.5,
    ...overrides,
  };
}

describe('promoteBatchAlternative', () => {
  it('promotes an alternative and demotes the former primary in the same position', () => {
    const original = row();
    const updated = promoteBatchAlternative(original, original.alternatives[0]);

    expect(updated).not.toBe(original);
    expect(updated.suggested_code).toBe('HP:0000822');
    expect(updated.suggested_term).toBe('Hypertension');
    expect(updated.ontology).toBe('HPO');
    expect(updated.confidence).toBe(0.74);
    expect(updated.logic_type).toBe('llm');
    expect(updated.notes).toBe('Alternative explanation.');
    expect(updated.decision).toBe('pending');
    expect(updated.alternatives).toHaveLength(2);
    expect(updated.alternatives[0]).toMatchObject({
      code: 'LOINC:8480-6',
      term: 'Systolic blood pressure',
      ontology: 'LOINC',
      confidence: 0.91,
      source: 'rag',
      explanation: 'Primary explanation.',
    });
    expect(updated.alternatives[1].code).toBe('HP:0002615');
    expect(original.suggested_code).toBe('LOINC:8480-6');
  });

  it('resets a rejected row to pending', () => {
    const original = row({ decision: 'rejected' });
    const updated = promoteBatchAlternative(original, original.alternatives[0]);

    expect(updated.decision).toBe('pending');
  });

  it('does not create an unmapped alternative when promoting from an unmapped primary', () => {
    const original = row({
      suggested_code: 'UNMAPPED',
      suggested_term: 'UNMAPPED',
      ontology: '',
      confidence: 0,
      decision: 'rejected',
    });
    const updated = promoteBatchAlternative(original, original.alternatives[0]);

    expect(updated.suggested_code).toBe('HP:0000822');
    expect(updated.decision).toBe('pending');
    expect(updated.alternatives).toHaveLength(1);
    expect(updated.alternatives.map((candidate) => candidate.code)).not.toContain('UNMAPPED');
  });

  it('handles missing optional metadata and repeated promotions without duplicates', () => {
    const original = row({
      notes: undefined,
      alternatives: [
        alternative({ code: 'HP:1', term: 'First', confidence: 0.7 }),
        alternative({ code: 'HP:2', term: 'Second', confidence: 0.6 }),
      ],
    });

    const first = promoteBatchAlternative(original, original.alternatives[0]);
    const second = promoteBatchAlternative(first, first.alternatives[1]);

    expect(first.notes).toBeUndefined();
    expect(second.suggested_code).toBe('HP:2');
    expect(second.alternatives.map((candidate) => `${candidate.ontology}:${candidate.code}`))
      .toEqual(['LOINC:LOINC:8480-6', 'HPO:HP:1']);
    expect(new Set(second.alternatives.map((candidate) => `${candidate.ontology}:${candidate.code}`)).size)
      .toBe(second.alternatives.length);
  });
});
