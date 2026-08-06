import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SettingsPage from './SettingsPage';
import type { AppConfig, ComponentTestResult, ConnectionTestResponse } from '../types/config';

const mocks = vi.hoisted(() => ({
  getConfig: vi.fn(),
  saveConfig: vi.fn(),
  testConnection: vi.fn(),
  invalidateRetrievalValidation: vi.fn(),
  getOllamaLoaded: vi.fn(),
  getOpenAIModels: vi.fn(),
  getAnthropicModels: vi.fn(),
}));

vi.mock('../api/configApi', () => ({
  getConfig: mocks.getConfig,
  saveConfig: mocks.saveConfig,
  testConnection: mocks.testConnection,
  invalidateRetrievalValidation: mocks.invalidateRetrievalValidation,
  getOllamaLoaded: mocks.getOllamaLoaded,
  getOpenAIModels: mocks.getOpenAIModels,
  getAnthropicModels: mocks.getAnthropicModels,
}));

const MASKED_SECRET_SENTINEL = '••••••••';
const LOINC_ACCOUNT_URL = 'https://loinc.org/join/';

const baseConfig: AppConfig = {
  use_ner: true,
  retrieval_mode: 'public',
  bioportal_api_key: null,
  loinc_username: null,
  loinc_password: null,
  sapbert_server_url: 'http://localhost:8000',
  rag_auto_accept_threshold: 0.85,
  provider: 'ollama',
  model: 'llama3.2',
  base_url: 'http://localhost:11434',
  api_key: null,
};

function componentResult(
  status: ComponentTestResult['status'],
  message: string,
  code: string = status,
): ComponentTestResult {
  return {
    valid: status === 'valid' || status === 'not_required',
    status,
    code,
    message,
  };
}

function connectionResponse(
  overrides: Partial<ConnectionTestResponse> = {},
): ConnectionTestResponse {
  const candidate = overrides.candidate_retrieval ?? componentResult(
    'valid',
    'LOINC credentials are valid.',
    'loinc_credentials_valid',
  );
  const ai = overrides.ai_model ?? componentResult(
    'valid',
    'AI model connection is valid.',
    'provider_connection_valid',
  );
  return {
    success: Boolean(candidate.valid && ai.valid),
    message: candidate.valid && ai.valid ? 'Connection test succeeded.' : 'Connection test failed.',
    candidate_retrieval: candidate,
    ai_model: ai,
    available_models: ['llama3.2'],
    api_key_ok: ai.valid,
    model_ok: ai.valid,
    provider_ok: ai.valid,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function setup(config: Partial<AppConfig> = {}) {
  const loaded = { ...baseConfig, ...config };
  mocks.getConfig.mockResolvedValue(loaded);
  mocks.saveConfig.mockImplementation(async (next: AppConfig) => next);
  if (!mocks.testConnection.getMockImplementation()) {
    mocks.testConnection.mockResolvedValue(connectionResponse());
  }
  mocks.invalidateRetrievalValidation.mockResolvedValue(undefined);
  mocks.getOllamaLoaded.mockResolvedValue({ resident_model: null });
  return {
    user: userEvent.setup(),
    ...render(<SettingsPage />),
  };
}

function resultRow(label: 'Candidate Retrieval' | 'AI Model'): HTMLElement {
  const heading = screen.getByText(`${label}:`);
  const row = heading.closest('[role]');
  if (!row) {
    throw new Error(`Could not find ${label} result row`);
  }
  return row as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('SettingsPage LOINC credentials panel', () => {
  it('shows the LOINC credentials panel in public mode with the expected controls and guidance', async () => {
    setup();

    const panel = await screen.findByLabelText('LOINC credentials');
    expect(within(panel).getByText('LOINC credentials')).toBeInTheDocument();
    expect(within(panel).getByText('LOINC requires an account to search its terminology API.')).toBeInTheDocument();
    expect(within(panel).getByLabelText('LOINC username')).toBeInTheDocument();

    const password = within(panel).getByLabelText('LOINC password');
    expect(password).toHaveAttribute('type', 'password');

    const link = within(panel).getByRole('link', { name: 'Create a LOINC account' });
    expect(link).toHaveAttribute('href', LOINC_ACCOUNT_URL);
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));

    expect(
      within(panel).getByText('Enter your credentials, then use "Test connection" at the bottom of the page.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /test loinc connection/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /test connection/i })).toHaveLength(1);
  });

  it('hides the LOINC credentials panel in local and disabled modes while preserving existing retrieval UI', async () => {
    const { user } = setup();
    await screen.findByLabelText('LOINC credentials');

    await user.click(screen.getByRole('radio', { name: /local semantic search/i }));

    expect(screen.queryByLabelText('LOINC credentials')).not.toBeInTheDocument();
    expect(screen.getByText('SapBERT server URL')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('http://localhost:8000')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: /disabled/i }));

    expect(screen.queryByLabelText('LOINC credentials')).not.toBeInTheDocument();
    expect(screen.queryByText('SapBERT server URL')).not.toBeInTheDocument();
    expect(screen.getByText('Auto-accept threshold')).toBeInTheDocument();
  });

  it('updates LOINC username and password form state and keeps the username in the save payload', async () => {
    const { user } = setup();

    await user.type(await screen.findByLabelText('LOINC username'), '  loinc-user  ');
    await user.type(screen.getByLabelText('LOINC password'), 'loinc-secret');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    await waitFor(() => expect(mocks.saveConfig).toHaveBeenCalled());
    const saved = mocks.saveConfig.mock.calls[0][0] as AppConfig;
    expect(saved.loinc_username).toBe('loinc-user');
    expect(saved.loinc_password).toBe('loinc-secret');
  });

  it('does not submit a loaded masked password as a new real password when saving', async () => {
    const { user } = setup({
      loinc_username: 'loinc-user',
      loinc_password: MASKED_SECRET_SENTINEL,
    });

    const password = await screen.findByLabelText('LOINC password');
    expect(password).toHaveValue(MASKED_SECRET_SENTINEL);

    await user.clear(screen.getByLabelText('LOINC username'));
    await user.type(screen.getByLabelText('LOINC username'), 'new-user');
    await user.click(screen.getByRole('button', { name: /save settings/i }));

    await waitFor(() => expect(mocks.saveConfig).toHaveBeenCalled());
    const saved = mocks.saveConfig.mock.calls[0][0] as AppConfig;
    expect(saved.loinc_username).toBe('new-user');
    expect(saved.loinc_password).toBe(MASKED_SECRET_SENTINEL);
  });

  it('does not mark Candidate Retrieval ready when credentials are merely entered', async () => {
    const { user } = setup();

    await user.type(await screen.findByLabelText('LOINC username'), 'loinc-user');
    await user.type(screen.getByLabelText('LOINC password'), 'loinc-secret');

    expect(screen.queryByText('Candidate Retrieval:')).not.toBeInTheDocument();
    expect(screen.queryByText(/LOINC credentials are valid/i)).not.toBeInTheDocument();
    expect(mocks.testConnection).not.toHaveBeenCalled();
  });

  it('preserves existing AI provider configuration behavior', async () => {
    const { user } = setup();
    await screen.findByLabelText('LOINC credentials');

    await user.click(screen.getByRole('radio', { name: /openai/i }));

    expect(screen.getByText('OpenAI settings')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('sk-...')).toHaveAttribute('type', 'password');
    expect(screen.getByPlaceholderText('Test connection to load models')).toBeDisabled();
  });
});

describe('SettingsPage connection testing', () => {
  it('uses the bottom Test connection button as the only test action', async () => {
    setup();
    await screen.findByLabelText('LOINC credentials');

    expect(screen.queryByRole('button', { name: /test loinc connection/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /test connection/i })).toHaveLength(1);
  });

  it('sends entered LOINC credentials in public mode', async () => {
    const { user } = setup();

    await user.type(await screen.findByLabelText('LOINC username'), '  loinc-user  ');
    await user.type(screen.getByLabelText('LOINC password'), 'loinc-secret');
    await user.click(screen.getByRole('button', { name: /test connection/i }));

    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalled());
    const payload = mocks.testConnection.mock.calls[0][0] as AppConfig;
    expect(payload.retrieval_mode).toBe('public');
    expect(payload.loinc_username).toBe('loinc-user');
    expect(payload.loinc_password).toBe('loinc-secret');
  });

  it('does not send the masked LOINC password sentinel during connection testing', async () => {
    const { user } = setup({
      loinc_username: 'loinc-user',
      loinc_password: MASKED_SECRET_SENTINEL,
    });

    expect(await screen.findByLabelText('LOINC password')).toHaveValue(MASKED_SECRET_SENTINEL);
    await user.click(screen.getByRole('button', { name: /test connection/i }));

    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalled());
    const payload = mocks.testConnection.mock.calls[0][0] as AppConfig;
    expect(payload.loinc_username).toBe('loinc-user');
    expect(payload.loinc_password).toBeNull();
  });

  it('does not send LOINC credentials in local or disabled modes', async () => {
    const { user } = setup({
      loinc_username: 'loinc-user',
      loinc_password: 'loinc-secret',
    });
    await screen.findByLabelText('LOINC credentials');

    await user.click(screen.getByRole('radio', { name: /local semantic search/i }));
    await user.click(screen.getByRole('button', { name: /test connection/i }));
    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalledTimes(1));
    let payload = mocks.testConnection.mock.calls[0][0] as AppConfig;
    expect(payload.loinc_username).toBeNull();
    expect(payload.loinc_password).toBeNull();

    await user.click(screen.getByRole('radio', { name: /disabled/i }));
    await user.click(screen.getByRole('button', { name: /test connection/i }));
    await waitFor(() => expect(mocks.testConnection).toHaveBeenCalledTimes(2));
    payload = mocks.testConnection.mock.calls[1][0] as AppConfig;
    expect(payload.loinc_username).toBeNull();
    expect(payload.loinc_password).toBeNull();
  });

  it('displays separate Candidate Retrieval and AI Model success messages with status roles', async () => {
    const { user } = setup();
    await screen.findByLabelText('LOINC credentials');

    await user.click(screen.getByRole('button', { name: /test connection/i }));

    await screen.findByText('Candidate Retrieval:');
    expect(resultRow('Candidate Retrieval')).toHaveAttribute('role', 'status');
    expect(resultRow('Candidate Retrieval')).toHaveTextContent('LOINC credentials are valid.');
    expect(resultRow('AI Model')).toHaveAttribute('role', 'status');
    expect(resultRow('AI Model')).toHaveTextContent('Connection llama3.2 OK');
  });

  it('displays both invalid component results as alerts', async () => {
    mocks.testConnection.mockResolvedValue(connectionResponse({
      candidate_retrieval: componentResult('invalid', 'The LOINC username or password is incorrect.'),
      ai_model: componentResult('invalid', 'The API key is invalid.', 'invalid_api_key'),
      success: false,
      api_key_ok: false,
      model_ok: false,
      provider_ok: true,
    }));
    const { user } = setup();

    await user.click(await screen.findByRole('button', { name: /test connection/i }));

    await screen.findByText('Candidate Retrieval:');
    expect(resultRow('Candidate Retrieval')).toHaveAttribute('role', 'alert');
    expect(resultRow('Candidate Retrieval')).toHaveTextContent('The LOINC username or password is incorrect.');
    expect(resultRow('AI Model')).toHaveAttribute('role', 'alert');
    expect(resultRow('AI Model')).toHaveTextContent('The API key is invalid.');
  });

  it('preserves AI Model failure when Candidate Retrieval is valid', async () => {
    mocks.testConnection.mockResolvedValue(connectionResponse({
      candidate_retrieval: componentResult('valid', 'LOINC credentials are valid.'),
      ai_model: componentResult('invalid', 'The selected model is unavailable.', 'model_unavailable'),
      success: false,
      api_key_ok: true,
      model_ok: false,
    }));
    const { user } = setup();

    await user.click(await screen.findByRole('button', { name: /test connection/i }));

    await screen.findByText('Candidate Retrieval:');
    expect(resultRow('Candidate Retrieval')).toHaveAttribute('role', 'status');
    expect(resultRow('Candidate Retrieval')).toHaveTextContent('LOINC credentials are valid.');
    expect(resultRow('AI Model')).toHaveAttribute('role', 'alert');
    expect(resultRow('AI Model')).toHaveTextContent('The selected model is unavailable.');
  });

  it('preserves AI Model success when Candidate Retrieval is invalid', async () => {
    mocks.testConnection.mockResolvedValue(connectionResponse({
      candidate_retrieval: componentResult('invalid', 'Enter a LOINC username and password before testing.'),
      ai_model: componentResult('valid', 'AI model connection is valid.'),
      available_models: [],
      success: false,
    }));
    const { user } = setup();

    await user.click(await screen.findByRole('button', { name: /test connection/i }));

    await screen.findByText('Candidate Retrieval:');
    expect(resultRow('Candidate Retrieval')).toHaveAttribute('role', 'alert');
    expect(resultRow('Candidate Retrieval')).toHaveTextContent('Enter a LOINC username and password before testing.');
    expect(resultRow('AI Model')).toHaveAttribute('role', 'status');
    expect(resultRow('AI Model')).toHaveTextContent('AI model connection is valid.');
  });

  it('shows disabled retrieval as a not-required status result', async () => {
    mocks.testConnection.mockResolvedValue(connectionResponse({
      candidate_retrieval: componentResult(
        'not_required',
        'Candidate retrieval is disabled; no connection test was required.',
        'retrieval_disabled',
      ),
    }));
    const { user } = setup({ retrieval_mode: 'disabled' });

    await user.click(await screen.findByRole('button', { name: /test connection/i }));

    await screen.findByText('Candidate Retrieval:');
    expect(resultRow('Candidate Retrieval')).toHaveAttribute('role', 'status');
    expect(resultRow('Candidate Retrieval')).toHaveTextContent(
      'Candidate retrieval is disabled; no connection test was required.',
    );
  });

  it('shows loading state and prevents duplicate submissions', async () => {
    const pending = deferred<ConnectionTestResponse>();
    mocks.testConnection.mockReturnValue(pending.promise);
    const { user } = setup();

    const button = await screen.findByRole('button', { name: /test connection/i });
    await user.click(button);
    await user.click(button);

    expect(screen.getByRole('status')).toHaveTextContent('Testing connection');
    expect(mocks.testConnection).toHaveBeenCalledTimes(1);

    pending.resolve(connectionResponse());
    await screen.findByText('Candidate Retrieval:');
  });

  it('invalidates only Candidate Retrieval when LOINC username changes after success', async () => {
    const { user } = setup({ loinc_username: 'loinc-user', loinc_password: 'loinc-secret' });

    await user.click(await screen.findByRole('button', { name: /test connection/i }));
    await screen.findByText('Candidate Retrieval:');

    await user.clear(screen.getByLabelText('LOINC username'));
    await user.type(screen.getByLabelText('LOINC username'), 'new-user');

    expect(screen.queryByText('Candidate Retrieval:')).not.toBeInTheDocument();
    expect(resultRow('AI Model')).toHaveTextContent('Connection llama3.2 OK');
    await waitFor(() => expect(mocks.invalidateRetrievalValidation).toHaveBeenCalled());
  });

  it('invalidates only Candidate Retrieval when LOINC password changes after success', async () => {
    const { user } = setup({ loinc_username: 'loinc-user', loinc_password: 'loinc-secret' });

    await user.click(await screen.findByRole('button', { name: /test connection/i }));
    await screen.findByText('Candidate Retrieval:');

    await user.clear(screen.getByLabelText('LOINC password'));
    await user.type(screen.getByLabelText('LOINC password'), 'new-secret');

    expect(screen.queryByText('Candidate Retrieval:')).not.toBeInTheDocument();
    expect(resultRow('AI Model')).toHaveTextContent('Connection llama3.2 OK');
    await waitFor(() => expect(mocks.invalidateRetrievalValidation).toHaveBeenCalled());
  });

  it('invalidates only AI Model when AI configuration changes after success', async () => {
    const { user } = setup({ loinc_username: 'loinc-user', loinc_password: 'loinc-secret' });

    await user.click(await screen.findByRole('button', { name: /test connection/i }));
    await screen.findByText('AI Model:');

    await user.click(screen.getByRole('radio', { name: /openai/i }));

    expect(resultRow('Candidate Retrieval')).toHaveTextContent('LOINC credentials are valid.');
    expect(screen.queryByText('AI Model:')).not.toBeInTheDocument();
  });

  it('does not apply a stale Candidate Retrieval success after credentials change during a request', async () => {
    const pending = deferred<ConnectionTestResponse>();
    mocks.testConnection.mockReturnValue(pending.promise);
    const { user } = setup({ loinc_username: 'old-user', loinc_password: 'old-secret' });

    await user.click(await screen.findByRole('button', { name: /test connection/i }));
    await user.clear(screen.getByLabelText('LOINC username'));
    await user.type(screen.getByLabelText('LOINC username'), 'new-user');
    pending.resolve(connectionResponse());

    await screen.findByText('AI Model:');
    expect(screen.queryByText('Candidate Retrieval:')).not.toBeInTheDocument();
    expect(resultRow('AI Model')).toHaveTextContent('Connection llama3.2 OK');
  });

  it('dispatches bridge:status-refresh after testing', async () => {
    const refreshHandler = vi.fn();
    window.addEventListener('bridge:status-refresh', refreshHandler);
    const { user } = setup();

    await user.click(await screen.findByRole('button', { name: /test connection/i }));

    await waitFor(() => expect(refreshHandler).toHaveBeenCalledTimes(1));
    window.removeEventListener('bridge:status-refresh', refreshHandler);
  });

  it('keeps available-model discovery working for Ollama Local', async () => {
    mocks.testConnection.mockResolvedValue(connectionResponse({
      available_models: ['mistral', 'llama3.2'],
      resident_model: 'mistral',
    }));
    const { user } = setup({ model: 'missing-model' });

    await user.click(await screen.findByRole('button', { name: /test connection/i }));

    const modelSelect = await screen.findByRole('combobox');
    expect(within(modelSelect).getByRole('option', { name: 'mistral' })).toBeInTheDocument();
    expect(within(modelSelect).getByRole('option', { name: 'llama3.2' })).toBeInTheDocument();
    expect(modelSelect).toHaveValue('mistral');
  });
});
