import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { vi } from 'vitest';

import { getOntologyDisplayName, ONTOLOGY_OPTIONS } from '../constants/ontologies';
import OntologyMultiSelect from './OntologyMultiSelect';

const helperText =
  'Selected ontologies restrict the mapping results. Leave all unselected for automatic selection.';

function renderControlled(onChange = vi.fn()) {
  function Harness() {
    const [selectedValues, setSelectedValues] = useState<string[]>([]);
    return (
      <OntologyMultiSelect
        label="Target ontologies"
        options={ONTOLOGY_OPTIONS}
        selectedValues={selectedValues}
        onChange={(values) => {
          setSelectedValues(values);
          onChange(values);
        }}
        helperText={helperText}
      />
    );
  }

  render(<Harness />);
  return onChange;
}

describe('OntologyMultiSelect', () => {
  it('renders all ontology options with none selected', () => {
    renderControlled();

    for (const option of ONTOLOGY_OPTIONS) {
      expect(screen.getByRole('checkbox', { name: option.label })).not.toBeChecked();
    }
  });

  it('exposes EFO in the mapping ontology catalog', () => {
    expect(ONTOLOGY_OPTIONS).toContainEqual({ value: 'EFO', label: 'EFO' });
    expect(getOntologyDisplayName('EFO')).toBe('Experimental Factor Ontology');
  });

  it('selects one ontology', async () => {
    const user = userEvent.setup();
    renderControlled();

    await user.click(screen.getByRole('checkbox', { name: 'LOINC' }));

    expect(screen.getByRole('checkbox', { name: 'LOINC' })).toBeChecked();
  });

  it('selects multiple ontologies', async () => {
    const user = userEvent.setup();
    renderControlled();

    await user.click(screen.getByRole('checkbox', { name: 'LOINC' }));
    await user.click(screen.getByRole('checkbox', { name: 'HPO' }));

    expect(screen.getByRole('checkbox', { name: 'LOINC' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'HPO' })).toBeChecked();
  });

  it('unselects an ontology', async () => {
    const user = userEvent.setup();
    renderControlled();

    const loinc = screen.getByRole('checkbox', { name: 'LOINC' });
    await user.click(loinc);
    await user.click(loinc);

    expect(loinc).not.toBeChecked();
  });

  it('calls onChange in catalog order', async () => {
    const user = userEvent.setup();
    const onChange = renderControlled();

    await user.click(screen.getByRole('checkbox', { name: 'LOINC' }));
    await user.click(screen.getByRole('checkbox', { name: 'HPO' }));

    expect(onChange).toHaveBeenLastCalledWith(['HPO', 'LOINC']);
  });

  it('connects helper text as an accessible description', () => {
    renderControlled();

    expect(screen.getByRole('group', { name: /target ontologies/i }))
      .toHaveAccessibleDescription(helperText);
  });
});
