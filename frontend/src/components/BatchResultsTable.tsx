import { Fragment } from 'react';
import type { AlternativeResult, BatchRowResult } from '../types/mapping';
import { getMappingExplanation } from '../utils/mappingDetails';
import MappingDetailsTooltip from './MappingDetailsTooltip';

export function batchConfidenceTier(confidence: number): 'high' | 'med' | 'low' {
  if (confidence >= 0.85) return 'high';
  if (confidence >= 0.5) return 'med';
  return 'low';
}

function batchConfidenceLabel(confidence: number): string {
  if (confidence >= 0.85) return 'High';
  if (confidence >= 0.5) return 'Med';
  return 'Low';
}

export function isUnmappedCode(code: string): boolean {
  return code.toUpperCase().includes('UNMAPPED');
}

function isTooltipEligibleUnmapped(row: BatchRowResult): boolean {
  return isUnmappedCode(row.suggested_code)
    && row.suggested_term.trim().toUpperCase() === 'UNMAPPED'
    && row.confidence <= 0
    && Boolean(getMappingExplanation({ notes: row.notes }));
}

export function BatchConfidenceBadge({ confidence }: { confidence: number }) {
  const tier = batchConfidenceTier(confidence);
  return (
    <span className={`batch-conf-badge batch-conf-badge--${tier}`}>
      {confidence >= 0.85 ? '✅' : confidence >= 0.5 ? '⚠️' : '❌'}{' '}
      {Math.round(confidence * 100)}% {batchConfidenceLabel(confidence)}
    </span>
  );
}

export function DecisionChip({ decision }: { decision: string }) {
  return (
    <span className={`batch-decision-chip batch-decision-chip--${decision}`}>
      {decision.charAt(0).toUpperCase() + decision.slice(1)}
    </span>
  );
}

export function filterBatchRows(
  rows: BatchRowResult[],
  getDecision: (row: BatchRowResult) => 'accepted' | 'rejected' | 'pending',
  filterStatus: string,
  searchQuery: string,
): BatchRowResult[] {
  return rows.filter((row) => {
    const decision = getDecision(row);
    const matchesFilter = filterStatus === 'all' || decision === filterStatus;
    const query = searchQuery.toLowerCase();
    const matchesSearch = !query
      || row.field_name.toLowerCase().includes(query)
      || (row.label ?? '').toLowerCase().includes(query)
      || row.suggested_code.toLowerCase().includes(query)
      || row.suggested_term.toLowerCase().includes(query);
    return matchesFilter && matchesSearch;
  });
}

interface BatchResultsTableProps {
  rows: BatchRowResult[];
  expandedRows: Set<number>;
  filterStatus: string;
  searchQuery: string;
  autoAcceptThreshold?: number;
  readOnly?: boolean;
  isRunning?: boolean;
  getDecision?: (row: BatchRowResult) => 'accepted' | 'rejected' | 'pending';
  onFilterStatusChange: (value: string) => void;
  onSearchQueryChange: (value: string) => void;
  onToggleExpand: (rowIndex: number) => void;
  onToggleDecision?: (row: BatchRowResult, decision: 'accepted' | 'rejected') => void;
  onBulkDecision?: (type: 'accept_high' | 'reject_unmapped' | 'reset') => void;
  onPromoteAlternative?: (row: BatchRowResult, alt: AlternativeResult) => void;
}

export default function BatchResultsTable({
  rows,
  expandedRows,
  filterStatus,
  searchQuery,
  autoAcceptThreshold = 85,
  readOnly = false,
  isRunning = false,
  getDecision = (row) => row.decision,
  onFilterStatusChange,
  onSearchQueryChange,
  onToggleExpand,
  onToggleDecision,
  onBulkDecision,
  onPromoteAlternative,
}: BatchResultsTableProps) {
  const filteredRows = filterBatchRows(rows, getDecision, filterStatus, searchQuery);
  const showMutatingControls = !readOnly;
  const showAlternativesColumn = readOnly && rows.some((row) => row.alternatives.length > 0);
  const colSpan = showMutatingControls || showAlternativesColumn ? 6 : 5;

  return (
    <>
      <div className="batch-bulk-toolbar">
        {showMutatingControls && onBulkDecision && (
          <>
            <button
              className="batch-btn-bulk"
              onClick={() => onBulkDecision('accept_high')}
            >
              Accept all High (≥{autoAcceptThreshold}%)
            </button>
            <button
              className="batch-btn-bulk"
              onClick={() => onBulkDecision('reject_unmapped')}
            >
              Reject all Unmapped
            </button>
            <button
              className="batch-btn-bulk"
              onClick={() => onBulkDecision('reset')}
            >
              Reset all
            </button>
          </>
        )}
        <select
          className="batch-filter-select"
          value={filterStatus}
          onChange={(e) => onFilterStatusChange(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="accepted">Accepted</option>
          <option value="rejected">Rejected</option>
          <option value="pending">Pending</option>
        </select>
        <input
          type="text"
          className="batch-search-input"
          placeholder="Search fields…"
          value={searchQuery}
          onChange={(e) => onSearchQueryChange(e.target.value)}
        />
      </div>

      <div className="batch-table-scroll">
        <table className="batch-table">
          <thead>
            <tr>
              <th>Field name</th>
              <th>Label</th>
              <th>Suggested code</th>
              <th>Confidence</th>
              <th>Decision</th>
              {showMutatingControls && <th>Actions</th>}
              {showAlternativesColumn && <th>Alternatives</th>}
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => {
              const decision = getDecision(row);
              const isExpanded = expandedRows.has(row.row_index);
              const showUnmappedTooltip = isTooltipEligibleUnmapped(row);
              return (
                <Fragment key={`batch-row-group-${row.row_index}`}>
                  <tr key={`row-${row.row_index}`} className="batch-table-row">
                    <td className="batch-field-name">
                      {row.field_name}
                    </td>
                    <td className="batch-label-cell">
                      {row.label ?? '—'}
                    </td>
                    <td>
                      {isUnmappedCode(row.suggested_code) ? (
                        <span className="batch-code-main">
                          <span className="batch-unmapped-code">UNMAPPED</span>
                          {showUnmappedTooltip && (
                            <MappingDetailsTooltip
                              code="UNMAPPED"
                              explanationLabel="Why unmapped"
                              details={{
                                notes: row.notes,
                                retrievalMode: row.retrieval_mode,
                                configuredProvider: row.configured_provider,
                                configuredModel: row.configured_model,
                              }}
                            />
                          )}
                        </span>
                      ) : (
                        <>
                          <div className="batch-code-main">
                            {row.suggested_url ? (
                              <a
                                href={row.suggested_url}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {row.suggested_code}
                              </a>
                            ) : (
                              <span>{row.suggested_code}</span>
                            )}
                            <MappingDetailsTooltip
                              code={row.suggested_code}
                              details={{
                                notes: row.notes,
                                retrievalMode: row.retrieval_mode,
                                configuredProvider: row.configured_provider,
                                configuredModel: row.configured_model,
                              }}
                            />
                          </div>
                          <div className="batch-code-term">{row.suggested_term}</div>
                        </>
                      )}
                    </td>
                    <td>
                      <BatchConfidenceBadge confidence={row.confidence} />
                    </td>
                    <td>
                      <DecisionChip decision={decision} />
                    </td>
                    {showMutatingControls && (
                      <td>
                        <div className="batch-actions-cell">
                          <button
                            className={`batch-action-btn${decision === 'accepted' ? ' batch-action-btn--active-accept' : ''}`}
                            title="Accept"
                            onClick={() => onToggleDecision?.(row, 'accepted')}
                          >
                            👍
                          </button>
                          <button
                            className={`batch-action-btn${decision === 'rejected' ? ' batch-action-btn--active-reject' : ''}`}
                            title="Reject"
                            onClick={() => onToggleDecision?.(row, 'rejected')}
                          >
                            👎
                          </button>
                          {row.alternatives.length > 0 && (
                            <button
                              className="batch-action-btn"
                              title={isExpanded ? 'Collapse' : 'Show alternatives'}
                              onClick={() => onToggleExpand(row.row_index)}
                            >
                              {isExpanded ? '▲' : '▼'}
                            </button>
                          )}
                        </div>
                      </td>
                    )}
                    {showAlternativesColumn && (
                      <td className="batch-readonly-expand-cell">
                        {row.alternatives.length > 0 && (
                          <button
                            className="batch-action-btn"
                            title={isExpanded ? 'Collapse' : 'Show alternatives'}
                            onClick={() => onToggleExpand(row.row_index)}
                          >
                            {isExpanded ? '▲' : '▼'}
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                  {isExpanded && row.alternatives.length > 0 && (
                    <tr key={`alt-${row.row_index}`} className="batch-alt-row">
                      <td colSpan={colSpan}>
                        <div className="batch-alt-list">
                          {row.alternatives.map((alt) => (
                            <div key={`${alt.ontology}:${alt.code}`} className="batch-alt-item">
                              <span className="batch-alt-code">
                                {alt.url ? (
                                  <a
                                    href={alt.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
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
                                      retrievalMode: row.retrieval_mode,
                                      configuredProvider: row.configured_provider,
                                      configuredModel: row.configured_model,
                                    }}
                                  />
                                )}
                              </span>
                              <span>{alt.term}</span>
                              <BatchConfidenceBadge confidence={alt.confidence} />
                              {showMutatingControls && (
                                <button
                                  type="button"
                                  className="batch-alt-use-btn"
                                  title="Use as suggested mapping"
                                  aria-label={`Use ${alt.code} as the suggested mapping`}
                                  onClick={() => onPromoteAlternative?.(row, alt)}
                                >
                                  Use
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {filteredRows.length === 0 && (
              <tr>
                <td colSpan={colSpan} style={{ textAlign: 'center', color: '#9ca3af', padding: '20px 0' }}>
                  {isRunning ? 'Waiting for results…' : 'No rows match filters.'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
