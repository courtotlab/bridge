export function targetOntologiesOrNull(values: string[]): string[] | null {
  return values.length > 0 ? [...values] : null;
}

// EFO must be selected for a strict toggle to take effect — this keeps a
// stale "on" toggle from silently applying once EFO is deselected.
export function effectiveStrictTargetOntology(
  targetOntologies: string[],
  strictToggleValue: boolean,
): boolean {
  return targetOntologies.includes('EFO') && strictToggleValue;
}

export function appendTargetOntologiesJson(
  form: FormData,
  values: string[] | undefined,
): void {
  if (values && values.length > 0) {
    form.append('target_ontologies_json', JSON.stringify(values));
  }
}
