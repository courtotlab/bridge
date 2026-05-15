import { isAxiosError } from 'axios';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getAnthropicModels, getConfig, getOllamaModels, getOpenAIModels, saveConfig, testConnection } from '../api/configApi';
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

type TestState = 'idle' | 'loading' | 'done';

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

  // Models discovered from local Ollama via /api/ollama-models
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const ollamaDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Models returned by Ollama Cloud /api/tags (from testConnection response)
  const [cloudModels, setCloudModels] = useState<string[]>([]);

  // Models fetched from OpenAI / Anthropic after a successful connection test
  const [openaiModels, setOpenaiModels] = useState<string[]>([]);
  const [openaiModelsWarning, setOpenaiModelsWarning] = useState<string | null>(null);
  const [openaiModelsError, setOpenaiModelsError] = useState<string | null>(null);

  const [anthropicModels, setAnthropicModels] = useState<string[]>([]);
  const [anthropicModelsWarning, setAnthropicModelsWarning] = useState<string | null>(null);
  const [anthropicModelsError, setAnthropicModelsError] = useState<string | null>(null);

  // Load config on mount
  useEffect(() => {
    getConfig()
      .then((c) => {
        setConfig(c);
        if (c.api_key && (c.provider === 'openai' || c.provider === 'anthropic')) {
          setApiKeyDisplay(MASKED_KEY_SENTINEL);
        }
      })
      .catch(() => {});
  }, []);

  // Fetch Ollama Local models when base_url changes (debounced 500 ms)
  const fetchOllamaModels = useCallback(() => {
    if (ollamaDebounceRef.current) clearTimeout(ollamaDebounceRef.current);
    ollamaDebounceRef.current = setTimeout(() => {
      if (config.provider === 'ollama') {
        getOllamaModels().then(setOllamaModels).catch(() => setOllamaModels([]));
      }
    }, 500);
  }, [config.provider]);

  useEffect(() => {
    if (config.provider === 'ollama') {
      fetchOllamaModels();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.base_url, config.provider]);

  function patch(updates: Partial<AppConfig>) {
    setConfig((prev) => ({ ...prev, ...updates }));
    setDirty(true);
    setSaveMsg('');
  }

  function handleProviderChange(provider: Provider) {
    setTestResult(null);
    setTestState('idle');
    setCloudModels([]);
    setOpenaiModels([]);
    setOpenaiModelsWarning(null);
    setOpenaiModelsError(null);
    setAnthropicModels([]);
    setAnthropicModelsWarning(null);
    setAnthropicModelsError(null);
    setApiKeyDisplay('');
    patch({ provider, model: DEFAULT_MODEL[provider] });
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg('');
    try {
      await saveConfig(config);
      setDirty(false);
      setSaveMsg('Settings saved');
      // Invalidate model dropdowns so the user must re-test after saving
      setOpenaiModels([]);
      setOpenaiModelsWarning(null);
      setOpenaiModelsError(null);
      setAnthropicModels([]);
      setAnthropicModelsWarning(null);
      setAnthropicModelsError(null);
      window.dispatchEvent(new Event('bridge:status-refresh'));
    } catch {
      setSaveMsg('Failed to save settings.');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTestState('loading');
    setTestResult(null);
    console.log(
      '[handleTest] provider=', config.provider,
      '| model=', config.model || '(empty)',
      '| api_key=', config.api_key ? 'set' : 'empty',
    );
    try {
      // Always forward current in-page config so unsaved api_key/model is used
      const result = await testConnection(config);
      setTestResult(result);

      if (result.success) {
        window.dispatchEvent(new Event('bridge:status-refresh'));
      }

      // Populate cloud model dropdown from /api/tags response
      if (config.provider === 'ollama_cloud' && result.available_models?.length) {
        console.log('[handleTest] cloudModels populated:', result.available_models);
        setCloudModels(result.available_models);
        // Auto-select first model only when none is chosen yet
        if (!config.model) {
          patch({ model: result.available_models[0] });
        }
      }

      // Populate OpenAI / Anthropic model dropdowns after a successful test
      if (result.success && config.provider === 'openai') {
        const resp = await getOpenAIModels();
        setOpenaiModels(resp.models);
        setOpenaiModelsWarning(resp.warning ?? null);
        setOpenaiModelsError(resp.error ?? null);
        if (!resp.error && resp.models.length > 0 && !resp.models.includes(config.model)) {
          patch({ model: resp.models[0] });
        }
      }

      if (result.success && config.provider === 'anthropic') {
        const resp = await getAnthropicModels();
        setAnthropicModels(resp.models);
        setAnthropicModelsWarning(resp.warning ?? null);
        setAnthropicModelsError(resp.error ?? null);
        if (!resp.error && resp.models.length > 0 && !resp.models.includes(config.model)) {
          patch({ model: resp.models[0] });
        }
      }
    } catch (err) {
      const message =
        isAxiosError(err) && !err.response
          ? 'Could not reach the backend — is the API server running?'
          : 'Test failed. Please check your settings.';
      setTestResult({ success: false, message });
    } finally {
      setTestState('done');
    }
  }

  const threshold = Math.round(config.rag_auto_accept_threshold * 100);
  const lowThreshold = threshold < 85;

  // Derive connection status CSS class and display text
  const isReachabilityOnly =
    testResult?.success && testResult?.validation_level === 'reachability';

  const connClass =
    testState === 'loading'
      ? 'conn-status-loading'
      : !testResult?.success
        ? 'conn-status-err'
        : isReachabilityOnly
          ? 'conn-status-info'
          : 'conn-status-ok';

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
              <label className="field-label">Model</label>
              {ollamaModels.length > 0 ? (
                <select
                  className="form-input form-select"
                  value={config.model}
                  onChange={(e) => patch({ model: e.target.value })}
                >
                  {ollamaModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  className="form-input"
                  value={config.model}
                  onChange={(e) => patch({ model: e.target.value })}
                />
              )}
              <p className="field-helper-sm">(detected from your local Ollama)</p>
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Can&apos;t see your model? Run <code>ollama pull &lt;name&gt;</code>
              </p>
            </div>
            <div className="field-group">
              <label className="field-label">Server URL</label>
              <input
                type="text"
                className="form-input"
                value={config.base_url}
                onChange={(e) => patch({ base_url: e.target.value })}
              />
              <p className="field-helper">
                <span className="info-icon">ℹ️</span>{' '}
                Change only if Ollama runs on a different machine.
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
                onChange={(e) => patch({ api_key: e.target.value || null })}
              />
            </div>
            <div className="field-group">
              <label className="field-label">Model</label>
              {cloudModels.length > 0 ? (
                <select
                  className="form-input form-select"
                  value={config.model}
                  onChange={(e) => patch({ model: e.target.value })}
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
                    onChange={(e) => patch({ model: e.target.value })}
                  />
                  <p className="field-error">{openaiModelsError}</p>
                </>
              ) : openaiModels.length > 0 ? (
                <>
                  <select
                    className="form-input form-select"
                    value={config.model}
                    onChange={(e) => patch({ model: e.target.value })}
                  >
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
                    onChange={(e) => patch({ model: e.target.value })}
                  />
                  <p className="field-error">{anthropicModelsError}</p>
                </>
              ) : anthropicModels.length > 0 ? (
                <>
                  <select
                    className="form-input form-select"
                    value={config.model}
                    onChange={(e) => patch({ model: e.target.value })}
                  >
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
      {testState !== 'idle' && (
        <div className={`conn-status ${connClass}`}>
          {testState === 'loading' && '⏳ Testing connection…'}
          {testState === 'done' && testResult?.success && isReachabilityOnly &&
            `ℹ️ ${testResult.message}`}
          {testState === 'done' && testResult?.success && !isReachabilityOnly &&
            `✅ ${testResult.message}`}
          {testState === 'done' && !testResult?.success &&
            `❌ ${testResult?.message}`}
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
