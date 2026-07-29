export interface OntologyOption {
  value: string;
  label: string;
}

export const ONTOLOGY_OPTIONS: OntologyOption[] = [
  { value: 'HPO', label: 'HPO' },
  { value: 'MONDO', label: 'MONDO' },
  { value: 'NCIT', label: 'NCIT' },
  { value: 'LOINC', label: 'LOINC' },
  { value: 'ICD10', label: 'ICD10' },
  { value: 'CHEBI', label: 'CHEBI' },
  { value: 'SNOMED', label: 'SNOMED' },
  { value: 'RxNorm', label: 'RxNorm' },
];

export const ONTOLOGY_FULL_NAMES: Record<string, string> = {
  HPO: 'Human Phenotype Ontology',
  MONDO: 'Monarch Disease Ontology',
  NCIT: 'NCI Thesaurus',
  LOINC: 'Logical Observation Identifiers Names and Codes',
  ICD10: 'International Classification of Diseases, 10th Revision',
  CHEBI: 'Chemical Entities of Biological Interest',
  SNOMED: 'SNOMED Clinical Terms',
  RXNORM: 'RxNorm',
};

export function getOntologyDisplayName(value: string): string {
  return ONTOLOGY_FULL_NAMES[value.toUpperCase()] ?? value;
}
