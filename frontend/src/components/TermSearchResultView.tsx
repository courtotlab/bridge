import { getOntologyDisplayName } from '../constants/ontologies';
import type { AlternativeResult, SingleMappingResponse } from '../types/mapping';
import { getMappingExplanation } from '../utils/mappingDetails';
import { formatRetrievalMode, RETRIEVAL_MODE_TOOLTIP } from '../utils/retrievalMode';
import InfoTooltip from './InfoTooltip';
import MappingDetailsTooltip from './MappingDetailsTooltip';

type ConfidenceTier = 'high' | 'med' | 'low';

function getConfidenceTier(confidence: number): ConfidenceTier {
  if (confidence >= 0.8) return 'high';
  if (confidence >= 0.5) return 'med';
  return 'low';
}

function getConfidenceLabel(confidence: number): string {
  if (confidence >= 0.8) return 'High';
  if (confidence >= 0.5) return 'Med';
  return 'Low';
}

export function ConfidenceBadge({ confidence }: { confidence: number }) {
  const tier = getConfidenceTier(confidence);
  const label = getConfidenceLabel(confidence);
  const pct = Math.round(confidence * 100);
  return (
    <span className={`confidence-badge confidence-badge--${tier}`}>
      ● {pct}% {label}
    </span>
  );
}

function RetrievalModeWithTooltip({ mode }: { mode?: string | null }) {
  return (
    <span className="logic-type-wrap">
      Retrieval method: <strong>{formatRetrievalMode(mode)}</strong>{' '}
      <InfoTooltip label="About retrieval method" tooltip={RETRIEVAL_MODE_TOOLTIP} />
    </span>
  );
}

interface TermSearchResultViewProps {
  bestMatch: SingleMappingResponse;
  alternatives: AlternativeResult[];
  copied?: boolean;
  readOnly?: boolean;
  sessionDate?: string;
  /**
   * Renders the no-confident-match presentation instead of a best-match
   * card. `bestMatch` is UNKNOWN:UNMAPPED/UNMAPPED in this case — it isn't a
   * real ontology mapping, so its code/term/confidence are never shown, and
   * actions that treat it as a selected mapping (copy/download) are hidden.
   * Metadata (ontology, retrieval method, provider, model) and the mapper's
   * own explanation are still shown, and alternatives still render/promote
   * normally underneath.
   */
  noMatch?: boolean;
  /**
   * The ontology the user actually requested (e.g. "Human Phenotype
   * Ontology"), used only in noMatch mode — bestMatch.ontology is blank/
   * UNKNOWN for an UNMAPPED result, so it can't be used for the headline.
   */
  requestedOntologyLabel?: string;
  onCopy?: () => void;
  onDownloadCsv?: () => void;
  onPromote?: (alt: AlternativeResult) => void;
}

export default function TermSearchResultView({
  bestMatch,
  alternatives,
  copied = false,
  readOnly = false,
  noMatch = false,
  requestedOntologyLabel,
  onCopy,
  onDownloadCsv,
  onPromote,
}: TermSearchResultViewProps) {
  const explanation = getMappingExplanation(bestMatch);
  const ontologyLabel = noMatch ? requestedOntologyLabel : getOntologyDisplayName(bestMatch.ontology);

  return (
    <div className="search-results">
      <div className={`card result-card${noMatch ? ' result-card--no-match' : ''}`}>
        <div className="result-card-header">
          <span className="result-card-title-label">
            {noMatch ? 'No confident match' : 'Best match'}
          </span>
          {noMatch ? (
            <span className="status-badge status-badge--unmapped">UNMAPPED</span>
          ) : (
            <ConfidenceBadge confidence={bestMatch.confidence} />
          )}
        </div>

        {noMatch ? (
          <p className="result-code-term">
            {ontologyLabel ? `No suitable ${ontologyLabel} mapping was found` : 'No confident mapping was found'}
          </p>
        ) : (
          <p className="result-code-term">
            {bestMatch.target_url ? (
              <a
                href={bestMatch.target_url}
                target="_blank"
                rel="noopener noreferrer"
                className="result-code-link"
              >
                {bestMatch.target_code}
              </a>
            ) : (
              <span>{bestMatch.target_code}</span>
            )}
            {' · '}{bestMatch.target_term}
            <MappingDetailsTooltip
              code={bestMatch.target_code}
              details={{
                notes: bestMatch.notes,
                explanation: bestMatch.explanation,
                configuredProvider: bestMatch.configured_provider,
                configuredModel: bestMatch.configured_model,
              }}
            />
          </p>
        )}

        {ontologyLabel && (
          <p className="result-meta-line">
            Ontology: {ontologyLabel}
          </p>
        )}
        <p className="result-meta-line">
          <RetrievalModeWithTooltip mode={bestMatch.retrieval_mode} />
        </p>
        {bestMatch.configured_provider && (
          <p className="result-meta-line">
            AI Provider: <strong>{bestMatch.configured_provider}</strong>{' '}
            <InfoTooltip
              label="About AI provider"
              tooltip="The AI provider configured in Bridge settings"
            />
          </p>
        )}
        {bestMatch.configured_model && (
          <p className="result-meta-line">
            Model: <strong>{bestMatch.configured_model}</strong>{' '}
            <InfoTooltip
              label="About model"
              tooltip="The model configured in Bridge settings"
            />
          </p>
        )}

        {explanation && <blockquote className="result-notes">"{explanation}"</blockquote>}

        {!noMatch && (
          <div className="result-actions">
            {onCopy && (
              <button className="btn-outline" onClick={onCopy}>
                {copied ? '✅ Copied!' : `📋 Copy code: ${bestMatch.target_code}`}
              </button>
            )}
            {onDownloadCsv && (
              <button className="btn-outline" onClick={onDownloadCsv}>
                💾 Download as CSV
              </button>
            )}
          </div>
        )}
      </div>

      {alternatives.length > 0 && (
        <div className="card alternatives-card">
          <h2 className="alternatives-heading">Other suggestions</h2>
          <table className="alternatives-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>Term</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {alternatives.map((alt) => {
                const interactive = !readOnly && Boolean(onPromote);
                return (
                  <tr
                    key={`${alt.ontology}:${alt.code}`}
                    className={`alternatives-row${readOnly ? ' alternatives-row--readonly' : ''}`}
                    onClick={interactive ? () => onPromote?.(alt) : undefined}
                    tabIndex={interactive ? 0 : undefined}
                    onKeyDown={interactive ? (e) => e.key === 'Enter' && onPromote?.(alt) : undefined}
                    role={interactive ? 'button' : undefined}
                    aria-label={interactive ? `Promote ${alt.code} to best match` : undefined}
                  >
                    <td className="alt-code">
                      {alt.url ? (
                        <a
                          href={alt.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {alt.code}
                        </a>
                      ) : (
                        <span>{alt.code}</span>
                      )}
                      {(alt.explanation || alt.source) && (
                        <MappingDetailsTooltip
                          code={alt.code}
                          details={{
                            explanation: alt.explanation,
                            configuredProvider: bestMatch.configured_provider,
                            configuredModel: bestMatch.configured_model,
                          }}
                        />
                      )}
                    </td>
                    <td>{alt.term}</td>
                    <td><ConfidenceBadge confidence={alt.confidence} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!readOnly && onPromote && (
            <p className="field-helper-sm" style={{ marginTop: 8 }}>
              Click any row to promote it to the best-match card.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
