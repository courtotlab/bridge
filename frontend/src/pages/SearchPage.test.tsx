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
  retrieval_mode: 'public',
  loinc_username: null,
  loinc_password: null,
  sapbert_server_url: 'http://localhost:8765',
  rag_auto_accept_threshold: 0.85,
  provider: 'ollama',
  model: 'llama3.2',
  base_url: 'http://localhost:11434',
  api_key: null,
  reasoning_effort: null,
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

// The code portion of the best-match "code · term" line is its own element
// (plain text, or an <a> when target_url is present) sitting next to the
// term as sibling text nodes — so the combined string is no longer a single
// element's direct text and must be read from the container instead of
// matched with screen.getByText().
function resultCodeTermText(): string | null | undefined {
  return document.querySelector('.result-code-term')?.textContent;
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
    await waitFor(() => expect(resultCodeTermText()).toBe('EFO:0004340 · body mass index'));
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

    await waitFor(() => expect(resultCodeTermText()).toBe('MONDO:0004975 · Alzheimer disease'));
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

  it('sends the entered description as source_description in the map request', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    const { user } = setup();

    await user.type(screen.getByLabelText(/field name/i), 'sbp');
    await user.type(screen.getByLabelText(/label of the field/i), 'Systolic blood pressure');
    await user.type(
      screen.getByLabelText(/description/i),
      'Baseline systolic blood pressure measured in mmHg',
    );
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => expect(mocks.mapSingleTerm).toHaveBeenCalledWith(
      expect.objectContaining({
        source_term: 'sbp',
        source_label: 'Systolic blood pressure',
        source_description: 'Baseline systolic blood pressure measured in mmHg',
      }),
    ));
  });

  it('does not send a whitespace-only description as source_description', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    const { user } = setup();

    await user.type(screen.getByLabelText(/field name/i), 'sbp');
    await user.type(screen.getByLabelText(/description/i), '   ');
    await user.click(screen.getByRole('button', { name: /search/i }));

    await waitFor(() => expect(mocks.mapSingleTerm).toHaveBeenCalledWith(
      expect.objectContaining({ source_description: undefined }),
    ));
  });

  it('hides the strict ontology toggle until EFO is selected', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    setup();

    expect(
      screen.queryByRole('checkbox', { name: /require codes from selected ontology only/i }),
    ).not.toBeInTheDocument();
  });

  it('shows the strict ontology toggle once EFO is selected', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));

    expect(
      screen.getByRole('checkbox', { name: /require codes from selected ontology only/i }),
    ).toBeInTheDocument();
  });

  it('defaults strict_target_ontology to false when the toggle is untouched', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));
    await submitSearch(user);

    await waitFor(() => expect(mocks.mapSingleTerm).toHaveBeenCalledWith(
      expect.objectContaining({ strict_target_ontology: false }),
    ));
  });

  it('sends strict_target_ontology=true once the toggle is switched on', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));
    await user.click(
      screen.getByRole('checkbox', { name: /require codes from selected ontology only/i }),
    );
    await submitSearch(user);

    await waitFor(() => expect(mocks.mapSingleTerm).toHaveBeenCalledWith(
      expect.objectContaining({ strict_target_ontology: true }),
    ));
  });

  it('does not submit a stale strict_target_ontology=true once EFO is deselected', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse());
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));
    await user.click(
      screen.getByRole('checkbox', { name: /require codes from selected ontology only/i }),
    );
    await user.click(screen.getByRole('checkbox', { name: 'EFO' }));

    expect(
      screen.queryByRole('checkbox', { name: /require codes from selected ontology only/i }),
    ).not.toBeInTheDocument();

    await submitSearch(user);

    await waitFor(() => expect(mocks.mapSingleTerm).toHaveBeenCalledWith(
      expect.objectContaining({ strict_target_ontology: false }),
    ));
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

describe('SearchPage UNMAPPED alternatives', () => {
  const unmappedAlternatives = [
    { code: 'HP:0004421', term: 'Elevated systolic blood pressure', ontology: 'HPO', confidence: 0.58, source: 'rag' },
    { code: 'HP:0500105', term: 'Decreased systolic blood pressure', ontology: 'HPO', confidence: 0.52, source: 'rag' },
    { code: 'HP:0500106', term: 'Isolated systolic hypertension', ontology: 'HPO', confidence: 0.46, source: 'rag' },
    { code: 'HP:0030972', term: 'Abnormal systemic blood pressure', ontology: 'HPO', confidence: 0.34, source: 'rag' },
    { code: 'HP:0032263', term: 'Increased blood pressure', ontology: 'HPO', confidence: 0.30, source: 'rag' },
  ];

  const MAPPER_EXPLANATION =
    'No candidate is a sufficiently correct match for the generic measurement systolic blood pressure. ' +
    'The available systolic blood pressure candidates specify an abnormal direction or a clinical condition, ' +
    'whereas the source does not indicate elevation, decrease, or hypertension.';

  function unmappedResponse(overrides: Partial<SingleMappingResponse> = {}) {
    return mappingResponse({
      target_code: 'UNMAPPED',
      target_term: 'UNMAPPED',
      ontology: '',
      confidence: 0.0,
      logic_type: 'rag',
      notes: undefined,
      alternatives: [],
      ...overrides,
    });
  }

  it('shows a no-confident-match card with the requested ontology, mapper explanation, and Other suggestions', async () => {
    mocks.mapSingleTerm.mockResolvedValue(
      unmappedResponse({ notes: MAPPER_EXPLANATION, alternatives: unmappedAlternatives }),
    );
    const { user } = setup();

    await user.click(screen.getByRole('checkbox', { name: 'HPO' }));
    await submitSearch(user);

    // No-confident-match card, not a fake "Best match / UNMAPPED / 0%" card.
    expect(await screen.findByText('No confident match')).toBeInTheDocument();
    expect(screen.getByText('UNMAPPED')).toBeInTheDocument();
    expect(screen.queryByText('Best match')).not.toBeInTheDocument();
    expect(screen.getByText('No suitable Human Phenotype Ontology mapping was found')).toBeInTheDocument();

    // Requested-ontology metadata, not "Ontology: UNKNOWN".
    expect(screen.getByText('Ontology: Human Phenotype Ontology')).toBeInTheDocument();
    expect(screen.queryByText(/ontology: unknown/i)).not.toBeInTheDocument();

    // The mapper's own reasoning, not generic UI copy.
    expect(screen.getByText(new RegExp(MAPPER_EXPLANATION.slice(0, 40)))).toBeInTheDocument();

    // Alternatives still render and promote normally.
    expect(screen.getByText('Other suggestions')).toBeInTheDocument();
    for (const alt of unmappedAlternatives) {
      expect(screen.getByText(alt.code)).toBeInTheDocument();
    }
  });

  it('shows the no-match card without an empty Other suggestions section when there are no alternatives', async () => {
    mocks.mapSingleTerm.mockResolvedValue(unmappedResponse({ notes: MAPPER_EXPLANATION }));
    const { user } = setup();

    await submitSearch(user);

    expect(await screen.findByText('No confident match')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(MAPPER_EXPLANATION.slice(0, 40)))).toBeInTheDocument();
    expect(screen.queryByText('Other suggestions')).not.toBeInTheDocument();
  });

  it('renders the no-match card without an empty explanation box when the mapper gives no notes', async () => {
    mocks.mapSingleTerm.mockResolvedValue(unmappedResponse());
    const { user, container } = setup();

    await submitSearch(user);

    expect(await screen.findByText('No confident match')).toBeInTheDocument();
    expect(container.querySelector('.result-notes')).toBeNull();
  });

  it('hides Copy code / Download as CSV actions for an UNMAPPED result', async () => {
    mocks.mapSingleTerm.mockResolvedValue(unmappedResponse({ alternatives: unmappedAlternatives }));
    const { user } = setup();

    await submitSearch(user);

    expect(await screen.findByText('No confident match')).toBeInTheDocument();
    expect(screen.queryByText(/copy code/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/download as csv/i)).not.toBeInTheDocument();
  });

  it('still shows the best-match card, its actions, and alternatives for a normal mapped result', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({
      alternatives: [
        { code: 'LOINC:8462-4', term: 'Diastolic blood pressure', ontology: 'LOINC', confidence: 0.4, source: 'rag' },
      ],
    }));
    const { user } = setup();

    await submitSearch(user);

    expect(await screen.findByText('Best match')).toBeInTheDocument();
    expect(screen.getByText(/copy code/i)).toBeInTheDocument();
    expect(screen.getByText(/download as csv/i)).toBeInTheDocument();
    expect(screen.getByText('Other suggestions')).toBeInTheDocument();
    expect(screen.getByText('LOINC:8462-4')).toBeInTheDocument();
    expect(screen.queryByText('No confident match')).not.toBeInTheDocument();
  });

  it('promotes an alternative from an UNMAPPED result into a normal best-match card', async () => {
    mocks.mapSingleTerm.mockResolvedValue(unmappedResponse({ alternatives: unmappedAlternatives }));
    const { user } = setup();

    await submitSearch(user);
    await screen.findByText('No confident match');

    await user.click(screen.getByRole('button', { name: /promote hp:0004421 to best match/i }));

    // The no-match card is gone; a normal mapped best-match card takes its place.
    expect(screen.queryByText('No confident match')).not.toBeInTheDocument();
    expect(await screen.findByText('Best match')).toBeInTheDocument();
    expect(resultCodeTermText()).toBe('HP:0004421 · Elevated systolic blood pressure');

    // Normal actions become available now that a real mapping is selected.
    expect(screen.getByText(/copy code: hp:0004421/i)).toBeInTheDocument();
    expect(screen.getByText(/download as csv/i)).toBeInTheDocument();

    // Remaining alternatives are still shown, and the UNMAPPED placeholder
    // must not appear as a demoted alternative.
    expect(screen.getByText('Other suggestions')).toBeInTheDocument();
    expect(screen.getByText('HP:0500105')).toBeInTheDocument();
    expect(screen.queryByText('UNMAPPED')).not.toBeInTheDocument();
  });
});

describe('SearchPage ontology entity links', () => {
  it('renders the best-match code as an external link when target_url is present', async () => {
    mocks.mapSingleTerm.mockResolvedValue(
      mappingResponse({ target_url: 'https://loinc.org/8480-6' }),
    );
    const { user } = setup();

    await submitSearch(user);

    const link = await screen.findByRole('link', { name: 'LOINC:8480-6' });
    expect(link).toHaveAttribute('href', 'https://loinc.org/8480-6');
  });

  it('renders the best-match code as plain text when target_url is absent', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({ target_url: undefined }));
    const { user } = setup();

    await submitSearch(user);

    await waitFor(() => expect(resultCodeTermText()).toBe('LOINC:8480-6 · Systolic blood pressure'));
    expect(screen.queryByRole('link', { name: 'LOINC:8480-6' })).not.toBeInTheDocument();
  });

  it('promoting an alternative carries its url onto the new best-match card', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({
      target_url: 'https://loinc.org/8480-6',
      alternatives: [
        {
          code: 'LOINC:8462-4',
          term: 'Diastolic blood pressure',
          ontology: 'LOINC',
          confidence: 0.4,
          source: 'rag',
          url: 'https://loinc.org/8462-4',
        },
      ],
    }));
    const { user } = setup();

    await submitSearch(user);
    await screen.findByText('Best match');

    await user.click(screen.getByRole('link', { name: 'LOINC:8462-4' }).closest('tr')!.querySelector('td:nth-child(2)')!);

    await waitFor(() =>
      expect(resultCodeTermText()).toBe('LOINC:8462-4 · Diastolic blood pressure'),
    );
    const promotedLink = screen.getByRole('link', { name: 'LOINC:8462-4' });
    expect(promotedLink).toHaveAttribute('href', 'https://loinc.org/8462-4');

    // The demoted former best match keeps its own url as an alternative.
    expect(screen.getByRole('link', { name: 'LOINC:8480-6' })).toHaveAttribute(
      'href',
      'https://loinc.org/8480-6',
    );
  });

  it('promoting an alternative without a url leaves the new best-match code as plain text', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({
      target_url: 'https://loinc.org/8480-6',
      alternatives: [
        {
          code: 'LOINC:8462-4',
          term: 'Diastolic blood pressure',
          ontology: 'LOINC',
          confidence: 0.4,
          source: 'rag',
          url: undefined,
        },
      ],
    }));
    const { user } = setup();

    await submitSearch(user);
    await screen.findByText('Best match');

    await user.click(screen.getByText('Diastolic blood pressure'));

    await waitFor(() =>
      expect(resultCodeTermText()).toBe('LOINC:8462-4 · Diastolic blood pressure'),
    );
    expect(screen.queryByRole('link', { name: 'LOINC:8462-4' })).not.toBeInTheDocument();
  });

  it('clicking an alternative code link opens the external page without promoting it', async () => {
    mocks.mapSingleTerm.mockResolvedValue(mappingResponse({
      alternatives: [
        {
          code: 'LOINC:8462-4',
          term: 'Diastolic blood pressure',
          ontology: 'LOINC',
          confidence: 0.4,
          source: 'rag',
          url: 'https://loinc.org/8462-4',
        },
      ],
    }));
    const { user } = setup();

    await submitSearch(user);
    await screen.findByText('Best match');

    await user.click(screen.getByRole('link', { name: 'LOINC:8462-4' }));

    // Best match is unchanged — the alternative link click did not promote it.
    expect(resultCodeTermText()).toBe('LOINC:8480-6 · Systolic blood pressure');
    expect(screen.getByRole('link', { name: 'LOINC:8462-4' })).toBeInTheDocument();
  });
});
