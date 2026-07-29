export function targetOntologiesOrNull(values: string[]): string[] | null {
  return values.length > 0 ? [...values] : null;
}

export function appendTargetOntologiesJson(
  form: FormData,
  values: string[] | undefined,
): void {
  if (values && values.length > 0) {
    form.append('target_ontologies_json', JSON.stringify(values));
  }
}
