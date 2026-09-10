import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import BatchResultsTable from './BatchResultsTable';
import type { AlternativeResult, BatchRowResult } from '../types/mapping';

function alternative(overrides: Partial<AlternativeResult> = {}): AlternativeResult {
  return {
    code: 'LOINC:76215-3',
    term: 'Systolic blood pressure alt',
    ontology: 'LOINC',
    confidence: 0.4,
    source: 'rag',
    url: 'https://loinc.org/76215-3',
    ...overrides,
  };
}

function row(overrides: Partial<BatchRowResult> = {}): BatchRowResult {
  return {
    row_index: 0,
    field_name: 'sbp',
    label: 'Systolic BP',
    suggested_code: 'LOINC:8480-6',
    suggested_term: 'Systolic blood pressure',
    ontology: 'LOINC',
    confidence: 0.92,
    logic_type: 'rag',
    decision: 'pending',
    alternatives: [],
    suggested_url: 'https://loinc.org/8480-6',
    ...overrides,
  };
}

function renderTable(rows: BatchRowResult[], extra: Partial<React.ComponentProps<typeof BatchResultsTable>> = {}) {
  const onPromoteAlternative = vi.fn();
  const onToggleExpand = vi.fn();
  const props: React.ComponentProps<typeof BatchResultsTable> = {
    rows,
    expandedRows: new Set(rows.map((r) => r.row_index)),
    filterStatus: 'all',
    searchQuery: '',
    onFilterStatusChange: vi.fn(),
    onSearchQueryChange: vi.fn(),
    onToggleExpand,
    onToggleDecision: vi.fn(),
    onBulkDecision: vi.fn(),
    onPromoteAlternative,
    ...extra,
  };
  return { onPromoteAlternative, onToggleExpand, ...render(<BatchResultsTable {...props} />) };
}

describe('BatchResultsTable ontology links', () => {
  it('renders the suggested code as an external link using suggested_url', () => {
    renderTable([row()]);

    const link = screen.getByRole('link', { name: 'LOINC:8480-6' });
    expect(link).toHaveAttribute('href', 'https://loinc.org/8480-6');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('renders the suggested code as plain text when suggested_url is absent', () => {
    renderTable([row({ suggested_url: undefined })]);

    expect(screen.queryByRole('link', { name: 'LOINC:8480-6' })).not.toBeInTheDocument();
    expect(screen.getByText('LOINC:8480-6')).toBeInTheDocument();
  });

  it('renders an alternative code as its own link using alt.url', () => {
    renderTable([row({ alternatives: [alternative()] })]);

    const link = screen.getByRole('link', { name: 'LOINC:76215-3' });
    expect(link).toHaveAttribute('href', 'https://loinc.org/76215-3');
  });

  it('renders an alternative without a url as plain text', () => {
    renderTable([row({ alternatives: [alternative({ url: undefined })] })]);

    expect(screen.queryByRole('link', { name: 'LOINC:76215-3' })).not.toBeInTheDocument();
    expect(screen.getByText('LOINC:76215-3')).toBeInTheDocument();
  });

  it('does not render a link for an UNMAPPED row', () => {
    renderTable([
      row({
        suggested_code: 'UNMAPPED',
        suggested_term: 'UNMAPPED',
        ontology: '',
        suggested_url: undefined,
      }),
    ]);

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('preserves the existing "Use" promotion button unaffected by the alternative link', async () => {
    const user = userEvent.setup();
    const alt = alternative();
    const { onPromoteAlternative } = renderTable([row({ alternatives: [alt] })]);

    await user.click(screen.getByRole('button', { name: `Use ${alt.code} as the suggested mapping` }));

    expect(onPromoteAlternative).toHaveBeenCalledWith(expect.objectContaining({ row_index: 0 }), alt);
  });

  it('clicking the alternative link does not trigger promotion (no row-level click target exists in batch rows)', async () => {
    const user = userEvent.setup();
    const alt = alternative();
    const { onPromoteAlternative } = renderTable([row({ alternatives: [alt] })]);

    await user.click(screen.getByRole('link', { name: 'LOINC:76215-3' }));

    expect(onPromoteAlternative).not.toHaveBeenCalled();
  });
});

describe('BatchResultsTable processing time', () => {
  it('shows PROCESSING TIME with the row value in the details card', () => {
    renderTable([
      row({
        processing_time_seconds: 4.82,
        notes: 'Strong lexical match.',
        configured_provider: 'ollama',
        configured_model: 'llama3.2',
      }),
    ]);

    expect(screen.getByText('Processing time')).toBeInTheDocument();
    expect(screen.getByText('4.82 s')).toBeInTheDocument();
  });

  it('renders Processing time directly after Model in the details card', () => {
    renderTable([
      row({
        processing_time_seconds: 4.82,
        notes: 'Strong lexical match.',
        configured_provider: 'ollama',
        configured_model: 'llama3.2',
      }),
    ]);

    const sections = Array.from(
      document.querySelectorAll('.mapping-details-tooltip-label'),
    ).map((el) => el.textContent);
    const modelIndex = sections.indexOf('Model');
    const processingIndex = sections.indexOf('Processing time');
    expect(modelIndex).toBeGreaterThanOrEqual(0);
    expect(processingIndex).toBe(modelIndex + 1);
  });

  it('shows a different processing time for each row', () => {
    renderTable([
      row({ row_index: 0, field_name: 'sbp', processing_time_seconds: 1.2, notes: 'Row A' }),
      row({ row_index: 1, field_name: 'temp', suggested_code: 'LOINC:8310-5', processing_time_seconds: 7.4, notes: 'Row B' }),
    ]);

    expect(screen.getByText('1.2 s')).toBeInTheDocument();
    expect(screen.getByText('7.4 s')).toBeInTheDocument();
  });

  it('omits the Processing time section when the value is missing', () => {
    renderTable([row({ processing_time_seconds: undefined, notes: 'Strong lexical match.' })]);

    expect(screen.queryByText('Processing time')).not.toBeInTheDocument();
  });

  it('does not add a visible table column for processing time', () => {
    renderTable([row({ processing_time_seconds: 4.82 })]);

    const headers = Array.from(document.querySelectorAll('th')).map((el) => el.textContent);
    expect(headers.some((h) => /processing time/i.test(h ?? ''))).toBe(false);
  });

  it('leaves existing links, decision buttons, and promotion unaffected', async () => {
    const user = userEvent.setup();
    const alt = alternative();
    const { onPromoteAlternative } = renderTable([
      row({ processing_time_seconds: 4.82, alternatives: [alt] }),
    ]);

    expect(screen.getByRole('link', { name: 'LOINC:8480-6' })).toHaveAttribute(
      'href',
      'https://loinc.org/8480-6',
    );

    await user.click(screen.getByTitle('Accept'));
    await user.click(
      screen.getByRole('button', { name: `Use ${alt.code} as the suggested mapping` }),
    );

    expect(onPromoteAlternative).toHaveBeenCalledWith(expect.objectContaining({ row_index: 0 }), alt);
  });
});
