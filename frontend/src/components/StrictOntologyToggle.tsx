interface StrictOntologyToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export default function StrictOntologyToggle({
  checked,
  onChange,
  disabled = false,
}: StrictOntologyToggleProps) {
  return (
    <div className="strict-ontology-toggle">
      <label className="strict-ontology-row" style={{ cursor: disabled ? 'default' : 'pointer' }}>
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          disabled={disabled}
          style={{ width: 15, height: 15, accentColor: '#1d4ed8', cursor: disabled ? 'default' : 'pointer' }}
        />
        Require codes from selected ontology only
      </label>
      <p className="strict-ontology-desc">
        Only return codes that belong directly to the selected ontology. For EFO, this
        excludes imported HPO, MONDO, and other ontology codes.
      </p>
    </div>
  );
}
