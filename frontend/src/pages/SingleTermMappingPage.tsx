import { isAxiosError } from 'axios';
import { useState } from 'react';
import { mapSingleTerm } from '../api/mappingApi';
import MappingResultCard from '../components/MappingResultCard';
import type { SingleMappingResponse } from '../types/mapping';

const ENTITY_TYPES = [
  { value: '', label: 'Select entity type (optional)' },
  { value: 'phenotype', label: 'Phenotype' },
  { value: 'disease', label: 'Disease' },
  { value: 'measurement', label: 'Measurement' },
  { value: 'medication', label: 'Medication' },
];

export default function SingleTermMappingPage() {
  const [sourceTerm, setSourceTerm] = useState('');
  const [sourceLabel, setSourceLabel] = useState('');
  const [entityType, setEntityType] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SingleMappingResponse | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);

    try {
      const response = await mapSingleTerm({
        source_term: sourceTerm.trim(),
        ...(sourceLabel.trim() && { source_label: sourceLabel.trim() }),
        ...(entityType && { entity_type: entityType }),
      });
      setResult(response);
    } catch (err) {
      if (isAxiosError(err) && !err.response) {
        setError(
          'Could not reach the backend. Make sure the API server is running at localhost:8000.',
        );
      } else {
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="card">
        <h2 className="card-title">Map a Term</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label" htmlFor="source-term">
              Source term <span className="required-mark">*</span>
            </label>
            <input
              id="source-term"
              className="form-input"
              type="text"
              placeholder="e.g. cough"
              value={sourceTerm}
              onChange={(e) => setSourceTerm(e.target.value)}
              required
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="source-label">
              Source label <span className="optional-mark">(optional)</span>
            </label>
            <input
              id="source-label"
              className="form-input"
              type="text"
              placeholder="e.g. cough symptom"
              value={sourceLabel}
              onChange={(e) => setSourceLabel(e.target.value)}
            />
          </div>

          <div className="form-group">
            <label className="form-label" htmlFor="entity-type">
              Entity type <span className="optional-mark">(optional)</span>
            </label>
            <select
              id="entity-type"
              className="form-select"
              value={entityType}
              onChange={(e) => setEntityType(e.target.value)}
            >
              {ENTITY_TYPES.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <button
            className="btn-primary"
            type="submit"
            disabled={loading || !sourceTerm.trim()}
          >
            {loading ? 'Mapping…' : 'Map term'}
          </button>
        </form>
      </div>

      {loading && <p className="status-loading">Mapping term…</p>}
      {error && <div className="status-error">{error}</div>}
      {result && <MappingResultCard result={result} />}
    </div>
  );
}
