import { isAxiosError } from 'axios';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getConfig, getOllamaModels, saveConfig, testConnection } from '../api/configApi';
import AccordionSection from '../components/AccordionSection';
import type { AppConfig, ConnectionTestResponse, Provider, RetrievalMode } from '../types/config';

const DEFAULT_MODEL: Record<Provider, string> = {
  ollama: 'llama3.2',
  ollama_cloud: 'llama3.2',
  openai: 'gpt-4o',
  anthropic: 'claude-sonnet-4-20250514',
};

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

  const [testState, setTestState] = useState<TestState>('idle');
  const [testResult, setTestResult] = useState<ConnectionTestResponse | null>(null);
  const [testTime, setTestTime] = useState<number>(0);

  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const ollamaDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load config on mount
  useEffect(() => {
    getConfig()
      .then((c) => setConfig(c))
      .catch(() => {});
  }, []);

  // Fetch Ollama models when base_url changes (debounced 500 ms)
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
    patch({ provider, model: DEFAULT_MODEL[provider] });
  }

  async function handleSave() {
    setSaving(true);
    setSaveMsg('');
    try {
      await saveConfig(config);
      setDirty(false);
      setSaveMsg('Settings saved');
    } catch {
      setSaveMsg('Failed to save settings.');
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTestState('loading');
    setTestResult(null);
    const start = Date.now();
    try {
      const result = await testConnection();
      setTestResult(result);
      setTestTime(Math.round((Date.now() - start) / 1000));
    } catch (err) {
      const message =
        isAxiosError(err) && !err.response
          ? 'Could not reach the backend — is the API server running?'
          : 'Test failed. Please check your settings.';
      setTestResult({ success: false, message });
      setTestTime(0);
    } finally {
      setTestState('done');
    }
  }

  const threshold = Math.round(config.rag_auto_accept_threshold * 100);
  const lowThreshold = threshold < 85;

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

        {config.provider === 'ollama' ? (
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
        ) : (
          <div className="subsection">
            <div className="field-group">
              <label className="field-label">Model</label>
              <input
                type="text"
                className="form-input"
                value={config.model}
                onChange={(e) => patch({ model: e.target.value })}
              />
            </div>
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
        <div className={`conn-status ${testState === 'loading' ? 'conn-status-loading' : testResult?.success ? 'conn-status-ok' : 'conn-status-err'}`}>
          {testState === 'loading' && '⏳ Testing connection…'}
          {testState === 'done' && testResult?.success &&
            `✅ Connection OK — ${config.model} is ready. (tested ${testTime} s ago)`}
          {testState === 'done' && !testResult?.success &&
            `❌ ${testResult?.message}`}
        </div>
      )}
    </div>
  );
}
