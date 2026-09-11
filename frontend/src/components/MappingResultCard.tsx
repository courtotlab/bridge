import type { SingleMappingResponse } from '../types/mapping';
import { formatRetrievalMode, RETRIEVAL_MODE_TOOLTIP } from '../utils/retrievalMode';
import InfoTooltip from './InfoTooltip';

function confidenceBadgeClass(confidence: number): string {
  if (confidence >= 0.8) return 'confidence-high';
  if (confidence >= 0.5) return 'confidence-medium';
  return 'confidence-low';
}

function pct(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

interface Props {
  result: SingleMappingResponse;
}

export default function MappingResultCard({ result }: Props) {
  return (
    <div className="card">
      <div className="result-header">
        <div>
          <p className="result-term">{result.target_term}</p>
          <p className="result-code">{result.target_code}</p>
        </div>
        <span className={`confidence-badge ${confidenceBadgeClass(result.confidence)}`}>
          {pct(result.confidence)}
        </span>
      </div>

      <div className="result-meta">
        <span>Ontology: {result.ontology}</span>
        <span>Source: {result.source_term}</span>
        <span>
          Retrieval method: <strong>{formatRetrievalMode(result.retrieval_mode)}</strong>{' '}
          <InfoTooltip label="About retrieval method" tooltip={RETRIEVAL_MODE_TOOLTIP} />
        </span>
      </div>

      {result.notes && <div className="result-notes">{result.notes}</div>}

      {result.alternatives.length > 0 && (
        <div>
          <p className="alternatives-title">Alternatives</p>
          {result.alternatives.map((alt) => (
            <div key={alt.code} className="alternative-item">
              <div className="alternative-info">
                <span className="alternative-code">{alt.code}</span>
                <span>{alt.term}</span>
                <span className="alternative-ontology">{alt.ontology}</span>
              </div>
              <span className={`confidence-badge ${confidenceBadgeClass(alt.confidence)}`}>
                {pct(alt.confidence)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
