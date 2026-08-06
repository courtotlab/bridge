import { describe, expect, it } from 'vitest';
import { detectColumnMappings, normalizeColumnHeader } from './columnDetection';

describe('normalizeColumnHeader', () => {
  it('treats spaces, hyphens, underscores, capitalization, and BOMs equivalently', () => {
    expect(normalizeColumnHeader('\uFEFF SOURCE-LABEL ')).toBe('source_label');
    expect(normalizeColumnHeader('Source Label')).toBe('source_label');
    expect(normalizeColumnHeader('source__label')).toBe('source_label');
  });
});

describe('detectColumnMappings', () => {
  it('selects source_label as Human-readable label', () => {
    expect(detectColumnMappings(['field_name', 'source_label']).sourceLabel)
      .toBe('source_label');
  });

  it('selects variable_label when source_label is absent', () => {
    expect(detectColumnMappings(['field_name', 'variable_label']).sourceLabel)
      .toBe('variable_label');
  });

  it('prefers a specific label alias over generic label', () => {
    expect(detectColumnMappings(['source_variable', 'label', 'field_label']).sourceLabel)
      .toBe('field_label');
  });

  it('selects source_description as Description', () => {
    expect(detectColumnMappings(['field_name', 'source_description']).description)
      .toBe('source_description');
  });

  it('selects description when no higher-priority description alias exists', () => {
    expect(detectColumnMappings(['field_name', 'description']).description)
      .toBe('description');
  });

  it('selects source_data_type as Data type', () => {
    expect(detectColumnMappings(['field_name', 'source_data_type']).dataType)
      .toBe('source_data_type');
  });

  it('recognizes datatype as Data type', () => {
    expect(detectColumnMappings(['field_name', 'datatype']).dataType).toBe('datatype');
  });

  it('preserves original uploaded header spelling in detected mappings', () => {
    expect(detectColumnMappings([
      'source_variable',
      'source-label',
      'Source Description',
      'DATA TYPE',
      'target_ontology',
    ])).toEqual({
      sourceTerm: 'source_variable',
      sourceLabel: 'source-label',
      description: 'Source Description',
      dataType: 'DATA TYPE',
      targetOntology: 'target_ontology',
    });
  });

  it('does not select unrelated type columns as Data type', () => {
    expect(detectColumnMappings([
      'source_variable',
      'record_type',
      'measurement_type',
    ]).dataType).toBeUndefined();
  });

  it('leaves ambiguous equally ranked optional matches unselected', () => {
    expect(detectColumnMappings([
      'source_variable',
      'source_label',
      'Source Label',
    ]).sourceLabel).toBeUndefined();
  });

  it('continues to detect target ontology columns', () => {
    expect(detectColumnMappings(['field_name', 'ontology']).targetOntology).toBe('ontology');
  });

  it('continues to detect Field variable name columns', () => {
    expect(detectColumnMappings(['source_variable', 'source_label']).sourceTerm)
      .toBe('source_variable');
    expect(detectColumnMappings(['variable_name', 'label']).sourceTerm)
      .toBe('variable_name');
  });
});
