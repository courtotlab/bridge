import {
  appendTargetOntologiesJson,
  targetOntologiesOrNull,
} from './ontologyPayloads';

describe('targetOntologiesOrNull', () => {
  it('serializes an empty selection as null', () => {
    expect(targetOntologiesOrNull([])).toBeNull();
  });

  it('serializes one ontology as an array', () => {
    expect(targetOntologiesOrNull(['LOINC'])).toEqual(['LOINC']);
  });

  it('serializes multiple ontologies as an array', () => {
    expect(targetOntologiesOrNull(['LOINC', 'HPO'])).toEqual(['LOINC', 'HPO']);
  });

  it('never serializes multiple ontologies as a comma-separated string', () => {
    expect(targetOntologiesOrNull(['LOINC', 'HPO'])).not.toBe('LOINC,HPO');
  });
});

describe('appendTargetOntologiesJson', () => {
  it('omits target_ontologies_json for an empty selection', () => {
    const form = new FormData();

    appendTargetOntologiesJson(form, []);

    expect(form.has('target_ontologies_json')).toBe(false);
  });

  it('serializes one ontology as a JSON array', () => {
    const form = new FormData();

    appendTargetOntologiesJson(form, ['LOINC']);

    expect(form.get('target_ontologies_json')).toBe('["LOINC"]');
  });

  it('serializes multiple ontologies as a JSON array', () => {
    const form = new FormData();

    appendTargetOntologiesJson(form, ['LOINC', 'HPO']);

    expect(form.get('target_ontologies_json')).toBe('["LOINC","HPO"]');
  });

  it('never serializes multiple ontologies as a comma-separated string', () => {
    const form = new FormData();

    appendTargetOntologiesJson(form, ['LOINC', 'HPO']);

    expect(form.get('target_ontologies_json')).not.toBe('LOINC,HPO');
  });
});
