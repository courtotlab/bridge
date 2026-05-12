export default function SettingsPanel() {
  return (
    <div>
      <p className="settings-title">Settings</p>

      <div className="settings-group">
        <label className="settings-label" htmlFor="provider">
          Provider
        </label>
        <select id="provider" className="form-select" disabled>
          <option>Anthropic</option>
          <option>OpenAI</option>
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
          defaultValue="claude-sonnet-4-6"
          disabled
        />
      </div>

      <div className="settings-group">
        <div className="toggle-row">
          <span className="toggle-label">
            Use ontology search to ground AI suggestions
          </span>
          <label className="toggle">
            <input type="checkbox" defaultChecked disabled />
            <span className="toggle-slider" />
          </label>
        </div>
      </div>

      <p className="settings-note">
        Settings are not functional yet. Configuration will be wired in a future update.
      </p>
    </div>
  );
}
