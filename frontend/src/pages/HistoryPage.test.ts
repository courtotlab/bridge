import { formatOntologySummary } from './HistoryPage';

describe('formatOntologySummary', () => {
  it('displays a plural ontology list', () => {
    expect(formatOntologySummary({ target_ontologies: ['LOINC', 'HPO'] }))
      .toBe('LOINC, HPO');
  });

  it('displays a legacy singular ontology value', () => {
    expect(formatOntologySummary({ target_ontology: 'LOINC' })).toBe('LOINC');
  });

  it('displays automatic routing when no ontology metadata exists', () => {
    expect(formatOntologySummary({})).toBe('Automatic');
  });
});
