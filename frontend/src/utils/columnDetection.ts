export type ColumnRole =
  | 'sourceTerm'
  | 'sourceLabel'
  | 'description'
  | 'dataType'
  | 'targetOntology';

export type ColumnMappings = Partial<Record<ColumnRole, string>>;

const ROLE_ALIASES: Record<ColumnRole, string[]> = {
  sourceTerm: [
    'field_name',
    'source_variable',
    'source_term',
    'variable_name',
    'field',
    'variable',
    'var_name',
    'name',
  ],
  sourceLabel: [
    'source_label',
    'human_readable_label',
    'human-readable label',
    'variable_label',
    'field_label',
    'display_label',
    'label',
  ],
  description: [
    'source_description',
    'variable_description',
    'field_description',
    'description',
    'definition',
  ],
  dataType: [
    'source_data_type',
    'source_datatype',
    'variable_data_type',
    'variable_datatype',
    'field_data_type',
    'field_datatype',
    'data_type',
    'datatype',
    'type',
  ],
  targetOntology: [
    'target_ontology',
    'target_ontologies',
    'ontology',
  ],
};

export function normalizeColumnHeader(header: string): string {
  return header
    .replace(/^\uFEFF/, '')
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function aliasPriorityByNormalizedValue(role: ColumnRole): Map<string, number> {
  const priorities = new Map<string, number>();
  ROLE_ALIASES[role].forEach((alias, index) => {
    const normalized = normalizeColumnHeader(alias);
    if (!priorities.has(normalized)) {
      priorities.set(normalized, index);
    }
  });
  return priorities;
}

function detectRole(headers: string[], role: ColumnRole): string | undefined {
  const priorities = aliasPriorityByNormalizedValue(role);
  const rankedMatches = headers
    .map((header) => ({
      header,
      priority: priorities.get(normalizeColumnHeader(header)),
    }))
    .filter((match): match is { header: string; priority: number } => (
      match.priority !== undefined
    ));

  if (rankedMatches.length === 0) {
    return undefined;
  }

  const bestPriority = Math.min(...rankedMatches.map((match) => match.priority));
  const bestMatches = rankedMatches.filter((match) => match.priority === bestPriority);
  return bestMatches.length === 1 ? bestMatches[0].header : undefined;
}

export function detectColumnMappings(headers: string[]): ColumnMappings {
  return {
    sourceTerm: detectRole(headers, 'sourceTerm') ?? headers[0],
    sourceLabel: detectRole(headers, 'sourceLabel'),
    description: detectRole(headers, 'description'),
    dataType: detectRole(headers, 'dataType'),
    targetOntology: detectRole(headers, 'targetOntology'),
  };
}
