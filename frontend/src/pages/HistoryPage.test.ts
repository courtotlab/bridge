import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { HistoryDetails, SessionSummary } from '../types/session';
import { formatOntologySummary } from './HistoryPage';
import HistoryPage from './HistoryPage';

const historyApi = vi.hoisted(() => ({
  getSessions: vi.fn(),
  getSession: vi.fn(),
  deleteSession: vi.fn(),
  exportUrl: vi.fn((id: string) => `/history/${id}/export`),
}));

vi.mock('../api/historyApi', () => historyApi);

const createdAt = '2026-08-06T12:00:00Z';

function summary(type: SessionSummary['type'], input_summary: SessionSummary['input_summary']): SessionSummary {
  return {
    session_id: `${type}-1`,
    type,
    created_at: createdAt,
    updated_at: createdAt,
    status: 'complete',
    input_summary,
    event_count: 3,
  };
}

async function openOnlySession(detail: HistoryDetails, session: SessionSummary) {
  historyApi.getSessions.mockResolvedValueOnce([session]);
  historyApi.getSession.mockResolvedValueOnce(detail);
  render(createElement(HistoryPage));
  await screen.findByText('View Details');
  await userEvent.click(screen.getByRole('button', { name: 'View Details' }));
}

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

describe('HistoryPage details', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders archived term search best match and alternatives without debug sections', async () => {
    await openOnlySession(
      {
        id: 'term_search-1',
        type: 'term_search',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { source_term: 'sbp', source_label: 'Systolic BP' },
        configuration: { retrieval_method: 'local', provider: 'ollama', model: 'llama3.2' },
        result: {
          best_match: {
            source_term: 'sbp',
            source_label: 'Systolic BP',
            source_type: 'numeric',
            target_code: '8480-6',
            target_term: 'Systolic blood pressure',
            ontology: 'LOINC',
            confidence: 0.91,
            logic_type: 'rag',
            notes: 'Strong match.',
            retrieval_mode: 'local',
            configured_provider: 'ollama',
            configured_model: 'llama3.2',
            alternatives: [
              {
                code: '8462-4',
                term: 'Diastolic blood pressure',
                ontology: 'LOINC',
                confidence: 0.62,
                explanation: 'Related blood pressure measurement.',
              },
            ],
          },
          alternatives: [
            {
              code: '8462-4',
              term: 'Diastolic blood pressure',
              ontology: 'LOINC',
              confidence: 0.62,
              explanation: 'Related blood pressure measurement.',
            },
          ],
        },
      },
      summary('term_search', { term: 'sbp', target_ontologies: ['LOINC'] }),
    );

    expect(await screen.findByText('Best match')).toBeInTheDocument();
    expect(screen.getAllByText(/8480-6/).length).toBeGreaterThan(0);
    expect(screen.getByText('Other suggestions')).toBeInTheDocument();
    expect(screen.getByText('8462-4')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Copy code/ })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Download CSV' }).length).toBeGreaterThan(0);
    expect(screen.queryByText('Event Timeline')).not.toBeInTheDocument();
    expect(screen.queryByText('Result Snapshot')).not.toBeInTheDocument();
    expect(screen.queryByText(/Click any row/)).not.toBeInTheDocument();
  });

  it('renders archived batch rows and decisions read-only', async () => {
    await openOnlySession(
      {
        id: 'batch_map-1',
        type: 'batch_map',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { filename: 'dictionary.csv', row_count: 2 },
        configuration: { target_ontologies: ['HPO'], auto_accept_threshold: 0.85 },
        result: {
          total: 2,
          completed: 2,
          status: 'done',
          summary: {
            total_rows: 2,
            completed_count: 2,
            accepted_count: 1,
            pending_count: 0,
            rejected_count: 1,
            unmapped_count: 1,
          },
          rows: [
            {
              row_index: 0,
              field_name: 'sbp',
              label: 'Systolic BP',
              suggested_code: 'LOINC:8480-6',
              suggested_term: 'Systolic blood pressure',
              ontology: 'LOINC',
              confidence: 0.92,
              logic_type: 'rag',
              decision: 'accepted',
              alternatives: [
                {
                  code: 'LOINC:8462-4',
                  term: 'Diastolic blood pressure',
                  ontology: 'LOINC',
                  confidence: 0.5,
                },
              ],
            },
            {
              row_index: 1,
              field_name: 'unknown',
              suggested_code: 'UNMAPPED',
              suggested_term: 'Unmapped',
              ontology: '',
              confidence: 0,
              logic_type: 'none',
              decision: 'rejected',
              alternatives: [],
            },
          ],
        },
      },
      summary('batch_map', { filename: 'dictionary.csv', row_count: 2 }),
    );

    expect(await screen.findByText('Archived Mappings')).toBeInTheDocument();
    expect(screen.getByText('sbp')).toBeInTheDocument();
    expect(screen.getAllByText('Accepted').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Rejected').length).toBeGreaterThan(0);
    expect(screen.queryByText(/Accept all High/)).not.toBeInTheDocument();
    expect(screen.queryByText('Reject all Unmapped')).not.toBeInTheDocument();
    expect(screen.queryByText('Reset all')).not.toBeInTheDocument();

    await userEvent.click(screen.getByTitle('Show alternatives'));
    expect(screen.getByText('Diastolic blood pressure')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Use LOINC/ })).not.toBeInTheDocument();
  });

  it('renders archived validation results cleanly', async () => {
    await openOnlySession(
      {
        id: 'validation-1',
        type: 'validation',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { codes: ['HP:0000822', 'HP:9999999'] },
        result: {
          summary: {
            total_count: 2,
            valid_count: 1,
            deprecated_count: 0,
            not_found_count: 1,
            error_count: 0,
          },
          results: [
            { code: 'HP:0000822', status: 'valid', term: 'Hypertension', ontology: 'HPO' },
            { code: 'HP:9999999', status: 'not-found' },
          ],
        },
      },
      summary('validation', { codes: ['HP:0000822', 'HP:9999999'] }),
    );

    expect(await screen.findByText('Validation Results')).toBeInTheDocument();
    expect(screen.getByText('HP:0000822')).toBeInTheDocument();
    expect(screen.getByText('Hypertension')).toBeInTheDocument();
    expect(screen.getByText('Not found')).toBeInTheDocument();
    expect(screen.queryByText('Result Snapshot')).not.toBeInTheDocument();
  });

  it('shows legacy missing-details message without rendering null', async () => {
    await openOnlySession(
      {
        id: 'term_search-1',
        type: 'term_search',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { source_term: 'legacy' },
        result: { best_match: null, alternatives: [] },
        legacy_message: 'Detailed results were not stored for this earlier session.',
      },
      summary('term_search', { term: 'legacy' }),
    );

    expect(await screen.findByText('Detailed results were not stored for this earlier session.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('null')).not.toBeInTheDocument());
  });

  it('renders archived term search ontology links from the enriched history response', async () => {
    await openOnlySession(
      {
        id: 'term_search-1',
        type: 'term_search',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { source_term: 'sbp', source_label: 'Systolic BP' },
        configuration: { retrieval_method: 'local', provider: 'ollama', model: 'llama3.2' },
        result: {
          best_match: {
            source_term: 'sbp',
            source_label: 'Systolic BP',
            source_type: 'numeric',
            target_code: 'LOINC:8480-6',
            target_term: 'Systolic blood pressure',
            ontology: 'LOINC',
            confidence: 0.91,
            logic_type: 'rag',
            notes: 'Strong match.',
            retrieval_mode: 'local',
            configured_provider: 'ollama',
            configured_model: 'llama3.2',
            target_url: 'https://loinc.org/8480-6',
            alternatives: [
              {
                code: 'LOINC:8462-4',
                term: 'Diastolic blood pressure',
                ontology: 'LOINC',
                confidence: 0.62,
                url: 'https://loinc.org/8462-4',
              },
            ],
          },
          alternatives: [
            {
              code: 'LOINC:8462-4',
              term: 'Diastolic blood pressure',
              ontology: 'LOINC',
              confidence: 0.62,
              url: 'https://loinc.org/8462-4',
            },
          ],
        },
      },
      summary('term_search', { term: 'sbp', target_ontologies: ['LOINC'] }),
    );

    await screen.findByText('Best match');
    expect(screen.getByRole('link', { name: 'LOINC:8480-6' })).toHaveAttribute(
      'href',
      'https://loinc.org/8480-6',
    );
    expect(screen.getByRole('link', { name: 'LOINC:8462-4' })).toHaveAttribute(
      'href',
      'https://loinc.org/8462-4',
    );
  });

  it('renders stored processing time for a new term-search history entry', async () => {
    await openOnlySession(
      {
        id: 'term_search-1',
        type: 'term_search',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { source_term: 'sbp' },
        configuration: { retrieval_method: 'local', provider: 'ollama', model: 'llama3.2' },
        result: {
          best_match: {
            source_term: 'sbp',
            target_code: 'LOINC:8480-6',
            target_term: 'Systolic blood pressure',
            ontology: 'LOINC',
            confidence: 0.91,
            logic_type: 'rag',
            retrieval_mode: 'local',
            configured_provider: 'ollama',
            configured_model: 'llama3.2',
            metadata: { model: 'llama3.2', provider: 'ollama', latency_ms: 4820 },
            alternatives: [],
          },
          alternatives: [],
        },
      },
      summary('term_search', { term: 'sbp' }),
    );

    await screen.findByText('Best match');
    expect(screen.getByText('4.82 s')).toBeInTheDocument();
  });

  it('omits the processing-time line for a pre-feature term-search history entry', async () => {
    await openOnlySession(
      {
        id: 'term_search-1',
        type: 'term_search',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { source_term: 'sbp' },
        configuration: { retrieval_method: 'local', provider: 'ollama', model: 'llama3.2' },
        result: {
          best_match: {
            source_term: 'sbp',
            target_code: 'LOINC:8480-6',
            target_term: 'Systolic blood pressure',
            ontology: 'LOINC',
            confidence: 0.91,
            logic_type: 'rag',
            retrieval_mode: 'local',
            configured_provider: 'ollama',
            configured_model: 'llama3.2',
            // No `metadata` at all — a pre-feature stored snapshot.
            alternatives: [],
          },
          alternatives: [],
        },
      },
      summary('term_search', { term: 'sbp' }),
    );

    await screen.findByText('Best match');
    expect(screen.queryByText(/processing time/i)).not.toBeInTheDocument();
  });

  it('renders stored per-row processing time in a new batch history entry', async () => {
    await openOnlySession(
      {
        id: 'batch_map-1',
        type: 'batch_map',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { filename: 'dictionary.csv', row_count: 1 },
        configuration: { target_ontologies: ['LOINC'], auto_accept_threshold: 0.85 },
        result: {
          total: 1,
          completed: 1,
          status: 'done',
          summary: {
            total_rows: 1,
            completed_count: 1,
            accepted_count: 1,
            pending_count: 0,
            rejected_count: 0,
            unmapped_count: 0,
          },
          rows: [
            {
              row_index: 0,
              field_name: 'sbp',
              suggested_code: 'LOINC:8480-6',
              suggested_term: 'Systolic blood pressure',
              ontology: 'LOINC',
              confidence: 0.92,
              logic_type: 'rag',
              decision: 'accepted',
              notes: 'Strong match.',
              alternatives: [],
              processing_time_seconds: 4.82,
            },
          ],
        },
      },
      summary('batch_map', { filename: 'dictionary.csv', row_count: 1 }),
    );

    expect(await screen.findByText('Archived Mappings')).toBeInTheDocument();
    expect(screen.getByText('4.82 s')).toBeInTheDocument();
  });

  it('renders a pre-feature batch history entry (no processing_time_seconds) without errors', async () => {
    await openOnlySession(
      {
        id: 'batch_map-1',
        type: 'batch_map',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { filename: 'dictionary.csv', row_count: 1 },
        configuration: { target_ontologies: ['LOINC'], auto_accept_threshold: 0.85 },
        result: {
          total: 1,
          completed: 1,
          status: 'done',
          summary: {
            total_rows: 1,
            completed_count: 1,
            accepted_count: 1,
            pending_count: 0,
            rejected_count: 0,
            unmapped_count: 0,
          },
          rows: [
            {
              row_index: 0,
              field_name: 'sbp',
              suggested_code: 'LOINC:8480-6',
              suggested_term: 'Systolic blood pressure',
              ontology: 'LOINC',
              confidence: 0.92,
              logic_type: 'rag',
              decision: 'accepted',
              notes: 'Strong match.',
              alternatives: [],
              // No processing_time_seconds — pre-feature stored snapshot.
            },
          ],
        },
      },
      summary('batch_map', { filename: 'dictionary.csv', row_count: 1 }),
    );

    expect(await screen.findByText('Archived Mappings')).toBeInTheDocument();
    expect(screen.getByText('sbp')).toBeInTheDocument();
    expect(screen.queryByText(/processing time/i)).not.toBeInTheDocument();
  });

  it('renders archived batch ontology links from the enriched history response', async () => {
    await openOnlySession(
      {
        id: 'batch_map-1',
        type: 'batch_map',
        status: 'complete',
        created_at: createdAt,
        completed_at: createdAt,
        input: { filename: 'dictionary.csv', row_count: 1 },
        configuration: { target_ontologies: ['LOINC'], auto_accept_threshold: 0.85 },
        result: {
          total: 1,
          completed: 1,
          status: 'done',
          summary: {
            total_rows: 1,
            completed_count: 1,
            accepted_count: 1,
            pending_count: 0,
            rejected_count: 0,
            unmapped_count: 0,
          },
          rows: [
            {
              row_index: 0,
              field_name: 'sbp',
              label: 'Systolic BP',
              suggested_code: 'LOINC:8480-6',
              suggested_term: 'Systolic blood pressure',
              ontology: 'LOINC',
              confidence: 0.92,
              logic_type: 'rag',
              decision: 'accepted',
              suggested_url: 'https://loinc.org/8480-6',
              alternatives: [
                {
                  code: 'LOINC:8462-4',
                  term: 'Diastolic blood pressure',
                  ontology: 'LOINC',
                  confidence: 0.5,
                  url: 'https://loinc.org/8462-4',
                },
              ],
            },
          ],
        },
      },
      summary('batch_map', { filename: 'dictionary.csv', row_count: 1 }),
    );

    expect(await screen.findByText('Archived Mappings')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'LOINC:8480-6' })).toHaveAttribute(
      'href',
      'https://loinc.org/8480-6',
    );

    await userEvent.click(screen.getByTitle('Show alternatives'));
    expect(screen.getByRole('link', { name: 'LOINC:8462-4' })).toHaveAttribute(
      'href',
      'https://loinc.org/8462-4',
    );
  });
});
