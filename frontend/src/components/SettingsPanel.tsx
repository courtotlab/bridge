import { isAxiosError } from 'axios';
import { useState } from 'react';
import { testConfig } from '../api/configApi';
import type { ConfigTestResponse } from '../types/config';

const PROVIDERS = ['Ollama', 'OpenAI', 'Anthropic', 'GitHub Models'];
const ONTOLOGIES = ['HPO', 'MONDO', 'NCIT', 'LOINC'];

const DEFAULT_MODEL: Record<string, string> = {
  Ollama: 'llama3.2',
  OpenAI: 'gpt-4o',
  Anthropic: 'claude-sonnet-4-6',
  'GitHub Models': 'gpt-4o',
};

interface Settings {
  provider: string;
  model: string;
  baseUrl: string;
  useRetrievalGrounding: boolean;
  selectedOntologies: string[];
  confidenceThreshold: number;
}

export default function SettingsPanel() {
  const [settings, setSettings] = useState<Settings>({
    provider: 'Anthropic',
    model: 'claude-sonnet-4-6',
    baseUrl: '',
    useRetrievalGrounding: true,
    selectedOntologies: ['HPO', 'MONDO'],
    confidenceThreshold: 0.7,
  });
  const [testing, setTesting] = useState(false);
  const [feedback, setFeedback] = useState<ConfigTestResponse | null>(null);

  function update(patch: Partial<Settings>) {
    setSettings((prev) => ({ ...prev, ...patch }));
    setFeedback(null);
  }

  function handleProviderChange(provider: string) {
    update({ provider, model: DEFAULT_MODEL[provider] ?? '' });
  }

  function toggleOntology(ontology: string) {
    const next = settings.selectedOntologies.includes(ontology)
      ? settings.selectedOntologies.filter((o) => o !== ontology)
      : [...settings.selectedOntologies, ontology];
    update({ selectedOntologies: next });
  }

  async function handleTestConnection() {
    setTesting(true);
    setFeedback(null);
    try {
      const result = await testConfig({
        provider: settings.provider,
        model: settings.model,
        ...(settings.baseUrl.trim() && { base_url: settings.baseUrl.trim() }),
        use_retrieval_grounding: settings.useRetrievalGrounding,
        selected_ontologies: settings.selectedOntologies,
        confidence_threshold: settings.confidenceThreshold,
      });
      setFeedback(result);
    } catch (err) {
      const message =
        isAxiosError(err) && !err.response
          ? 'Could not reach the backend. Is the API server running?'
          : 'Test failed. Please check your settings.';
      setFeedback({ success: false, message });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div>
      <p className="settings-title">Settings</p>

      <div className="settings-group">
        <label className="settings-label" htmlFor="provider">
          Provider
        </label>
        <select
          id="provider"
          className="form-select"
          value={settings.provider}
          onChange={(e) => handleProviderChange(e.target.value)}
        >
          {PROVIDERS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div className="settings-group">
        <label className="settings-label" htmlFor="model">
          Model
        </label>
        <input
          id="model"
          className="form-input"
          type="text"
          value={settings.model}
          onChange={(e) => update({ model: e.target.value })}
        />
      </div>

      <div className="settings-group">
        <label className="settings-label" htmlFor="base-url">
          Base URL <span className="optional-mark">(optional)</span>
        </label>
        <input
          id="base-url"
          className="form-input"
          type="text"
          placeholder="e.g. http://localhost:11434"
          value={settings.baseUrl}
          onChange={(e) => update({ baseUrl: e.target.value })}
        />
      </div>

      <hr className="settings-divider" />

      <div className="settings-group">
        <div className="toggle-row">
          <span className="toggle-label">
            Use ontology search to ground AI suggestions
          </span>
          <label className="toggle">
            <input
              type="checkbox"
              checked={settings.useRetrievalGrounding}
              onChange={(e) => update({ useRetrievalGrounding: e.target.checked })}
            />
            <span className="toggle-slider" />
          </label>
        </div>
      </div>

      <div className="settings-group">
        <p className="settings-label">Ontologies to search</p>
        <div className="checkbox-group">
          {ONTOLOGIES.map((ont) => (
            <label key={ont} className="checkbox-item">
              <input
                type="checkbox"
                checked={settings.selectedOntologies.includes(ont)}
                onChange={() => toggleOntology(ont)}
              />
              {ont}
            </label>
          ))}
        </div>
      </div>

      <div className="settings-group">
        <p className="settings-label">
          Minimum confidence — {Math.round(settings.confidenceThreshold * 100)}%
        </p>
        <input
          type="range"
          className="range-slider"
          min="0"
          max="1"
          step="0.05"
          value={settings.confidenceThreshold}
          onChange={(e) => update({ confidenceThreshold: parseFloat(e.target.value) })}
        />
      </div>

      <hr className="settings-divider" />

      <button
        className="btn-outline"
        onClick={handleTestConnection}
        disabled={testing || !settings.model.trim()}
      >
        {testing ? 'Testing…' : 'Test connection'}
      </button>

      {feedback && (
        <div className={`settings-feedback ${feedback.success ? 'settings-feedback-ok' : 'settings-feedback-err'}`}>
          {feedback.message}
        </div>
      )}
    </div>
  );
}
