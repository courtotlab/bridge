import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cancelBatch,
  startBatch,
  uploadPreview,
} from '../api/batchApi';
import type { BatchJobStatus, BatchRowResult } from '../types/mapping';
import { BATCH_FILE_ACCEPT } from '../utils/batchFiles';
import { promoteBatchAlternative } from '../utils/batchPromotion';
import { interruptActiveBatch } from '../utils/activeBatchInterruption';
import BatchPage from './BatchPage';

const mocks = vi.hoisted(() => ({
  uploadPreview: vi.fn(),
  startBatch: vi.fn(),
  getBatchStatus: vi.fn(),
  cancelBatch: vi.fn(),
  cancelBatchKeepalive: vi.fn(),
  setDecision: vi.fn(),
  promoteAlternative: vi.fn(),
  startSession: vi.fn(),
  emitEvent: vi.fn(),
  completeSession: vi.fn(),
}));

vi.mock('../api/batchApi', () => ({
  uploadPreview: mocks.uploadPreview,
  startBatch: mocks.startBatch,
  getBatchStatus: mocks.getBatchStatus,
  cancelBatch: mocks.cancelBatch,
  cancelBatchKeepalive: mocks.cancelBatchKeepalive,
  setDecision: mocks.setDecision,
  promoteAlternative: mocks.promoteAlternative,
  exportUrl: (jobId: string) => `/api/batch/export/${jobId}`,
}));

vi.mock('../context/SessionContext', () => ({
  useSession: () => ({
    startSession: mocks.startSession,
    emitEvent: mocks.emitEvent,
    completeSession: mocks.completeSession,
  }),
}));

const COMPLETE_COLUMNS = [
  'source_variable',
  'source_label',
  'source_description',
  'source_data_type',
  'target_ontology',
];

function preview(filename: string, columns = ['field_name', 'label', 'clinical_area', 'target_ontology']) {
  return {
    filename,
    row_count: 1,
    columns,
    preview: [
      Object.fromEntries(columns.map((column) => [column, `${column}_value`])),
    ],
  };
}

function fileNamed(name: string, type = ''): File {
  return new File(['field_name\tlabel\nsys_bp\tSystolic blood pressure\n'], name, {
    type,
  });
}

function mappedRow(overrides: Partial<BatchRowResult> = {}): BatchRowResult {
  return {
    row_index: 0,
    field_name: 'sbp',
    label: 'Systolic blood pressure',
    suggested_code: 'LOINC:8480-6',
    suggested_term: 'Systolic blood pressure',
    ontology: 'LOINC',
    confidence: 0.91,
    logic_type: 'rag',
    decision: 'accepted',
    alternatives: [],
    notes: 'Mapped. Selected because the field label matches systolic blood pressure.',
    configured_provider: 'ollama',
    configured_model: 'llama3.2',
    retrieval_mode: 'public',
    ...overrides,
  };
}

function batchStatus(results: BatchRowResult[]): BatchJobStatus {
  return {
    job_id: 'job-1',
    total: results.length,
    completed: results.length,
    results,
    status: 'done',
    error: null,
  };
}

function setup() {
  const view = render(<BatchPage />);
  const input = view.container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) {
    throw new Error('Batch file input was not rendered');
  }
  return {
    user: userEvent.setup(),
    input,
    ...view,
  };
}

async function renderCompletedBatchReview(status: BatchJobStatus) {
  mocks.getBatchStatus.mockResolvedValue(status);
  const view = setup();
  const file = fileNamed('data.csv', 'text/csv');

  await view.user.upload(view.input, file);
  await waitFor(() => {
    expect(screen.getAllByText('data.csv').length).toBeGreaterThan(0);
  });
  await view.user.click(screen.getByRole('button', { name: /start mapping/i }));

  await waitFor(() => expect(mocks.getBatchStatus).toHaveBeenCalled(), {
    timeout: 3000,
  });
  expect(await screen.findByText('Review and Approve Mappings', {}, {
    timeout: 3000,
  })).toBeInTheDocument();

  return view;
}

function getColumnSelectors(): HTMLSelectElement[] {
  return screen.getAllByRole('combobox') as HTMLSelectElement[];
}

function getFileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) {
    throw new Error('Batch file input was not rendered');
  }
  return input;
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.uploadPreview.mockImplementation(async (file: File) => preview(file.name));
  mocks.startBatch.mockResolvedValue({ job_id: 'job-1', total: 1 });
  mocks.cancelBatch.mockResolvedValue({ interrupted: true });
  mocks.setDecision.mockResolvedValue(undefined);
  mocks.promoteAlternative.mockImplementation(async (_jobId, _rowIndex, alt) => mappedRow({
    suggested_code: alt.code,
    suggested_term: alt.code === 'HP:0000822' ? 'Hypertension' : 'Promoted term',
    ontology: alt.ontology,
    confidence: 0.78,
    logic_type: 'llm',
    decision: 'pending',
    notes: 'Alternative-specific hypertension reasoning.',
    alternatives: [
      {
        code: 'LOINC:8480-6',
        term: 'Systolic blood pressure',
        ontology: 'LOINC',
        confidence: 0.91,
        source: 'rag',
        explanation: 'Selected because the field label matches systolic blood pressure.',
      },
    ],
  }));
  mocks.startSession.mockResolvedValue('session-1');
  mocks.emitEvent.mockResolvedValue(undefined);
  mocks.completeSession.mockResolvedValue(undefined);
});

afterEach(async () => {
  await interruptActiveBatch({ reason: 'manual' });
});

describe('BatchPage file upload formats', () => {
  it('accepts CSV, TSV, and XLSX in the file input', () => {
    const { input } = setup();

    expect(input).toHaveAttribute('accept', BATCH_FILE_ACCEPT);
  });

  it('mentions CSV, TSV, and XLSX in upload instructions', () => {
    setup();

    expect(screen.getByText('CSV, TSV, or XLSX')).toBeInTheDocument();
  });

  it.each([
    ['lowercase .tsv', fileNamed('data.tsv', 'text/tab-separated-values')],
    ['uppercase .TSV', fileNamed('DATA.TSV', 'text/tab-separated-values')],
    ['TSV text/tab-separated-values MIME', fileNamed('data.tsv', 'text/tab-separated-values')],
    ['TSV text/plain MIME', fileNamed('data.tsv', 'text/plain')],
    ['TSV generic MIME', fileNamed('data.tsv', 'application/octet-stream')],
    ['TSV empty MIME', fileNamed('data.tsv')],
  ])('accepts %s', async (_label, file) => {
    const { user, input } = setup();

    await user.upload(input, file);

    await waitFor(() => expect(uploadPreview).toHaveBeenCalledWith(file));
    await waitFor(() => {
      expect(screen.getAllByText(file.name).length).toBeGreaterThan(0);
    });
  });

  it('rejects an arbitrary .txt file selected in the picker', async () => {
    const { input } = setup();

    fireEvent.change(input, {
      target: {
        files: [fileNamed('data.txt', 'text/plain')],
      },
    });

    expect(uploadPreview).not.toHaveBeenCalled();
    expect(screen.getByText('Unsupported file type. Upload a CSV, TSV, or XLSX file.')).toBeInTheDocument();
  });

  it('rejects an arbitrary .txt file dropped onto the upload zone', () => {
    setup();

    fireEvent.drop(screen.getByRole('button', { name: 'Upload file' }), {
      dataTransfer: {
        files: [fileNamed('data.txt', 'text/plain')],
      },
    });

    expect(uploadPreview).not.toHaveBeenCalled();
    expect(screen.getByText('Unsupported file type. Upload a CSV, TSV, or XLSX file.')).toBeInTheDocument();
  });

  it('keeps batch interruption available after starting from a TSV upload', async () => {
    const { user, input } = setup();
    const tsvFile = fileNamed('data.tsv', 'text/plain');

    await user.upload(input, tsvFile);
    await waitFor(() => {
      expect(screen.getAllByText('data.tsv').length).toBeGreaterThan(0);
    });
    await user.click(screen.getByRole('button', { name: /start mapping/i }));
    await waitFor(() => expect(startBatch).toHaveBeenCalledWith(
      expect.objectContaining({ file: tsvFile }),
    ));

    await interruptActiveBatch({ reason: 'manual' });

    expect(cancelBatch).toHaveBeenCalledWith('job-1');
  });

  it('sends the selected per-row target ontology column and mutes global selections', async () => {
    const { user, input } = setup();
    const file = fileNamed('data.csv', 'text/csv');

    await user.upload(input, file);
    await waitFor(() => {
      expect(screen.getAllByText('data.csv').length).toBeGreaterThan(0);
    });

    const selectors = screen.getAllByRole('combobox');
    const targetOntologySelector = selectors[selectors.length - 1];
    await user.selectOptions(targetOntologySelector, '');
    await user.click(screen.getByRole('checkbox', { name: 'LOINC' }));
    expect(screen.getByRole('checkbox', { name: 'LOINC' })).toBeChecked();

    await user.selectOptions(targetOntologySelector, 'target_ontology');
    expect(screen.getByRole('group', { name: /target ontologies/i })).toBeDisabled();
    expect(screen.getByText(/Per-row target ontologies are active/i)).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'LOINC' })).toBeChecked();

    await user.click(screen.getByRole('button', { name: /start mapping/i }));

    await waitFor(() => expect(startBatch).toHaveBeenCalledWith(
      expect.objectContaining({
        file,
        targetOntologyColumn: 'target_ontology',
        targetOntologies: ['LOINC'],
      }),
    ));
  });
});

describe('BatchPage column auto-detection', () => {
  it.each([
    ['CSV', fileNamed('data.csv', 'text/csv')],
    ['TSV', fileNamed('data.tsv', 'text/tab-separated-values')],
    [
      'XLSX',
      fileNamed(
        'data.xlsx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      ),
    ],
  ])('auto-selects all expected column roles for %s uploads', async (_label, file) => {
    mocks.uploadPreview.mockResolvedValueOnce(preview(file.name, COMPLETE_COLUMNS));
    const { user, input } = setup();

    await user.upload(input, file);

    await waitFor(() => {
      const selectors = getColumnSelectors();
      expect(selectors[0]).toHaveValue('source_variable');
      expect(selectors[1]).toHaveValue('source_label');
      expect(selectors[2]).toHaveValue('source_description');
      expect(selectors[3]).toHaveValue('source_data_type');
      expect(selectors[4]).toHaveValue('target_ontology');
    });
  });

  it('preserves original uploaded header spelling in the start request', async () => {
    const columns = [
      'source_variable',
      'source-label',
      'Source Description',
      'DATA TYPE',
      'target_ontology',
    ];
    const file = fileNamed('data.csv', 'text/csv');
    mocks.uploadPreview.mockResolvedValueOnce(preview(file.name, columns));
    const { user, input } = setup();

    await user.upload(input, file);
    await waitFor(() => {
      expect(getColumnSelectors()[1]).toHaveValue('source-label');
      expect(getColumnSelectors()[2]).toHaveValue('Source Description');
      expect(getColumnSelectors()[3]).toHaveValue('DATA TYPE');
    });
    await user.click(screen.getByRole('button', { name: /start mapping/i }));

    await waitFor(() => expect(startBatch).toHaveBeenCalledWith(
      expect.objectContaining({
        columnMap: expect.objectContaining({
          field_name: 'source_variable',
          label: 'source-label',
          description: 'Source Description',
          data_type: 'DATA TYPE',
          target_ontology: 'target_ontology',
        }),
      }),
    ));
  });

  it('does not overwrite a user-selected column during rerenders', async () => {
    mocks.uploadPreview.mockResolvedValueOnce(preview('data.csv', COMPLETE_COLUMNS));
    const { user, input } = setup();

    await user.upload(input, fileNamed('data.csv', 'text/csv'));
    await waitFor(() => expect(getColumnSelectors()[1]).toHaveValue('source_label'));
    await user.selectOptions(getColumnSelectors()[1], 'source_description');
    await user.click(screen.getByRole('checkbox', { name: 'LOINC' }));

    expect(getColumnSelectors()[1]).toHaveValue('source_description');
  });

  it('runs detection again for a different uploaded file', async () => {
    mocks.uploadPreview
      .mockResolvedValueOnce(preview('first.csv', COMPLETE_COLUMNS))
      .mockResolvedValueOnce(preview('second.csv', [
        'variable_name',
        'variable_label',
        'definition',
        'datatype',
        'ontology',
      ]));
    const { user, input, container } = setup();

    await user.upload(input, fileNamed('first.csv', 'text/csv'));
    await waitFor(() => expect(getColumnSelectors()[1]).toHaveValue('source_label'));
    await user.selectOptions(getColumnSelectors()[1], '');
    expect(getColumnSelectors()[1]).toHaveValue('');
    await user.click(screen.getByTitle('Remove file'));

    await user.upload(getFileInput(container), fileNamed('second.csv', 'text/csv'));
    await waitFor(() => {
      const selectors = getColumnSelectors();
      expect(selectors[0]).toHaveValue('variable_name');
      expect(selectors[1]).toHaveValue('variable_label');
      expect(selectors[2]).toHaveValue('definition');
      expect(selectors[3]).toHaveValue('datatype');
      expect(selectors[4]).toHaveValue('ontology');
    });
  });

  it('removing the file clears detected selections from the form', async () => {
    mocks.uploadPreview.mockResolvedValueOnce(preview('data.csv', COMPLETE_COLUMNS));
    const { user, input } = setup();

    await user.upload(input, fileNamed('data.csv', 'text/csv'));
    await waitFor(() => expect(getColumnSelectors()[1]).toHaveValue('source_label'));
    await user.click(screen.getByTitle('Remove file'));

    expect(screen.queryByText('Tell us which columns contain what')).not.toBeInTheDocument();
    expect(screen.queryAllByRole('combobox')).toHaveLength(0);
  });
});

describe('BatchPage mapping details tooltips', () => {
  it('shows primary suggested mapping explanation and metadata in the shared tooltip', async () => {
    await renderCompletedBatchReview(batchStatus([mappedRow()]));

    const trigger = await screen.findByRole('button', {
      name: 'View mapping details for LOINC:8480-6',
    });
    const tooltip = document.getElementById(trigger.getAttribute('aria-describedby') ?? '');

    expect(tooltip).toHaveTextContent('Why selected');
    expect(tooltip).toHaveTextContent('Selected because the field label matches systolic blood pressure.');
    expect(tooltip).toHaveTextContent('Retrieval method');
    expect(tooltip).toHaveTextContent('Public ontology databases (grounded)');
    expect(tooltip).not.toHaveTextContent('Retrieval source');
    expect(tooltip).toHaveTextContent('AI provider');
    expect(tooltip).toHaveTextContent('ollama');
    expect(tooltip).toHaveTextContent('Model');
    expect(tooltip).toHaveTextContent('llama3.2');
  });

  it('reveals mapping details on keyboard focus', async () => {
    await renderCompletedBatchReview(batchStatus([mappedRow()]));

    const trigger = await screen.findByRole('button', {
      name: 'View mapping details for LOINC:8480-6',
    });
    const tooltip = document.getElementById(trigger.getAttribute('aria-describedby') ?? '');

    fireEvent.focus(trigger);

    expect(trigger).toHaveAttribute('type', 'button');
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(tooltip).toHaveClass('info-tooltip-bubble--visible');
  });

  it('shows expanded alternative mapping details from the alternative itself', async () => {
    const row = mappedRow({
      notes: 'Mapped. Primary explanation only.',
      alternatives: [
        {
          code: 'HP:0000822',
          term: 'Hypertension',
          ontology: 'HPO',
          confidence: 0.78,
          source: 'llm',
          explanation: 'Alternative-specific hypertension reasoning.',
        },
      ],
    });
    const { user } = await renderCompletedBatchReview(batchStatus([row]));

    await user.click(screen.getByTitle('Show alternatives'));

    const trigger = await screen.findByRole('button', {
      name: 'View mapping details for HP:0000822',
    });
    const tooltip = document.getElementById(trigger.getAttribute('aria-describedby') ?? '');

    expect(tooltip).toHaveTextContent('Alternative-specific hypertension reasoning.');
    expect(tooltip).not.toHaveTextContent('Primary explanation only.');
    expect(tooltip).not.toHaveTextContent('Retrieval source');
  });

  it('omits missing optional metadata sections without placeholder strings', async () => {
    await renderCompletedBatchReview(batchStatus([
      mappedRow({
        notes: undefined,
        configured_provider: undefined,
        configured_model: undefined,
        retrieval_mode: undefined,
      }),
    ]));

    const trigger = screen.queryByRole('button', {
      name: 'View mapping details for LOINC:8480-6',
    });

    expect(trigger).not.toBeInTheDocument();
  });

  it('omits missing optional metadata sections without placeholder strings when some metadata remains', async () => {
    await renderCompletedBatchReview(batchStatus([
      mappedRow({
        notes: undefined,
        configured_provider: undefined,
        configured_model: undefined,
      }),
    ]));

    const trigger = await screen.findByRole('button', {
      name: 'View mapping details for LOINC:8480-6',
    });
    const tooltip = document.getElementById(trigger.getAttribute('aria-describedby') ?? '');

    expect(tooltip).toHaveTextContent('Retrieval method');
    expect(tooltip).not.toHaveTextContent('Why selected');
    expect(tooltip).not.toHaveTextContent('Model');
    expect(tooltip).not.toHaveTextContent('Retrieval source');
    expect(tooltip).not.toHaveTextContent('undefined');
    expect(tooltip).not.toHaveTextContent('null');
    expect(tooltip).not.toHaveTextContent('[object Object]');
  });

  it('does not show mapping details for unmapped results or alternatives without their own details', async () => {
    const row = mappedRow({
      suggested_code: 'UNMAPPED',
      suggested_term: 'UNMAPPED',
      ontology: '',
      confidence: 0,
      decision: 'rejected',
      alternatives: [
        {
          code: 'HP:0000001',
          term: 'All',
          ontology: 'HPO',
          confidence: 0.2,
        },
      ],
    });
    const { user } = await renderCompletedBatchReview(batchStatus([row]));

    expect(screen.queryByRole('button', {
      name: 'View mapping details for UNMAPPED',
    })).not.toBeInTheDocument();

    await user.click(screen.getByTitle('Show alternatives'));

    expect(screen.queryByRole('button', {
      name: 'View mapping details for HP:0000001',
    })).not.toBeInTheDocument();
  });
});

describe('BatchPage alternative promotion', () => {
  it('promotes an alternative into the primary suggested mapping and resets an accepted row to pending', async () => {
    const row = mappedRow({
      alternatives: [
        {
          code: 'HP:0000822',
          term: 'Hypertension',
          ontology: 'HPO',
          confidence: 0.78,
          source: 'llm',
          explanation: 'Alternative-specific hypertension reasoning.',
        },
        {
          code: 'HP:0002615',
          term: 'Hypotension',
          ontology: 'HPO',
          confidence: 0.51,
        },
      ],
    });
    const { user } = await renderCompletedBatchReview(batchStatus([row]));

    await user.click(screen.getByTitle('Show alternatives'));
    await user.click(screen.getByRole('button', {
      name: 'Use HP:0000822 as the suggested mapping',
    }));

    expect(await screen.findByText('HP:0000822')).toBeInTheDocument();
    expect(screen.getByText('Hypertension')).toBeInTheDocument();
    expect(screen.getByText(/78% Med/)).toBeInTheDocument();
    expect(screen.getAllByText('Pending').some((el) => (
      el.classList.contains('batch-decision-chip')
    ))).toBe(true);
    expect(screen.queryByRole('button', {
      name: 'Use HP:0000822 as the suggested mapping',
    })).not.toBeInTheDocument();
    expect(screen.getByRole('button', {
      name: 'Use LOINC:8480-6 as the suggested mapping',
    })).toBeInTheDocument();
    expect(mocks.promoteAlternative).toHaveBeenCalledWith(
      'job-1',
      0,
      expect.objectContaining({ code: 'HP:0000822', ontology: 'HPO' }),
    );
  });

  it('updates primary and demoted alternative tooltip explanations after promotion', async () => {
    const row = mappedRow({
      notes: 'Mapped. Primary explanation only.',
      alternatives: [
        {
          code: 'HP:0000822',
          term: 'Hypertension',
          ontology: 'HPO',
          confidence: 0.78,
          source: 'llm',
          explanation: 'Alternative-specific hypertension reasoning.',
        },
      ],
    });
    mocks.promoteAlternative.mockImplementationOnce(async () => (
      promoteBatchAlternative(row, row.alternatives[0])
    ));
    const { user } = await renderCompletedBatchReview(batchStatus([row]));

    await user.click(screen.getByTitle('Show alternatives'));
    await user.click(screen.getByRole('button', {
      name: 'Use HP:0000822 as the suggested mapping',
    }));

    const promotedTrigger = await screen.findByRole('button', {
      name: 'View mapping details for HP:0000822',
    });
    const promotedTooltip = document.getElementById(promotedTrigger.getAttribute('aria-describedby') ?? '');
    expect(promotedTooltip).toHaveTextContent('Alternative-specific hypertension reasoning.');
    expect(promotedTooltip).not.toHaveTextContent('Primary explanation only.');

    const demotedTrigger = await screen.findByRole('button', {
      name: 'View mapping details for LOINC:8480-6',
    });
    const demotedTooltip = document.getElementById(demotedTrigger.getAttribute('aria-describedby') ?? '');
    expect(demotedTooltip).toHaveTextContent('Primary explanation only.');
  });

  it('supports keyboard activation and updates the intended filtered row only', async () => {
    const first = mappedRow({
      row_index: 0,
      field_name: 'sbp',
      alternatives: [
        {
          code: 'HP:0000822',
          term: 'Hypertension',
          ontology: 'HPO',
          confidence: 0.78,
        },
      ],
    });
    const second = mappedRow({
      row_index: 3,
      field_name: 'dbp',
      label: 'Diastolic blood pressure',
      suggested_code: 'LOINC:8462-4',
      suggested_term: 'Diastolic blood pressure',
      notes: 'Diastolic primary explanation.',
      alternatives: [
        {
          code: 'HP:0005117',
          term: 'Abnormal diastolic blood pressure',
          ontology: 'HPO',
          confidence: 0.67,
          explanation: 'Diastolic alternative explanation.',
        },
      ],
    });
    mocks.promoteAlternative.mockImplementationOnce(async () => ({
      ...second,
      suggested_code: 'HP:0005117',
      suggested_term: 'Abnormal diastolic blood pressure',
      ontology: 'HPO',
      confidence: 0.67,
      notes: 'Diastolic alternative explanation.',
      decision: 'pending',
      alternatives: [
        {
          code: 'LOINC:8462-4',
          term: 'Diastolic blood pressure',
          ontology: 'LOINC',
          confidence: 0.91,
          source: 'rag',
          explanation: 'Diastolic primary explanation.',
        },
      ],
    }));
    const { user } = await renderCompletedBatchReview(batchStatus([first, second]));

    await user.type(screen.getByPlaceholderText('Search fields…'), 'dbp');
    await user.click(screen.getByTitle('Show alternatives'));
    const useButton = screen.getByRole('button', {
      name: 'Use HP:0005117 as the suggested mapping',
    });
    useButton.focus();
    await user.keyboard('{Enter}');

    expect(await screen.findByText('HP:0005117')).toBeInTheDocument();
    expect(screen.queryByText('sbp')).not.toBeInTheDocument();
    expect(mocks.promoteAlternative).toHaveBeenCalledWith(
      'job-1',
      3,
      expect.objectContaining({ code: 'HP:0005117', ontology: 'HPO' }),
    );
  });

  it('updates the completed session snapshot after a persisted promotion', async () => {
    const row = mappedRow({
      alternatives: [
        {
          code: 'HP:0000822',
          term: 'Hypertension',
          ontology: 'HPO',
          confidence: 0.78,
          explanation: 'Alternative-specific hypertension reasoning.',
        },
      ],
    });
    const { user } = await renderCompletedBatchReview(batchStatus([row]));

    await user.click(screen.getByTitle('Show alternatives'));
    await user.click(screen.getByRole('button', {
      name: 'Use HP:0000822 as the suggested mapping',
    }));

    await waitFor(() => expect(mocks.completeSession).toHaveBeenLastCalledWith(
      'session-1',
      'complete',
      expect.objectContaining({
        results: expect.arrayContaining([
          expect.objectContaining({
            suggested_code: 'HP:0000822',
            decision: 'pending',
          }),
        ]),
      }),
    ));
  });

  it('bulk accept uses the promoted candidate confidence', async () => {
    const row = mappedRow({
      confidence: 0.41,
      decision: 'pending',
      alternatives: [
        {
          code: 'HP:0000822',
          term: 'Hypertension',
          ontology: 'HPO',
          confidence: 0.91,
          explanation: 'High confidence alternative.',
        },
      ],
    });
    mocks.promoteAlternative.mockImplementationOnce(async () => (
      promoteBatchAlternative(row, row.alternatives[0])
    ));
    const { user } = await renderCompletedBatchReview(batchStatus([row]));

    await user.click(screen.getByTitle('Show alternatives'));
    await user.click(screen.getByRole('button', {
      name: 'Use HP:0000822 as the suggested mapping',
    }));
    await user.click(screen.getByRole('button', { name: /accept all high/i }));

    expect(screen.getAllByText('Accepted').some((el) => (
      el.classList.contains('batch-decision-chip')
    ))).toBe(true);
    expect(mocks.setDecision).toHaveBeenCalledWith('job-1', 0, 'accepted');
  });
});
