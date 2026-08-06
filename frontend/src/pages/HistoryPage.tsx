import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { deleteSession, exportUrl, getSession, getSessions } from '../api/historyApi';
import BatchResultsTable from '../components/BatchResultsTable';
import TermSearchResultView from '../components/TermSearchResultView';
import ValidationResultsTable from '../components/ValidationResultsTable';
import type {
  BatchMapHistoryDetails,
  HistoryDetails,
  HistoryConfiguration,
  InputSummary,
  SessionStatus,
  SessionSummary,
  SessionType,
  TermSearchHistoryDetails,
  ValidationHistoryDetails,
} from '../types/session';
import {
  downloadBatchRowsCsv,
  downloadTermMappingCsv,
  downloadValidationCsv,
} from '../utils/csvExport';
import { formatRetrievalMode } from '../utils/retrievalMode';
import './BatchPage.css';
import './HistoryPage.css';
import './ValidatorPage.css';

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function inputSummaryLabel(type: SessionType, summary: InputSummary): string {
  if (type === 'term_search') return summary.term ?? '—';
  if (type === 'validation') {
    const codes = summary.codes ?? [];
    if (codes.length === 0) return '—';
    const preview = codes.slice(0, 3).join(', ');
    return codes.length > 3 ? `${preview} +${codes.length - 3} more` : preview;
  }
  // batch_map
  return summary.filename ?? '—';
}

export function formatOntologySummary(summary: InputSummary): string {
  if (summary.target_ontologies && summary.target_ontologies.length > 0) {
    return summary.target_ontologies.join(', ');
  }
  if (summary.target_ontology) return summary.target_ontology;
  return 'Automatic';
}

function formatValue(value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (Array.isArray(value)) return value.length > 0 ? value.join(', ') : null;
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  if (typeof value === 'number') return String(value);
  return String(value);
}

function formatPercent(value: unknown): string | null {
  if (typeof value !== 'number') return null;
  return `${Math.round(value * 100)}%`;
}

function addRow(rows: Array<[string, string]>, label: string, value: unknown): void {
  const formatted = formatValue(value);
  if (formatted) rows.push([label, formatted]);
}

function addPercentRow(rows: Array<[string, string]>, label: string, value: unknown): void {
  const formatted = formatPercent(value);
  if (formatted) rows.push([label, formatted]);
}

function detailPrimaryLabel(detail: HistoryDetails): string {
  if (detail.type === 'term_search') {
    return formatValue(detail.input.source_term) ?? formatValue(detail.input.term) ?? 'Term search';
  }
  if (detail.type === 'batch_map') {
    return formatValue(detail.input.filename) ?? 'Batch map';
  }
  const codes = Array.isArray(detail.input.codes) ? detail.input.codes : [];
  if (codes.length > 0) {
    const preview = codes.slice(0, 3).join(', ');
    return codes.length > 3 ? `${preview} +${codes.length - 3} more` : preview;
  }
  return detail.result.summary.total_count > 0
    ? `${detail.result.summary.total_count} submitted codes`
    : 'Validation';
}

function configurationRows(configuration?: HistoryConfiguration | null): Array<[string, string]> {
  if (!configuration) return [];
  const rows: Array<[string, string]> = [];
  addRow(rows, 'Selected ontologies', configuration.target_ontologies);
  addRow(rows, 'Target ontology column', configuration.target_ontology_column);
  addPercentRow(rows, 'Auto-accept threshold', configuration.auto_accept_threshold);
  addRow(rows, 'Retrieval method', configuration.retrieval_method ? formatRetrievalMode(configuration.retrieval_method) : null);
  addRow(rows, 'AI provider', configuration.provider);
  addRow(rows, 'Model', configuration.model);
  addRow(rows, 'RAG/retrieval', configuration.rag_enabled);
  return rows;
}

function termSearchSummaryRows(detail: TermSearchHistoryDetails): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  addRow(rows, 'Original term', detail.input.source_term ?? detail.input.term);
  addRow(rows, 'Source label', detail.input.source_label);
  addRow(rows, 'Description', detail.input.source_description);
  addRow(rows, 'Data type', detail.input.source_data_type);
  addRow(rows, 'Clinical area', detail.input.clinical_area);
  return [...rows, ...configurationRows(detail.configuration)];
}

function batchSummaryRows(detail: BatchMapHistoryDetails): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  addRow(rows, 'Filename', detail.input.filename);
  addRow(rows, 'Total rows', detail.result.summary.total_rows ?? detail.input.row_count);
  addRow(rows, 'Completed mappings', detail.result.summary.completed_count);
  addRow(rows, 'Accepted', detail.result.summary.accepted_count);
  addRow(rows, 'Pending', detail.result.summary.pending_count);
  addRow(rows, 'Rejected', detail.result.summary.rejected_count);
  addRow(rows, 'Unmapped', detail.result.summary.unmapped_count);
  return [...rows, ...configurationRows(detail.configuration)];
}

function validationSummaryRows(detail: ValidationHistoryDetails): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  const codes = Array.isArray(detail.input.codes) ? detail.input.codes : [];
  addRow(rows, 'Submitted codes', codes.length > 0 ? `${codes.length} codes` : undefined);
  addRow(rows, 'Valid', detail.result.summary.valid_count);
  addRow(rows, 'Deprecated', detail.result.summary.deprecated_count);
  addRow(rows, 'Not found', detail.result.summary.not_found_count);
  addRow(rows, 'Errors', detail.result.summary.error_count);
  return rows;
}

function getSummaryRows(detail: HistoryDetails): Array<[string, string]> {
  if (detail.type === 'term_search') return termSearchSummaryRows(detail);
  if (detail.type === 'batch_map') return batchSummaryRows(detail);
  return validationSummaryRows(detail);
}

function canDownloadCsv(detail: HistoryDetails): boolean {
  if (detail.type === 'term_search') return Boolean(detail.result.best_match);
  if (detail.type === 'batch_map') return detail.result.rows.length > 0;
  return detail.result.results.length > 0;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const TYPE_META: Record<SessionType, { icon: string; label: string; cls: string }> = {
  validation:  { icon: '✓',  label: 'Validation',  cls: 'hist-type--validation'  },
  term_search: { icon: '🔍', label: 'Term Search',  cls: 'hist-type--term-search' },
  batch_map:   { icon: '⊞',  label: 'Batch Map',   cls: 'hist-type--batch-map'   },
};

function TypeBadge({ type }: { type: SessionType }) {
  const { icon, label, cls } = TYPE_META[type];
  return (
    <span className={`hist-type-badge ${cls}`}>
      <span aria-hidden="true">{icon}</span>{label}
    </span>
  );
}

const STATUS_META: Record<SessionStatus, { label: string; cls: string }> = {
  in_progress: { label: 'In Progress', cls: 'hist-status-badge--in-progress' },
  complete:    { label: 'Complete',    cls: 'hist-status-badge--complete'    },
  error:       { label: 'Error',       cls: 'hist-status-badge--error'       },
  interrupted: { label: 'Interrupted', cls: 'hist-status-badge--interrupted' },
};

function StatusBadge({ status }: { status: SessionStatus }) {
  const { label, cls } = STATUS_META[status] ?? { label: status, cls: '' };
  return <span className={`hist-status-badge ${cls}`}>{label}</span>;
}

// ── Main component ────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [sessions, setSessions]           = useState<SessionSummary[]>([]);
  const [loading, setLoading]             = useState(true);
  const [openSession, setOpenSession]     = useState<HistoryDetails | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteError, setDeleteError]     = useState<string | null>(null);
  const [copiedCode, setCopiedCode]       = useState(false);
  const [expandedBatchRows, setExpandedBatchRows] = useState<Set<number>>(new Set());
  const [batchFilterStatus, setBatchFilterStatus] = useState('all');
  const [batchSearchQuery, setBatchSearchQuery] = useState('');

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return; // already running
    pollRef.current = setInterval(async () => {
      try {
        const data = await getSessions();
        setSessions(data);
        if (!data.some((s) => s.status === 'in_progress')) {
          stopPoll();
        }
      } catch {
        // silently ignore transient poll errors
      }
    }, 5000);
  }, [stopPoll]);

  // Initial load + cleanup
  useEffect(() => {
    let mounted = true;
    getSessions()
      .then((data) => {
        if (!mounted) return;
        setSessions(data);
        setLoading(false);
        if (data.some((s) => s.status === 'in_progress')) startPolling();
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
      stopPoll();
    };
  }, [startPolling, stopPoll]);

  async function handleReopen(id: string) {
    if (openSession?.id === id) {
      setOpenSession(null);
      return;
    }
    setLoadingDetail(true);
    setOpenSession(null);
    setCopiedCode(false);
    setExpandedBatchRows(new Set());
    setBatchFilterStatus('all');
    setBatchSearchQuery('');
    try {
      const session = await getSession(id);
      setOpenSession(session);
    } catch {
      // ignore — panel stays closed
    } finally {
      setLoadingDetail(false);
    }
  }

  async function handleDelete(id: string) {
    setDeleteError(null);
    try {
      await deleteSession(id);
      setSessions((prev) => prev.filter((s) => s.session_id !== id));
      if (openSession?.id === id) setOpenSession(null);
    } catch {
      setDeleteError('Could not delete session — try again.');
    } finally {
      setConfirmDeleteId(null);
    }
  }

  const hasInProgress = sessions.some((s) => s.status === 'in_progress');
  const panelOpen = openSession !== null || loadingDetail;

  function handleCopyTermCode(detail: TermSearchHistoryDetails) {
    const code = detail.result.best_match?.target_code;
    if (!code) return;
    navigator.clipboard.writeText(code).then(() => {
      setCopiedCode(true);
      window.setTimeout(() => setCopiedCode(false), 2000);
    });
  }

  function handleDownloadCsv(detail: HistoryDetails) {
    if (detail.type === 'term_search' && detail.result.best_match) {
      downloadTermMappingCsv(detail.result.best_match, detail.created_at);
    } else if (detail.type === 'batch_map') {
      const filename = detail.input.filename
        ? `${String(detail.input.filename).replace(/\.[^.]+$/, '')}_history_results.csv`
        : 'batch-history-results.csv';
      downloadBatchRowsCsv(detail.result.rows, filename);
    } else if (detail.type === 'validation') {
      downloadValidationCsv(detail.result.results, detail.created_at);
    }
  }

  function toggleBatchExpand(rowIndex: number) {
    setExpandedBatchRows((prev) => {
      const next = new Set(prev);
      next.has(rowIndex) ? next.delete(rowIndex) : next.add(rowIndex);
      return next;
    });
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="history-page">
      <div className={`history-layout${panelOpen ? ' history-layout--with-panel' : ''}`}>

        {/* ── Main content area ──────────────────────────────────────────── */}
        <div className="history-content">
          <div className="history-header-row">
            <h1 className="page-title">History</h1>
            {hasInProgress && (
              <span className="hist-live-badge">
                <span className="hist-live-dot" aria-hidden="true" />
                Live
              </span>
            )}
          </div>
          <p className="page-subtitle">
            Past ontology validation, term search, and batch mapping sessions.
          </p>

          {deleteError && (
            <div className="search-alert search-alert--err" style={{ marginBottom: 16 }}>
              {deleteError}
              <button className="alert-link-btn" style={{ marginLeft: 12 }} onClick={() => setDeleteError(null)}>
                Dismiss
              </button>
            </div>
          )}

          {loading ? (
            <div className="history-loading">Loading sessions…</div>
          ) : sessions.length === 0 ? (
            <div className="history-empty">
              <p className="history-empty-title">No sessions yet</p>
              <p className="history-empty-sub">
                Sessions are recorded automatically when you use Validator, Term Search, or Batch Map.
              </p>
            </div>
          ) : (
            <div className="history-table-wrap">
              <table className="history-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Input</th>
                    <th>Date / Time</th>
                    <th>Rows</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr
                      key={s.session_id}
                      className={openSession?.id === s.session_id ? 'history-row--active' : ''}
                    >
                      <td><TypeBadge type={s.type} /></td>
                      <td>
                        <span className="hist-input-label" title={inputSummaryLabel(s.type, s.input_summary)}>
                          {inputSummaryLabel(s.type, s.input_summary)}
                        </span>
                      </td>
                      <td><span className="hist-date">{formatDate(s.created_at)}</span></td>
                      <td style={{ color: '#6b7280' }}>
                        {s.type === 'batch_map' && s.input_summary.row_count != null
                          ? s.input_summary.row_count
                          : '—'}
                      </td>
                      <td><StatusBadge status={s.status} /></td>
                      <td>
                        <div className="hist-actions">
                          <button
                            className={`hist-btn-sm hist-btn-reopen${openSession?.id === s.session_id ? ' hist-btn-reopen--active' : ''}`}
                            onClick={() => handleReopen(s.session_id)}
                            disabled={loadingDetail}
                          >
                            View Details
                          </button>
                          <a
                            href={exportUrl(s.session_id)}
                            download
                            className="hist-btn-sm hist-btn-export"
                          >
                            Export
                          </a>
                          {confirmDeleteId === s.session_id ? (
                            <span className="hist-delete-confirm">
                              Delete?&nbsp;
                              <button
                                className="hist-btn-sm hist-btn-danger"
                                onClick={() => handleDelete(s.session_id)}
                              >
                                Yes
                              </button>
                              <button
                                className="hist-btn-sm"
                                onClick={() => setConfirmDeleteId(null)}
                              >
                                No
                              </button>
                            </span>
                          ) : (
                            <button
                              className="hist-btn-sm hist-btn-delete"
                              onClick={() => setConfirmDeleteId(s.session_id)}
                              title="Delete session"
                            >
                              ✕
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Detail panel ───────────────────────────────────────────────── */}
        {panelOpen && (
          <aside className="history-panel history-panel--wide">
            {loadingDetail ? (
              <div className="history-panel-loading">
                <span className="spinner" style={{ borderTopColor: '#6b7280', borderColor: 'rgba(0,0,0,0.1)' }} aria-hidden="true" />
                Loading session…
              </div>
            ) : openSession ? (
              <>
                <div className="history-panel-header">
                  <div className="history-panel-header-meta">
                    <TypeBadge type={openSession.type} />
                    <p className="history-panel-title" style={{ marginTop: 8 }}>
                      {detailPrimaryLabel(openSession)}
                    </p>
                    <p className="history-panel-subtitle">
                      {formatDate(openSession.created_at)}
                    </p>
                    <div className="history-panel-header-status">
                      <StatusBadge status={openSession.status} />
                    </div>
                  </div>
                  {canDownloadCsv(openSession) && (
                    <button
                      className="btn-primary history-download-btn"
                      onClick={() => handleDownloadCsv(openSession)}
                    >
                      Download CSV
                    </button>
                  )}
                  <button
                    className="history-panel-close"
                    onClick={() => setOpenSession(null)}
                    aria-label="Close panel"
                  >
                    ✕
                  </button>
                </div>

                <div className="history-panel-body">
                  <div className="history-panel-section">
                    <p className="history-panel-section-title">Session summary</p>
                    <dl className="hist-meta-grid">
                      {getSummaryRows(openSession).map(([k, v]) => (
                        <Fragment key={k}>
                          <dt className="hist-meta-key">{k}</dt>
                          <dd className="hist-meta-val" style={{ margin: 0 }}>{v}</dd>
                        </Fragment>
                      ))}
                      <dt className="hist-meta-key">Status</dt>
                      <dd style={{ margin: 0 }}><StatusBadge status={openSession.status} /></dd>
                    </dl>
                  </div>

                  {openSession.failure?.message && (
                    <div className="history-panel-section">
                      <div className="history-failure-card">
                        <p className="history-failure-title">Session failed</p>
                        <p className="history-failure-message">{openSession.failure.message}</p>
                      </div>
                    </div>
                  )}

                  {openSession.status === 'in_progress' && (
                    <div className="history-panel-section">
                      <div className="history-progress-card">
                        This session is still in progress. Latest persisted results are shown when available.
                      </div>
                    </div>
                  )}

                  {openSession.legacy_message && (
                    <div className="history-panel-section">
                      <div className="history-legacy-card">{openSession.legacy_message}</div>
                    </div>
                  )}

                  {openSession.type === 'term_search' && openSession.result.best_match && (
                    <div className="history-panel-section history-results-section">
                      <TermSearchResultView
                        bestMatch={openSession.result.best_match}
                        alternatives={openSession.result.alternatives}
                        copied={copiedCode}
                        readOnly
                        onCopy={() => handleCopyTermCode(openSession)}
                        onDownloadCsv={() => handleDownloadCsv(openSession)}
                      />
                    </div>
                  )}

                  {openSession.type === 'batch_map' && openSession.result.rows.length > 0 && (
                    <div className="history-panel-section history-results-section">
                      <div className="card">
                        <h2 className="batch-section-heading">Archived Mappings</h2>
                        <BatchResultsTable
                          rows={openSession.result.rows}
                          expandedRows={expandedBatchRows}
                          filterStatus={batchFilterStatus}
                          searchQuery={batchSearchQuery}
                          readOnly
                          isRunning={openSession.status === 'in_progress'}
                          onFilterStatusChange={setBatchFilterStatus}
                          onSearchQueryChange={setBatchSearchQuery}
                          onToggleExpand={toggleBatchExpand}
                        />
                      </div>
                    </div>
                  )}

                  {openSession.type === 'validation' && openSession.result.results.length > 0 && (
                    <div className="history-panel-section history-results-section">
                      <div className="card">
                        <div className="val-results-header">
                          <h2 className="val-results-heading">Validation Results</h2>
                          <span className="val-count-badge">
                            {openSession.result.results.length} code{openSession.result.results.length !== 1 ? 's' : ''} checked
                          </span>
                        </div>
                        <ValidationResultsTable rows={openSession.result.results} showOntology />
                      </div>
                    </div>
                  )}
                </div>
              </>
            ) : null}
          </aside>
        )}
      </div>
    </div>
  );
}
