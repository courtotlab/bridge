import { isAxiosError } from 'axios';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  discoverOllamaModels,
  getAnthropicModels,
  getConfig,
  getOllamaLoaded,
  getOpenAIModels,
  invalidateRetrievalValidation,
  saveConfig,
  testConnection,
} from '../api/configApi';
import AccordionSection from '../components/AccordionSection';
import type { AppConfig, ComponentTestResult, ConnectionTestResponse, Provider, RetrievalMode } from '../types/config';

const DEFAULT_MODEL: Record<Provider, string> = {
  ollama: '',
  ollama_cloud: '',       // populated from /api/tags after first test
  openai: '',
  anthropic: '',
};

// Displayed in the API key field when a key is already loaded in backend memory.
// Never sent to the backend — config.api_key always holds the real key.
const MASKED_KEY_SENTINEL = '••••••••';
const LOINC_ACCOUNT_URL = 'https://loinc.org/join/';

const CLOUD_PROVIDERS: Provider[] = ['openai', 'ollama_cloud', 'anthropic'];

type TestState = 'idle' | 'loading' | 'done';
type ModelDiscoveryState = 'idle' | 'loading' | 'done' | 'error';

type TestSnapshot = {
  aiRevision: number;
  retrievalRevision: number;
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
  const [candidateRetrievalResult, setCandidateRetrievalResult] = useState<ComponentTestResult | null>(null);
  const [aiModelResult, setAiModelResult] = useState<ComponentTestResult | null>(null);

  // Models discovered from the configured Ollama Local server without running inference.
  const [ollamaLocalModels, setOllamaLocalModels] = useState<string[]>([]);
  const [ollamaModelDiscoveryState, setOllamaModelDiscoveryState] = useState<ModelDiscoveryState>('idle');
  const [ollamaModelDiscoveryError, setOllamaModelDiscoveryError] = useState<string | null>(null);
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
  const [loincPasswordDisplay, setLoincPasswordDisplay] = useState('');
  const [loincCredentialsDirty, setLoincCredentialsDirty] = useState(false);

  const testRequestIdRef = useRef(0);
  const ollamaDiscoveryRequestIdRef = useRef(0);
  const ollamaDiscoveryInFlightUrlRef = useRef<string | null>(null);
  const aiRevisionRef = useRef(0);
  const retrievalRevisionRef = useRef(0);
  const configRef = useRef(config);

  configRef.current = config;

  // Load config on mount
  useEffect(() => {
    getConfig()
      .then((c) => {
        configRef.current = c;
        setConfig(c);
        if (c.api_key && (c.provider === 'openai' || c.provider === 'anthropic')) {
          setApiKeyDisplay(MASKED_KEY_SENTINEL);
        }
        if (c.loinc_password === MASKED_KEY_SENTINEL) {
          setLoincPasswordDisplay(MASKED_KEY_SENTINEL);
        } else {
          setLoincPasswordDisplay(c.loinc_password ?? '');
        }
        if (c.provider === 'ollama') {
          getOllamaLoaded().then((r) => setOllamaResidentModel(r.resident_model)).catch(() => {});
          void discoverLocalOllamaModels(c.base_url);
        }
      })
      .catch(() => {});
  }, []);

  async function discoverLocalOllamaModels(baseUrl = configRef.current.base_url, options: { force?: boolean } = {}) {
    const targetBaseUrl = baseUrl.trim();
    if (!targetBaseUrl) return;
    if (!options.force && ollamaDiscoveryInFlightUrlRef.current === targetBaseUrl) return;

    const requestId = ++ollamaDiscoveryRequestIdRef.current;
    ollamaDiscoveryInFlightUrlRef.current = targetBaseUrl;
    setOllamaModelDiscoveryState('loading');
    setOllamaModelDiscoveryError(null);
    try {
      const result = await discoverOllamaModels(targetBaseUrl);
      if (requestId !== ollamaDiscoveryRequestIdRef.current || configRef.current.provider !== 'ollama') return;
      const models = result.models;
      setOllamaLocalModels(models);
      setOllamaModelDiscoveryState('done');
      const currentModel = (configRef.current.model ?? '').trim();
      if (currentModel && !models.includes(currentModel)) {
        clearAiModelResult();
        setConfig((prev) => {
          const next = { ...prev, model: '' };
          configRef.current = next;
          return next;
        });
        setDirty(true);
        setSaveMsg('');
      }
    } catch {
      if (requestId !== ollamaDiscoveryRequestIdRef.current || configRef.current.provider !== 'ollama') return;
      setOllamaLocalModels([]);
      setOllamaModelDiscoveryState('error');
      setOllamaModelDiscoveryError('Could not load models from this Ollama server.');
    } finally {
      if (ollamaDiscoveryInFlightUrlRef.current === targetBaseUrl) {
        ollamaDiscoveryInFlightUrlRef.current = null;
      }
    }
  }

  function dispatchStatusRefresh() {
    window.dispatchEvent(new Event('bridge:status-refresh'));
  }

  function clearCandidateRetrievalResult(options: { invalidateBackend?: boolean } = {}) {
    retrievalRevisionRef.current += 1;
    if (options.invalidateBackend && candidateRetrievalResult?.valid) {
      void invalidateRetrievalValidation().finally(dispatchStatusRefresh);
    }
    setCandidateRetrievalResult(null);
  }

  function clearAiModelResult() {
    aiRevisionRef.current += 1;
    setAiModelResult(null);
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
    clearAiModelResult();
    setConfig((prev) => {
      const next = { ...prev, model };
      configRef.current = next;
      return next;
    });
    setDirty(true);
    setSaveMsg('');
  }

  function normalizedLoincPasswordForSave(): string | null {
    if (loincPasswordDisplay === MASKED_KEY_SENTINEL) {
      return MASKED_KEY_SENTINEL;
    }
    return loincPasswordDisplay || null;
  }

  function normalizedLoincPasswordForTest(): string | null {
    if (loincPasswordDisplay === MASKED_KEY_SENTINEL) {
      return null;
    }
    if (loincCredentialsDirty && loincPasswordDisplay === '') {
      return '';
    }
    return loincPasswordDisplay || null;
  }

  function buildConfigPayload(mode: 'save' | 'test'): AppConfig {
    const current = configRef.current;
    const includeLoincCredentials = mode === 'save' || current.retrieval_mode === 'public';
    return {
      ...current,
      loinc_username: includeLoincCredentials ? current.loinc_username?.trim() || null : null,
      loinc_password: includeLoincCredentials
        ? mode === 'save'
          ? normalizedLoincPasswordForSave()
          : normalizedLoincPasswordForTest()
        : null,
      model: (current.model ?? '').trim(),
    };
  }

  function matchesAiSnapshot(snapshot: TestSnapshot): boolean {
    return snapshot.aiRevision === aiRevisionRef.current;
  }

  function matchesRetrievalSnapshot(snapshot: TestSnapshot): boolean {
    return snapshot.retrievalRevision === retrievalRevisionRef.current;
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
    clearAiModelResult();
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

  function markLoincCredentialsDirty() {
    setLoincCredentialsDirty(true);
    clearCandidateRetrievalResult({ invalidateBackend: configRef.current.retrieval_mode === 'public' });
  }

  function handleRetrievalModeChange(retrieval_mode: RetrievalMode) {
    clearCandidateRetrievalResult({ invalidateBackend: configRef.current.retrieval_mode === 'public' });
    patch({ retrieval_mode });
  }

  function handleProviderChange(provider: Provider) {
    clearAiModelResult();
    setApiKeyDirty(false);
    setOllamaLocalModels([]);
    setOllamaModelDiscoveryState('idle');
    setOllamaModelDiscoveryError(null);
    setOllamaResidentModel(null);
    setCloudModels([]);
    setOpenaiModels([]);
    setOpenaiModelsWarning(null);
    setOpenaiModelsError(null);
    setAnthropicModels([]);
    setAnthropicModelsWarning(null);
    setAnthropicModelsError(null);
    setApiKeyDisplay('');
    const nextConfig = { ...configRef.current, provider, model: DEFAULT_MODEL[provider] };
    configRef.current = nextConfig;
    setConfig(nextConfig);
    setDirty(true);
    setSaveMsg('');
    if (provider === 'ollama') {
      getOllamaLoaded().then((r) => setOllamaResidentModel(r.resident_model)).catch(() => {});
      void discoverLocalOllamaModels(nextConfig.base_url, { force: true });
    }
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg('');
    try {
      const saved = await saveConfig(buildConfigPayload('save'));
      configRef.current = saved;
      setConfig(saved);
      if (saved.loinc_password === MASKED_KEY_SENTINEL) {
        setLoincPasswordDisplay(MASKED_KEY_SENTINEL);
      } else {
        setLoincPasswordDisplay(saved.loinc_password ?? '');
      }
      setLoincCredentialsDirty(false);
      setDirty(false);
      setSaveMsg('Settings saved');
      dispatchStatusRefresh();
    } catch {
      setSaveMsg('Failed to save settings.');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    if (testState === 'loading') return;
    const requestId = ++testRequestIdRef.current;
    const payload = buildConfigPayload('test');
    const snapshot: TestSnapshot = {
      aiRevision: aiRevisionRef.current,
      retrievalRevision: retrievalRevisionRef.current,
    };

    setTestState('loading');
    setTestResult(null);
    setCandidateRetrievalResult(null);
    setAiModelResult(null);
    if (import.meta.env.DEV) {
      console.debug('[handleTest] payload', {
        provider: payload.provider,
        model: payload.model || '(empty)',
        hasApiKey: Boolean(payload.api_key),
        hasLoincPassword: Boolean(payload.loinc_password),
      });
    }
    try {
      const result = await testConnection(payload);
      if (requestId !== testRequestIdRef.current) {
        console.log('[handleTest] stale response ignored');
        return;
      }

      setTestResult(result);

      const retrievalResult = result.candidate_retrieval ?? null;
      const aiResult = result.ai_model ?? {
        valid: result.success,
        status: result.success ? 'valid' : 'error',
        code: result.error_type ?? (result.success ? 'provider_connection_valid' : 'provider_connection_failed'),
        message: result.message,
      } satisfies ComponentTestResult;
      const aiSnapshotMatches = matchesAiSnapshot(snapshot);
      const retrievalSnapshotMatches = matchesRetrievalSnapshot(snapshot);

      if (retrievalResult && retrievalSnapshotMatches) {
        setCandidateRetrievalResult(retrievalResult);
        if (payload.retrieval_mode === 'public' && retrievalResult.valid) {
          setLoincCredentialsDirty(false);
        }
      }

      if (aiResult && aiSnapshotMatches) {
        setAiModelResult(aiResult);
      }

      if (aiSnapshotMatches && hasModelCatalogFromTest(result)) {
        setApiKeyDirty(false);
      }
      dispatchStatusRefresh();

      if (aiSnapshotMatches && payload.provider === 'ollama' && aiResult.valid) {
        if (result.resident_model != null) {
          setOllamaResidentModel(result.resident_model);
        }
      }

      if (aiSnapshotMatches && CLOUD_PROVIDERS.includes(payload.provider)) {
        if (result.available_models?.length) {
          applyCloudModelsFromTest(payload.provider, result);
        }
        return;
      }

      // OpenAI / Anthropic fallback when not using unified cloud path (should not run)
      if (config.provider === 'openai' && aiResult.valid) {
        const resp = await getOpenAIModels();
        if (requestId !== testRequestIdRef.current) return;
        setOpenaiModels(resp.models);
        setOpenaiModelsWarning(resp.warning ?? null);
        setOpenaiModelsError(resp.error ?? null);
      }
      if (config.provider === 'anthropic' && aiResult.valid) {
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
        const errorResult: ComponentTestResult = {
          valid: false,
          status: 'error',
          code: 'backend_unreachable',
          message,
        };
        setTestResult({
          success: false,
          message,
          candidate_retrieval: errorResult,
          ai_model: errorResult,
          api_key_ok: false,
          provider_ok: false,
        });
        if (matchesRetrievalSnapshot(snapshot)) {
          setCandidateRetrievalResult(errorResult);
        }
        if (matchesAiSnapshot(snapshot)) {
          setAiModelResult(errorResult);
        }
      }
    } finally {
      if (requestId === testRequestIdRef.current) {
        setTestState('done');
      }
    }
  }

  const threshold = Math.round(config.rag_auto_accept_threshold * 100);
  const lowThreshold = threshold < 85;

  function componentStatusClass(result: ComponentTestResult): string {
    if (result.status === 'not_required') return 'conn-status-info';
    if (result.status === 'valid') return 'conn-status-ok';
    return 'conn-status-err';
  }

  function componentStatusIcon(result: ComponentTestResult): string {
    if (result.status === 'not_required') return 'ℹ️';
    if (result.status === 'valid') return '✅';
    return result.status === 'invalid' ? '❌' : '⚠️';
  }

  function componentRole(result: ComponentTestResult): 'status' | 'alert' {
    return result.status === 'valid' || result.status === 'not_required' ? 'status' : 'alert';
  }

  const showOllamaLocalModels = config.provider === 'ollama' && ollamaLocalModels.length > 0;
  const localOllamaModelReady =
    config.provider !== 'ollama' || (Boolean(config.model) && ollamaLocalModels.includes(config.model));

  const ollamaLocalConnectionMessage = useMemo(() => {
    if (!aiModelResult?.valid || config.provider !== 'ollama') return null;
    const n = testResult?.available_models?.length ?? 0;
    if (n === 0) return null;
    const countText = `${n} model${n !== 1 ? 's' : ''} available`;
    if (config.model) {
      return `Connection ${config.model} OK — ${countText}.`;
    }
    return `Connection OK — ${countText}. Select a model below.`;
  }, [aiModelResult, testResult, config.model, config.provider]);

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

      {/* ── Layer 2 ─────────────────────────────────────────── */}
      <AccordionSection title="Candidate Retrieval: Finding Ontology Matches">
        <p className="section-question">
          How should the tool find candidate codes before asking the AI?
        </p>

        <div className="radio-group">
          {(
            [
              {
                value: 'public' as RetrievalMode,
                label: 'Public ontology databases',
                desc: 'uses EBI OLS4, LOINC, RxNav, NIH Clinical Tables — LOINC requires credentials',
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
                onChange={() => handleRetrievalModeChange(value)}
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
          <div className="subsection" aria-label="LOINC credentials">
            <p className="subsection-title">LOINC credentials</p>
            <p className="field-helper">
              LOINC requires an account to search its terminology API.
            </p>
            <p className="field-helper">
              <a href={LOINC_ACCOUNT_URL} target="_blank" rel="noopener noreferrer">
                Create a LOINC account
              </a>
            </p>
            <div className="field-group">
              <label className="field-label" htmlFor="loinc-username">LOINC username</label>
              <input
                id="loinc-username"
                type="text"
                className="form-input"
                value={config.loinc_username ?? ''}
                onChange={(e) => {
                  patch({ loinc_username: e.target.value || null });
                  markLoincCredentialsDirty();
                }}
              />
            </div>
            <div className="field-group">
              <label className="field-label" htmlFor="loinc-password">LOINC password</label>
              <input
                id="loinc-password"
                type="password"
                className="form-input"
                value={loincPasswordDisplay}
                onFocus={() => {
                  if (loincPasswordDisplay === MASKED_KEY_SENTINEL) setLoincPasswordDisplay('');
                }}
                onBlur={() => {
                  if (
                    configRef.current.loinc_password === MASKED_KEY_SENTINEL &&
                    !loincCredentialsDirty &&
                    !loincPasswordDisplay
                  ) {
                    setLoincPasswordDisplay(MASKED_KEY_SENTINEL);
                  }
                }}
                onChange={(e) => {
                  const val = e.target.value;
                  setLoincPasswordDisplay(val);
                  patch({ loinc_password: val || null });
                  markLoincCredentialsDirty();
                }}
              />
            </div>
            <p className="field-helper">
              Enter your credentials, then use &quot;Test connection&quot; at the bottom of the page.
            </p>
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
                onChange={(e) => {
                  patch({ sapbert_server_url: e.target.value });
                  clearCandidateRetrievalResult();
                }}
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
      <AccordionSection title="AI Model: Final Code Selection">
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
              <label className="field-label" htmlFor="ollama-base-url">Server URL</label>
              <input
                id="ollama-base-url"
                type="text"
                className="form-input"
                value={config.base_url}
                onChange={(e) => {
                  patch({ base_url: e.target.value });
                  clearAiModelResult();
                  setOllamaLocalModels([]);
                  setOllamaModelDiscoveryState('idle');
                  setOllamaModelDiscoveryError(null);
                  setOllamaResidentModel(null);
                }}
                onBlur={() => {
                  void discoverLocalOllamaModels(configRef.current.base_url, { force: true });
                }}
              />
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Change if Ollama runs on a different machine or via SSH tunnel.
              </p>
            </div>
            <div className="field-group">
              <label className="field-label" htmlFor="ollama-model">Model</label>
              {showOllamaLocalModels ? (
                <>
                  <div className="input-row">
                    <select
                      id="ollama-model"
                      className="form-input form-select"
                      value={config.model}
                      onChange={(e) => {
                        patchModel(e.target.value);
                      }}
                    >
                      <option value="">— select a model —</option>
                      {ollamaLocalModels.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </select>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() => {
                        void discoverLocalOllamaModels(config.base_url, { force: true });
                      }}
                      disabled={ollamaModelDiscoveryState === 'loading'}
                    >
                      Refresh models
                    </button>
                  </div>
                  <p className="field-helper">
                    {ollamaModelDiscoveryState === 'loading'
                      ? 'Loading available models…'
                      : 'Models are loaded from the Ollama server above.'}
                  </p>
                </>
              ) : (
                <>
                  <div className="input-row">
                    <input
                      id="ollama-model"
                      type="text"
                      className="form-input"
                      disabled
                      placeholder={
                        ollamaModelDiscoveryState === 'loading'
                          ? 'Loading available models…'
                          : ollamaModelDiscoveryState === 'error'
                            ? 'Could not load models from this Ollama server.'
                            : 'Load models from the Ollama server above'
                      }
                      value=""
                    />
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() => {
                        void discoverLocalOllamaModels(config.base_url, { force: true });
                      }}
                      disabled={ollamaModelDiscoveryState === 'loading'}
                    >
                      Refresh models
                    </button>
                  </div>
                  {ollamaModelDiscoveryError ? (
                    <p className="field-error">{ollamaModelDiscoveryError}</p>
                  ) : (
                    <p className="field-helper">
                      {ollamaModelDiscoveryState === 'loading'
                        ? 'Loading available models…'
                        : 'Models are loaded from the Ollama server above.'}
                    </p>
                  )}
                </>
              )}
              {ollamaResidentModel && (
                <p className="field-helper">
                  On the current endpoint ({config.base_url}), the model &apos;{ollamaResidentModel}&apos; is
                  currently loaded in memory — it makes sense to use this model to avoid a cold-load delay.
                </p>
              )}
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
        💾 Settings are saved to a local file on this computer. API keys and passwords are held in memory
        only and must be re-entered when the app restarts.
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
	          disabled={testState === 'loading' || !localOllamaModelReady}
	        >
          {testState === 'loading' ? '⏳ Testing…' : '🔌 Test connection'}
        </button>
        {dirty && !saving && <span className="unsaved-dot">● Unsaved changes</span>}
        {saveMsg && !dirty && <span className="save-ok">{saveMsg}</span>}
      </div>

      {/* ── Connection status ────────────────────────────────── */}
      {testState === 'loading' && (
        <div className="conn-status conn-status-loading" role="status">⏳ Testing connection…</div>
      )}
      {candidateRetrievalResult && (
        <div
          className={`conn-status ${componentStatusClass(candidateRetrievalResult)}`}
          role={componentRole(candidateRetrievalResult)}
        >
          {componentStatusIcon(candidateRetrievalResult)} <strong>Candidate Retrieval:</strong>{' '}
          {candidateRetrievalResult.message}
        </div>
      )}
      {aiModelResult && (
        <div
          className={`conn-status ${componentStatusClass(aiModelResult)}`}
          role={componentRole(aiModelResult)}
          style={{ marginTop: candidateRetrievalResult ? '6px' : undefined }}
        >
          {componentStatusIcon(aiModelResult)} <strong>AI Model:</strong>{' '}
          {config.provider === 'ollama' && ollamaLocalConnectionMessage
            ? ollamaLocalConnectionMessage
            : aiModelResult.message}
        </div>
      )}
    </div>
  );
}
