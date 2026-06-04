import { isAxiosError } from 'axios';
import { useEffect, useMemo, useRef, useState } from 'react';
import { getAnthropicModels, getConfig, getOllamaLoaded, getOpenAIModels, saveConfig, testConnection } from '../api/configApi';
import AccordionSection from '../components/AccordionSection';
import type { AppConfig, ConnectionTestResponse, Provider, RetrievalMode } from '../types/config';

const DEFAULT_MODEL: Record<Provider, string> = {
  ollama: 'llama3.2',
  ollama_cloud: '',       // populated from /api/tags after first test
  openai: '',
  anthropic: '',
};

// Displayed in the API key field when a key is already loaded in backend memory.
// Never sent to the backend — config.api_key always holds the real key.
const MASKED_KEY_SENTINEL = '••••••••';

const CLOUD_PROVIDERS: Provider[] = ['openai', 'ollama_cloud', 'anthropic'];

type TestState = 'idle' | 'loading' | 'done';

type TestSnapshot = {
  provider: Provider;
  api_key: string | null;
  model: string;
};

export default function SettingsPage() {
  const [config, setConfig] = useState<AppConfig>({
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
  });
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');

  // Display value for the API key field (openai / anthropic only).
  // Kept separate from config.api_key so we can show the masked sentinel
  // without ever sending it to the backend.
  const [apiKeyDisplay, setApiKeyDisplay] = useState('');

  const [testState, setTestState] = useState<TestState>('idle');
  const [testResult, setTestResult] = useState<ConnectionTestResponse | null>(null);

  // Models returned by last successful Ollama Local test (from testConnection response)
  const [ollamaLocalTestModels, setOllamaLocalTestModels] = useState<string[]>([]);
  // True when base_url changed after the last successful Ollama Local test
  const [ollamaBaseUrlDirty, setOllamaBaseUrlDirty] = useState(false);
  // Model currently selected in the Ollama Local dropdown (set after test + on dropdown change)
  const [ollamaLocalSelectedModel, setOllamaLocalSelectedModel] = useState<string>('');
  // Model currently resident in VRAM on the Ollama server (from /api/ps)
  const [ollamaResidentModel, setOllamaResidentModel] = useState<string | null>(null);

  // Models returned by Ollama Cloud /api/tags (from testConnection response)
  const [cloudModels, setCloudModels] = useState<string[]>([]);

  // Models fetched from OpenAI / Anthropic after a successful connection test
  const [openaiModels, setOpenaiModels] = useState<string[]>([]);
  const [openaiModelsWarning, setOpenaiModelsWarning] = useState<string | null>(null);
  const [openaiModelsError, setOpenaiModelsError] = useState<string | null>(null);

  const [anthropicModels, setAnthropicModels] = useState<string[]>([]);
  const [anthropicModelsWarning, setAnthropicModelsWarning] = useState<string | null>(null);
  const [anthropicModelsError, setAnthropicModelsError] = useState<string | null>(null);

  // True when the API key field changed since the last successful connection test
  const [apiKeyDirty, setApiKeyDirty] = useState(false);

  const testRequestIdRef = useRef(0);
  const configRef = useRef(config);

  configRef.current = config;

  // Load config on mount
  useEffect(() => {
    getConfig()
      .then((c) => {
        setConfig(c);
        if (c.api_key && (c.provider === 'openai' || c.provider === 'anthropic')) {
          setApiKeyDisplay(MASKED_KEY_SENTINEL);
        }
        if (c.provider === 'ollama') {
          getOllamaLoaded().then((r) => setOllamaResidentModel(r.resident_model)).catch(() => {});
        }
      })
      .catch(() => {});
  }, []);

  function clearValidationResult() {
    setTestResult(null);
    setTestState('idle');
  }

  function patch(updates: Partial<AppConfig>) {
    setConfig((prev) => {
      const next = { ...prev, ...updates };
      configRef.current = next;
      return next;
    });
    setDirty(true);
    setSaveMsg('');
  }

  function patchModel(model: string) {
    setTestResult(null);
    setTestState('idle');
    setConfig((prev) => {
      const next = { ...prev, model };
      configRef.current = next;
      return next;
    });
    setDirty(true);
    setSaveMsg('');
  }

  function buildTestConfig(): AppConfig {
    const current = configRef.current;
    return {
      ...current,
      model: (current.model ?? '').trim(),
    };
  }

  function matchesTestSnapshot(snapshot: TestSnapshot): boolean {
    const current = configRef.current;
    return (
      snapshot.provider === current.provider &&
      snapshot.api_key === current.api_key &&
      snapshot.model === current.model
    );
  }

  function applyCloudModelsFromTest(
    provider: Provider,
    result: ConnectionTestResponse,
  ) {
    if (!result.available_models?.length) return;
    if (provider === 'ollama_cloud') {
      setCloudModels(result.available_models);
    }
    if (provider === 'openai') {
      setOpenaiModels(result.available_models);
      setOpenaiModelsWarning(null);
      setOpenaiModelsError(null);
    }
    if (provider === 'anthropic') {
      setAnthropicModels(result.available_models);
      setAnthropicModelsWarning(null);
      setAnthropicModelsError(null);
    }
  }

  function testResultMessage(result: ConnectionTestResponse | null, succeeded: boolean): string {
    const msg = result?.message;
    if (typeof msg === 'string' && msg.trim()) return msg;
    return succeeded
      ? 'Connection test succeeded.'
      : 'Connection test failed. Please try again.';
  }

  function isApiKeyValidated(result: ConnectionTestResponse): boolean {
    return result.api_key_ok === true;
  }

  function isDiscoveryOnly(result: ConnectionTestResponse): boolean {
    return (
      result.validation_level === 'discovery' ||
      (result.provider_ok === true && result.api_key_ok !== true && Boolean(result.available_models?.length))
    );
  }

  /** Model catalog returned — unlock dropdown without treating the API key as authenticated. */
  function hasModelCatalogFromTest(result: ConnectionTestResponse): boolean {
    return Boolean(result.available_models?.length) && (isApiKeyValidated(result) || isDiscoveryOnly(result));
  }

  function isModelLevelTestFailure(result: ConnectionTestResponse): boolean {
    return (
      !result.success &&
      result.api_key_ok === true &&
      result.error_type !== 'invalid_api_key'
    );
  }

  function clearProviderModels() {
    setCloudModels([]);
    setOpenaiModels([]);
    setOpenaiModelsWarning(null);
    setOpenaiModelsError(null);
    setAnthropicModels([]);
    setAnthropicModelsWarning(null);
    setAnthropicModelsError(null);
  }

  function markApiKeyDirty() {
    setApiKeyDirty(true);
    clearProviderModels();
    clearValidationResult();
    if (CLOUD_PROVIDERS.includes(configRef.current.provider)) {
      setConfig((prev) => {
        const next = { ...prev, model: '' };
        configRef.current = next;
        return next;
      });
      setDirty(true);
      setSaveMsg('');
    }
  }

  function handleProviderChange(provider: Provider) {
    setTestResult(null);
    setTestState('idle');
    setApiKeyDirty(false);
    setOllamaLocalTestModels([]);
    setOllamaBaseUrlDirty(false);
    setOllamaLocalSelectedModel('');
    setOllamaResidentModel(null);
    setCloudModels([]);
    setOpenaiModels([]);
    setOpenaiModelsWarning(null);
    setOpenaiModelsError(null);
    setAnthropicModels([]);
    setAnthropicModelsWarning(null);
    setAnthropicModelsError(null);
    setApiKeyDisplay('');
    patch({ provider, model: DEFAULT_MODEL[provider] });
    if (provider === 'ollama') {
      getOllamaLoaded().then((r) => setOllamaResidentModel(r.resident_model)).catch(() => {});
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg('');
    try {
      const saved = await saveConfig(buildTestConfig());
      configRef.current = saved;
      setConfig(saved);
      setDirty(false);
      setSaveMsg('Settings saved');
      if (saved.provider === 'ollama') {
        setOllamaLocalTestModels([]);
        setOllamaLocalSelectedModel('');
      }
      window.dispatchEvent(new Event('bridge:status-refresh'));
    } catch {
      setSaveMsg('Failed to save settings.');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    const requestId = ++testRequestIdRef.current;
    const payload = buildTestConfig();
    const snapshot: TestSnapshot = {
      provider: payload.provider,
      api_key: payload.api_key,
      model: payload.model,
    };

    setTestState('loading');
    setTestResult(null);
    if (import.meta.env.DEV) {
      console.debug('[handleTest] payload', {
        provider: payload.provider,
        model: payload.model || '(empty)',
        hasApiKey: Boolean(payload.api_key),
      });
    }
    try {
      const result = await testConnection(payload);
      if (requestId !== testRequestIdRef.current || !matchesTestSnapshot(snapshot)) {
        console.log('[handleTest] stale response ignored');
        return;
      }

      setTestResult(result);

      if (hasModelCatalogFromTest(result)) {
        setApiKeyDirty(false);
      }
      window.dispatchEvent(new Event('bridge:status-refresh'));

      if (payload.provider === 'ollama' && result.success && result.available_models?.length) {
        setOllamaLocalTestModels(result.available_models);
        setOllamaBaseUrlDirty(false);
        if (result.resident_model != null) {
          setOllamaResidentModel(result.resident_model);
        }
        const savedModel = configRef.current.model;
        const resident = result.resident_model ?? null;
        const preselect = result.available_models.includes(savedModel)
          ? savedModel
          : (resident && result.available_models.includes(resident))
            ? resident
            : result.available_models[0];
        setOllamaLocalSelectedModel(preselect);
        if (preselect !== savedModel) {
          setConfig((prev) => {
            const next = { ...prev, model: preselect };
            configRef.current = next;
            return next;
          });
          setDirty(true);
        }
      }

      if (CLOUD_PROVIDERS.includes(payload.provider)) {
        if (result.available_models?.length) {
          applyCloudModelsFromTest(payload.provider, result);
        }
        return;
      }

      // OpenAI / Anthropic fallback when not using unified cloud path (should not run)
      if (config.provider === 'openai' && result.success) {
        const resp = await getOpenAIModels();
        if (requestId !== testRequestIdRef.current) return;
        setOpenaiModels(resp.models);
        setOpenaiModelsWarning(resp.warning ?? null);
        setOpenaiModelsError(resp.error ?? null);
      }
      if (config.provider === 'anthropic' && result.success) {
        const resp = await getAnthropicModels();
        if (requestId !== testRequestIdRef.current) return;
        setAnthropicModels(resp.models);
        setAnthropicModelsWarning(resp.warning ?? null);
        setAnthropicModelsError(resp.error ?? null);
      }
    } catch (err) {
      const message =
        isAxiosError(err) && !err.response
          ? 'Could not reach the backend — is the API server running?'
          : 'Test failed. Please check your settings.';
      if (requestId === testRequestIdRef.current) {
        setTestResult({ success: false, message, api_key_ok: false, provider_ok: false });
      }
    } finally {
      if (requestId === testRequestIdRef.current) {
        setTestState('done');
      }
    }
  }

  const threshold = Math.round(config.rag_auto_accept_threshold * 100);
  const lowThreshold = threshold < 85;

  // Derive connection status CSS class and display text
  const connClass =
    testState === 'loading'
      ? 'conn-status-loading'
      : testResult?.success && testResult?.warning === 'inference_timeout'
        ? 'conn-status-warn'
        : testResult?.success
          ? 'conn-status-ok'
          : testResult && isDiscoveryOnly(testResult)
            ? 'conn-status-info'
            : testResult && isModelLevelTestFailure(testResult)
              ? 'conn-status-warn'
              : 'conn-status-err';

  const showOllamaLocalModels =
    config.provider === 'ollama' && ollamaLocalTestModels.length > 0 && !ollamaBaseUrlDirty;

  const ollamaLocalConnectionMessage = useMemo(() => {
    if (!testResult?.success || config.provider !== 'ollama') return null;
    const n = testResult.available_models?.length ?? 0;
    const countText = `${n} model${n !== 1 ? 's' : ''} available`;
    if (ollamaLocalSelectedModel) {
      return `Connection ${ollamaLocalSelectedModel} OK — ${countText}.`;
    }
    return `Connection OK — ${countText}. Select a model below.`;
  }, [testResult, ollamaLocalSelectedModel, config.provider]);

  const showCloudModels =
    config.provider === 'ollama_cloud' &&
    cloudModels.length > 0 &&
    (!apiKeyDirty || (testResult != null && isDiscoveryOnly(testResult)));
  const showOpenaiModels =
    config.provider === 'openai' && !apiKeyDirty && openaiModels.length > 0 && !openaiModelsError;
  const showAnthropicModels =
    config.provider === 'anthropic' && !apiKeyDirty && anthropicModels.length > 0 && !anthropicModelsError;

  return (
    <div className="settings-page">
      <h1 className="page-title">Settings — Pipeline Configuration</h1>
      <p className="page-subtitle">Configure Pipeline Settings</p>

      {/* ── Layer 1 ─────────────────────────────────────────── */}
      <AccordionSection title="Layer 1 — Input: Smart Term Extraction">
        <div className="field-group">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={config.use_ner}
              onChange={(e) => patch({ use_ner: e.target.checked })}
            />
            <span>Use biomedical term detection</span>
          </label>
          <p className="field-helper">
            <span className="info-icon">ℹ️</span>{' '}
            Before mapping, the tool identifies the key medical concept in your field name
            (e.g. extracts &apos;hypertension&apos; from &apos;htn_diag_age&apos;). Improves accuracy for
            abbreviated names. Requires scispaCy models — disable if not installed.
          </p>
        </div>
      </AccordionSection>

      {/* ── Layer 2 ─────────────────────────────────────────── */}
      <AccordionSection title="Layer 2 — Candidate Retrieval: Finding Ontology Matches">
        <p className="section-question">
          How should the tool find candidate codes before asking the AI?
        </p>

        <div className="radio-group">
          {(
            [
              {
                value: 'public' as RetrievalMode,
                label: 'Public ontology databases',
                desc: 'no setup — uses EBI OLS4, LOINC, RxNav, NIH Clinical Tables',
              },
              {
                value: 'local' as RetrievalMode,
                label: 'Local semantic search',
                desc: 'faster, offline-capable — requires a SapBERT+FAISS server',
              },
              {
                value: 'disabled' as RetrievalMode,
                label: 'Disabled',
                desc: 'AI maps directly without candidate lookup — fastest, but less accurate',
              },
            ] as const
          ).map(({ value, label, desc }) => (
            <label key={value} className="radio-row">
              <input
                type="radio"
                name="retrieval_mode"
                value={value}
                checked={config.retrieval_mode === value}
                onChange={() => patch({ retrieval_mode: value })}
              />
              <span>
                <strong>{label}</strong>
                <br />
                <span className="radio-desc">{desc}</span>
              </span>
            </label>
          ))}
        </div>

        {config.retrieval_mode === 'public' && (
          <div className="subsection">
            <p className="subsection-title">Public databases options</p>
            <div className="field-group">
              <label className="field-label">BioPortal API key</label>
              <input
                type="password"
                className="form-input"
                placeholder="optional — leave blank to skip"
                value={config.bioportal_api_key ?? ''}
                onChange={(e) => patch({ bioportal_api_key: e.target.value || null })}
              />
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Adds BioPortal as a fallback source. Get a free key at bioportal.bioontology.org
                → Account → API key.
              </p>
            </div>

            <div className="field-group">
              <label className="field-label">
                LOINC credentials <span className="optional-mark">(optional)</span>
              </label>
              <div className="input-row">
                <input
                  type="text"
                  className="form-input"
                  placeholder="username"
                  value={config.loinc_username ?? ''}
                  onChange={(e) => patch({ loinc_username: e.target.value || null })}
                />
                <input
                  type="password"
                  className="form-input"
                  placeholder="password"
                  value={config.loinc_password ?? ''}
                  onChange={(e) => patch({ loinc_password: e.target.value || null })}
                />
              </div>
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Required only for LOINC-specific searches.
              </p>
            </div>
          </div>
        )}

        {config.retrieval_mode === 'local' && (
          <div className="subsection">
            <div className="field-group">
              <label className="field-label">SapBERT server URL</label>
              <input
                type="text"
                className="form-input"
                placeholder="http://localhost:8000"
                value={config.sapbert_server_url}
                onChange={(e) => patch({ sapbert_server_url: e.target.value })}
              />
            </div>
          </div>
        )}

        <div className="field-group" style={{ marginTop: '16px' }}>
          <label className="field-label">Auto-accept threshold</label>
          <div className="input-inline">
            <input
              type="number"
              className="form-input form-input-sm"
              min={0}
              max={100}
              value={threshold}
              onChange={(e) => {
                const v = Math.min(100, Math.max(0, parseInt(e.target.value, 10) || 0));
                patch({ rag_auto_accept_threshold: v / 100 });
              }}
            />
            <span className="input-suffix">%</span>
          </div>
          {lowThreshold && (
            <p className="field-warning">
              ⚠️ Low threshold — suggestions may bypass clinical review
            </p>
          )}
          <p className="field-helper">
            <span className="info-icon">ℹ️</span>{' '}
            Suggestions above this confidence are pre-marked &apos;Accepted&apos; in the review table.
            You can still change any of them.
          </p>
        </div>
      </AccordionSection>

      {/* ── Layer 3 ─────────────────────────────────────────── */}
      <AccordionSection title="Layer 3 — AI Model: Final Code Selection">
        <p className="section-question">Which AI would you like to use?</p>

        <div className="radio-group">
          {(
            [
              { value: 'ollama' as Provider, label: 'Ollama Local', desc: 'local — no internet required, no API key' },
              { value: 'ollama_cloud' as Provider, label: 'Ollama Cloud', desc: 'requires API key — billed per use' },
              { value: 'openai' as Provider, label: 'OpenAI', desc: 'requires API key — billed per use' },
              { value: 'anthropic' as Provider, label: 'Anthropic', desc: 'requires API key — billed per use' },
            ] as const
          ).map(({ value, label, desc }) => (
            <label key={value} className="radio-row">
              <input
                type="radio"
                name="provider"
                value={value}
                checked={config.provider === value}
                onChange={() => handleProviderChange(value)}
              />
              <span>
                <strong>{label}</strong>
                <br />
                <span className="radio-desc">{desc}</span>
              </span>
            </label>
          ))}
        </div>

        {/* ── Ollama Local ── */}
        {config.provider === 'ollama' && (
          <div className="subsection">
            <p className="subsection-title">Ollama Local settings</p>
            <div className="field-group">
              <label className="field-label">Server URL</label>
              <input
                type="text"
                className="form-input"
                value={config.base_url}
                onChange={(e) => {
                  patch({ base_url: e.target.value });
                  setOllamaBaseUrlDirty(true);
                  setOllamaLocalTestModels([]);
                  setOllamaLocalSelectedModel('');
                }}
              />
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Change if Ollama runs on a different machine or via SSH tunnel.
              </p>
            </div>
            <div className="field-group">
              <label className="field-label">Model</label>
              {showOllamaLocalModels ? (
                <>
                  <select
                    className="form-input form-select"
                    value={config.model}
                    onChange={(e) => {
                      const model = e.target.value;
                      setConfig((prev) => {
                        const next = { ...prev, model };
                        configRef.current = next;
                        return next;
                      });
                      setOllamaLocalSelectedModel(model);
                      setDirty(true);
                      setSaveMsg('');
                    }}
                  >
                    {ollamaLocalTestModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  <p className="field-helper">Select a model then save settings</p>
                </>
              ) : (
                <input
                  type="text"
                  className="form-input"
                  disabled
                  placeholder={config.model || 'Test connection to load models'}
                  value=""
                />
              )}
              {ollamaResidentModel && (
                <p className="field-helper">
                  On the current endpoint ({config.base_url}), the model &apos;{ollamaResidentModel}&apos; is
                  currently loaded in memory — it makes sense to use this model to avoid a cold-load delay.
                </p>
              )}
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Click &quot;Test connection&quot; to discover available models.
              </p>
            </div>
          </div>
        )}

        {/* ── Ollama Cloud ── */}
        {config.provider === 'ollama_cloud' && (
          <div className="subsection">
            <p className="subsection-title">Ollama Cloud settings</p>
            <div className="field-group">
              <label className="field-label">API key</label>
              <input
                type="password"
                className="form-input"
                placeholder="sk-..."
                value={config.api_key ?? ''}
                onChange={(e) => {
                  patch({ api_key: e.target.value || null });
                  markApiKeyDirty();
                }}
              />
            </div>
            <div className="field-group">
              <label className="field-label">Model</label>
              {showCloudModels ? (
                <select
                  className="form-input form-select"
                  value={config.model}
                  onChange={(e) => patchModel(e.target.value)}
                >
                  <option value="">— select a model —</option>
                  {cloudModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  className="form-input"
                  disabled
                  placeholder="Test connection to load models"
                  value=""
                />
              )}
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Click &quot;Test connection&quot; to discover available cloud models,
                then select one and test again to validate your API key.
              </p>
            </div>
          </div>
        )}

        {/* ── OpenAI ── */}
        {config.provider === 'openai' && (
          <div className="subsection">
            <p className="subsection-title">OpenAI settings</p>
            <div className="field-group">
              <label className="field-label">API key</label>
              <input
                type="password"
                className="form-input"
                placeholder="sk-..."
                value={apiKeyDisplay}
                onFocus={() => {
                  if (apiKeyDisplay === MASKED_KEY_SENTINEL) setApiKeyDisplay('');
                }}
                onChange={(e) => {
                  const val = e.target.value;
                  setApiKeyDisplay(val);
                  patch({ api_key: val || null });
                  markApiKeyDirty();
                }}
              />
            </div>
            <div className="field-group">
              <label className="field-label">Model</label>
              {openaiModelsError ? (
                <>
                  <input
                    type="text"
                    className="form-input"
                    value={config.model}
                    onChange={(e) => patchModel(e.target.value)}
                  />
                  <p className="field-error">{openaiModelsError}</p>
                </>
              ) : showOpenaiModels ? (
                <>
                  <select
                    className="form-input form-select"
                    value={config.model}
                    onChange={(e) => patchModel(e.target.value)}
                  >
                    <option value="">— select a model —</option>
                    {openaiModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  {openaiModelsWarning && (
                    <p className="field-warning">⚠️ {openaiModelsWarning}</p>
                  )}
                </>
              ) : (
                <input
                  type="text"
                  className="form-input"
                  disabled
                  placeholder="Test connection to load models"
                  value=""
                />
              )}
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Click &quot;Test connection&quot; to discover available models.
              </p>
            </div>
          </div>
        )}

        {/* ── Anthropic ── */}
        {config.provider === 'anthropic' && (
          <div className="subsection">
            <p className="subsection-title">Anthropic settings</p>
            <div className="field-group">
              <label className="field-label">API key</label>
              <input
                type="password"
                className="form-input"
                placeholder="sk-ant-..."
                value={apiKeyDisplay}
                onFocus={() => {
                  if (apiKeyDisplay === MASKED_KEY_SENTINEL) setApiKeyDisplay('');
                }}
                onChange={(e) => {
                  const val = e.target.value;
                  setApiKeyDisplay(val);
                  patch({ api_key: val || null });
                  markApiKeyDirty();
                }}
              />
            </div>
            <div className="field-group">
              <label className="field-label">Model</label>
              {anthropicModelsError ? (
                <>
                  <input
                    type="text"
                    className="form-input"
                    value={config.model}
                    onChange={(e) => patchModel(e.target.value)}
                  />
                  <p className="field-error">{anthropicModelsError}</p>
                </>
              ) : showAnthropicModels ? (
                <>
                  <select
                    className="form-input form-select"
                    value={config.model}
                    onChange={(e) => patchModel(e.target.value)}
                  >
                    <option value="">— select a model —</option>
                    {anthropicModels.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  {anthropicModelsWarning && (
                    <p className="field-warning">⚠️ {anthropicModelsWarning}</p>
                  )}
                </>
              ) : (
                <input
                  type="text"
                  className="form-input"
                  disabled
                  placeholder="Test connection to load models"
                  value=""
                />
              )}
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Click &quot;Test connection&quot; to discover available models.
              </p>
            </div>
          </div>
        )}
      </AccordionSection>

      {/* ── Info banner ──────────────────────────────────────── */}
      <div className="info-banner">
        💾 Settings are saved to a local file on this computer. API keys are held in memory
        only and will need to be re-entered when the app restarts.
      </div>

      {/* ── Actions ──────────────────────────────────────────── */}
      <div className="settings-actions">
        <button
          className="btn-primary"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving…' : '💾 Save settings'}
        </button>
        <button
          className="btn-outline"
          onClick={handleTest}
          disabled={testState === 'loading'}
        >
          {testState === 'loading' ? '⏳ Testing…' : '🔌 Test connection'}
        </button>
        {dirty && !saving && <span className="unsaved-dot">● Unsaved changes</span>}
        {saveMsg && !dirty && <span className="save-ok">{saveMsg}</span>}
      </div>

      {/* ── Connection status ────────────────────────────────── */}
      {testState === 'loading' && (
        <div className="conn-status conn-status-loading">⏳ Testing connection…</div>
      )}
      {testState === 'done' && testResult && (
        <div className={`conn-status ${connClass}`}>
          {testResult.success && testResult.warning === 'inference_timeout' &&
            `⚠️ ${testResultMessage(testResult, true)}`}
          {testResult.success && testResult.warning !== 'inference_timeout' &&
            `✅ ${config.provider === 'ollama' && ollamaLocalConnectionMessage
              ? ollamaLocalConnectionMessage
              : testResultMessage(testResult, true)}`}
          {!testResult.success && isDiscoveryOnly(testResult) &&
            `ℹ️ ${testResultMessage(testResult, false)}`}
          {!testResult.success && isModelLevelTestFailure(testResult) &&
            `⚠️ ${testResultMessage(testResult, false)}`}
          {!testResult.success && !isDiscoveryOnly(testResult) && !isModelLevelTestFailure(testResult) &&
            `❌ ${testResultMessage(testResult, false)}`}
        </div>
      )}
      {testState === 'done' && testResult?.sapbert_status === 'ok' && (
        <div className="conn-status conn-status-ok" style={{ marginTop: '6px' }}>
          ✅ SapBERT server reachable
        </div>
      )}
      {testState === 'done' && testResult?.sapbert_status === 'unreachable' && (
        <div className="conn-status conn-status-warn" style={{ marginTop: '6px' }}>
          ⚠️ SapBERT server not reachable at {config.sapbert_server_url} — candidate retrieval will not work. Switch to Public databases or check your server.
        </div>
      )}
    </div>
  );
}
