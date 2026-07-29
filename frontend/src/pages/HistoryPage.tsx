import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import { deleteSession, exportUrl, getSession, getSessions } from '../api/historyApi';
import type { EventRecord, InputSummary, SessionRecord, SessionStatus, SessionSummary, SessionType } from '../types/session';
import './HistoryPage.css';

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

function relativeTime(eventIso: string, startIso: string): string {
  const diffMs = new Date(eventIso).getTime() - new Date(startIso).getTime();
  const secs = Math.max(0, Math.round(diffMs / 1000));
  if (secs < 60) return `${secs}s after start`;
  return `${Math.round(secs / 60)} min after start`;
}

function formatEventType(raw: string): string {
  return raw
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
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

function inputSummaryMetaRows(summary: InputSummary): Array<[string, string]> {
  const rows: Array<[string, string]> = [];
  if (summary.filename)               rows.push(['File', summary.filename]);
  if (summary.row_count != null)      rows.push(['Rows', String(summary.row_count)]);
  if (summary.term)                   rows.push(['Term', summary.term]);
  if (summary.codes && summary.codes.length > 0) rows.push(['Codes', `${summary.codes.length} codes`]);
  if (summary.clinical_area)          rows.push(['Area', summary.clinical_area]);
  if (summary.term || summary.filename) rows.push(['Ontologies', formatOntologySummary(summary)]);
  if (summary.auto_accept_threshold != null) {
    rows.push(['Auto-accept', `${Math.round(summary.auto_accept_threshold * 100)}%`]);
  }
  return rows;
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
};

function StatusBadge({ status }: { status: SessionStatus }) {
  const { label, cls } = STATUS_META[status] ?? { label: status, cls: '' };
  return <span className={`hist-status-badge ${cls}`}>{label}</span>;
}

function PayloadTags({ payload }: { payload: Record<string, unknown> }) {
  const tags = Object.entries(payload)
    .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
    .map(([k, v]) => `${k}: ${String(v)}`)
    .filter((s) => s.length <= 48);
  if (tags.length === 0) return null;
  return (
    <div className="history-event-tags">
      {tags.map((tag) => (
        <span key={tag} className="hist-payload-tag">{tag}</span>
      ))}
    </div>
  );
}

function TimelineItem({ event, startIso }: { event: EventRecord; startIso: string }) {
  return (
    <div className="history-timeline-item">
      <span className={`history-timeline-dot history-timeline-dot--${event.actor}`} aria-hidden="true" />
      <div className="history-timeline-content">
        <span className="history-event-type">{formatEventType(event.event_type)}</span>
        <PayloadTags payload={event.payload} />
        <span className="history-event-time">{relativeTime(event.timestamp, startIso)}</span>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function HistoryPage() {
  const [sessions, setSessions]           = useState<SessionSummary[]>([]);
  const [loading, setLoading]             = useState(true);
  const [openSession, setOpenSession]     = useState<SessionRecord | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteError, setDeleteError]     = useState<string | null>(null);

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
    if (openSession?.session_id === id) {
      setOpenSession(null);
      return;
    }
    setLoadingDetail(true);
    setOpenSession(null);
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
      if (openSession?.session_id === id) setOpenSession(null);
    } catch {
      setDeleteError('Could not delete session — try again.');
    } finally {
      setConfirmDeleteId(null);
    }
  }

  const hasInProgress = sessions.some((s) => s.status === 'in_progress');
  const panelOpen = openSession !== null || loadingDetail;

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
                      className={openSession?.session_id === s.session_id ? 'history-row--active' : ''}
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
                            className={`hist-btn-sm hist-btn-reopen${openSession?.session_id === s.session_id ? ' hist-btn-reopen--active' : ''}`}
                            onClick={() => handleReopen(s.session_id)}
                            disabled={loadingDetail}
                          >
                            {loadingDetail && openSession?.session_id !== s.session_id ? 'Re-open' : 'Re-open'}
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
          <aside className="history-panel">
            {loadingDetail ? (
              <div className="history-panel-loading">
                <span className="spinner" style={{ borderTopColor: '#6b7280', borderColor: 'rgba(0,0,0,0.1)' }} aria-hidden="true" />
                Loading session…
              </div>
            ) : openSession ? (
              <>
                {/* Panel header */}
                <div className="history-panel-header">
                  <div className="history-panel-header-meta">
                    <TypeBadge type={openSession.type} />
                    <p className="history-panel-title" style={{ marginTop: 8 }}>
                      {inputSummaryLabel(openSession.type, openSession.input_summary)}
                    </p>
                    <p className="history-panel-subtitle">
                      {formatDate(openSession.created_at)} · {openSession.event_count} event{openSession.event_count !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <button
                    className="history-panel-close"
                    onClick={() => setOpenSession(null)}
                    aria-label="Close panel"
                  >
                    ✕
                  </button>
                </div>

                {/* Panel body */}
                <div className="history-panel-body">

                  {/* Input summary */}
                  <div className="history-panel-section">
                    <p className="history-panel-section-title">Input</p>
                    <dl className="hist-meta-grid">
                      {inputSummaryMetaRows(openSession.input_summary).map(([k, v]) => (
                        <Fragment key={k}>
                          <dt className="hist-meta-key">{k}</dt>
                          <dd className="hist-meta-val" style={{ margin: 0 }}>{v}</dd>
                        </Fragment>
                      ))}
                      <dt className="hist-meta-key">Status</dt>
                      <dd style={{ margin: 0 }}><StatusBadge status={openSession.status} /></dd>
                    </dl>
                  </div>

                  {/* Event timeline */}
                  <div className="history-panel-section">
                    <p className="history-panel-section-title">Event Timeline</p>
                    {openSession.events.length === 0 ? (
                      <p style={{ margin: 0, fontSize: 12, color: '#9ca3af' }}>No events recorded.</p>
                    ) : (
                      <div className="history-timeline">
                        {openSession.events.map((event, i) => (
                          <TimelineItem
                            key={i}
                            event={event}
                            startIso={openSession.created_at}
                          />
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Result snapshot */}
                  {openSession.result_snapshot != null && (
                    <div className="history-panel-section">
                      <p className="history-panel-section-title">Result Snapshot</p>
                      <pre className="hist-snapshot">
                        {JSON.stringify(openSession.result_snapshot, null, 2)}
                      </pre>
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
