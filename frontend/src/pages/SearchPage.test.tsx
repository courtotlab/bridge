import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SearchPage from './SearchPage';
import type { AppConfig, RetrievalMode } from '../types/config';
import type { SingleMappingResponse } from '../types/mapping';

const mocks = vi.hoisted(() => ({
  getConfig: vi.fn(),
  mapSingleTerm: vi.fn(),
  startSession: vi.fn(),
  emitEvent: vi.fn(),
  completeSession: vi.fn(),
}));

vi.mock('../api/configApi', () => ({
  getConfig: mocks.getConfig,
}));

vi.mock('../api/mappingApi', () => ({
  mapSingleTerm: mocks.mapSingleTerm,
}));

vi.mock('../context/SessionContext', () => ({
  useSession: () => ({
    startSession: mocks.startSession,
    emitEvent: mocks.emitEvent,
    completeSession: mocks.completeSession,
  }),
}));

const SINGLE_TERM_RESULT_STORAGE_KEY = 'bridge:single-term-result';

const baseConfig: AppConfig = {
  use_ner: true,
  retrieval_mode: 'public',
  bioportal_api_key: null,
  loinc_username: null,
  loinc_password: null,
  sapbert_server_url: 'http://localhost:8765',
  rag_auto_accept_threshold: 0.85,
  provider: 'ollama',
  model: 'llama3.2',
  base_url: 'http://localhost:11434',
  api_key: null,
};

function mappingResponse(
  overrides: Partial<SingleMappingResponse> = {},
): SingleMappingResponse {
  return {
    source_term: 'sbp',
    source_label: 'Systolic blood pressure',
    source_type: 'numeric',
    target_code: 'LOINC:8480-6',
    target_term: 'Systolic blood pressure',
    ontology: 'LOINC',
    confidence: 0.91,
    logic_type: 'rag',
    notes: 'Mapped.',
    alternatives: [],
    configured_provider: 'ollama',
    configured_model: 'llama3.2',
    retrieval_mode: 'public',
    ...overrides,
  };
}

function setup() {
  return {
    user: userEvent.setup(),
    ...render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    ),
  };
}

async function submitSearch(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/field name/i), 'sbp');
  await user.click(screen.getByRole('button', { name: /search/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  mocks.getConfig.mockResolvedValue(baseConfig);
  mocks.startSession.mockResolvedValue('session-1');
  mocks.emitEvent.mockResolvedValue(undefined);
  mocks.completeSession.mockResolvedValue(undefined);
});

describe('SearchPage retrieval method display', () => {
  it.each([
    ['public', 'Public ontology databases (grounded)'],
    ['local', 'Local retrieval (grounded)'],
    ['disabled', 'Disabled (ungrounded)'],
  ] satisfies Array<[RetrievalMode, string]>)(
    'renders %s as %s',
    async (mode, label) => {
      mocks.mapSingleTerm.mockResolvedValue(mappingResponse({ retrieval_mode: mode }));
      const { user } = setup();

      await submitSearch(user);

      expect(await screen.findByText(label)).toBeInTheDocument();
      expect(screen.getByText(/retrieval method:/i)).toBeInTheDocument();
      const trigger = screen.getByRole('button', { name: 'About retrieval method' });
      expect(trigger).toHaveAttribute('aria-describedby');
      expect(trigger).not.toHaveAttribute('title');
      const tooltipId = trigger.getAttribute('aria-describedby');
      expect(document.getElementById(tooltipId ?? '')).toHaveTextContent(
        /grounded mappings use candidates/i,
      );
    },
  );

  it('renders Not recorded for legacy results with no retrieval mode', async () => {
    const legacy = mappingResponse();
    delete legacy.retrieval_mode;
    mocks.mapSingleTerm.mockResolvedValue(legacy);
    const { user } = setup();

    await submitSearch(user);

    expect(await screen.findByText('Not recorded')).toBeInTheDocument();
  });

  it('does not change a completed result when settings later change', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({ retrieval_mode: 'local' }));
    const first = setup();

    await submitSearch(first.user);
    expect(await screen.findByText('Local retrieval (grounded)')).toBeInTheDocument();
    first.unmount();

    mocks.getConfig.mockResolvedValue({ ...baseConfig, retrieval_mode: 'disabled' });
    setup();

    expect(await screen.findByText('Local retrieval (grounded)')).toBeInTheDocument();
    expect(screen.queryByText('Disabled (ungrounded)')).not.toBeInTheDocument();
    expect(mocks.mapSingleTerm).toHaveBeenCalledTimes(1);
  });

  it('preserves retrieval_mode in the session snapshot and browser session state', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({ retrieval_mode: 'disabled' }));
    const { user } = setup();

    await submitSearch(user);

    await waitFor(() => expect(mocks.completeSession).toHaveBeenCalled());
    const snapshot = mocks.completeSession.mock.calls[0][2] as SingleMappingResponse;
    expect(snapshot.retrieval_mode).toBe('disabled');

    const stored = JSON.parse(
      window.sessionStorage.getItem(SINGLE_TERM_RESULT_STORAGE_KEY) ?? '{}',
    ) as { bestMatch?: SingleMappingResponse };
    expect(stored.bestMatch?.retrieval_mode).toBe('disabled');
  });

  it('sends EFO through the existing single-term target ontology payload', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({
      target_code: 'EFO:0004340',
      target_term: 'body mass index',
      ontology: 'EFO',
    }));
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));
    await submitSearch(user);

    await waitFor(() => expect(mocks.mapSingleTerm).toHaveBeenCalledWith(
      expect.objectContaining({
        target_ontologies: ['EFO'],
      }),
    ));
    expect(await screen.findByText('EFO:0004340 · body mass index')).toBeInTheDocument();
    expect(screen.getByText('Ontology: Experimental Factor Ontology')).toBeInTheDocument();
  });

  it('renders imported EFO mappings with the returned native ontology unchanged', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({
      target_code: 'MONDO:0004975',
      target_term: 'Alzheimer disease',
      ontology: 'MONDO',
      confidence: 0.99,
      alternatives: [
        {
          code: 'EFO:0000249',
          term: 'Alzheimer disease',
          ontology: 'EFO',
          confidence: 0.86,
          source: 'rag',
        },
      ],
    }));
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));
    await submitSearch(user);

    expect(await screen.findByText('MONDO:0004975 · Alzheimer disease')).toBeInTheDocument();
    expect(screen.getByText('Ontology: Monarch Disease Ontology')).toBeInTheDocument();
    expect(screen.getByText('EFO:0000249')).toBeInTheDocument();

    await waitFor(() => expect(mocks.completeSession).toHaveBeenCalled());
    const snapshot = mocks.completeSession.mock.calls[0][2] as SingleMappingResponse;
    expect(snapshot.ontology).toBe('MONDO');
    expect(snapshot.target_code).toBe('MONDO:0004975');
    expect(snapshot.alternatives[0]).toEqual(expect.objectContaining({
      code: 'EFO:0000249',
      ontology: 'EFO',
    }));
  });

  it('uses accessible non-native tooltip triggers for result metadata', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({ retrieval_mode: 'public' }));
    const { user } = setup();

    await submitSearch(user);

    const expectedTooltips = [
      ['About retrieval method', /grounded mappings use candidates/i],
      ['About AI provider', /AI provider configured in Bridge settings/i],
      ['About model', /model configured in Bridge settings/i],
    ] as const;

    for (const [name, text] of expectedTooltips) {
      const trigger = await screen.findByRole('button', { name });
      const tooltipId = trigger.getAttribute('aria-describedby');
      expect(trigger).toHaveAttribute('type', 'button');
      expect(trigger).not.toHaveAttribute('title');
      expect(document.getElementById(tooltipId ?? '')).toHaveAttribute('role', 'tooltip');
      expect(document.getElementById(tooltipId ?? '')).toHaveTextContent(text);
    }
  });
});
