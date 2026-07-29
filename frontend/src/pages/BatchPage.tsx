import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cancelBatch,
  exportUrl,
  getBatchStatus,
  setDecision as apiSetDecision,
  startBatch,
  uploadPreview,
} from '../api/batchApi';
import OntologyMultiSelect from '../components/OntologyMultiSelect';
import { ONTOLOGY_OPTIONS } from '../constants/ontologies';
import { useSession } from '../context/SessionContext';
import type { BatchJobStatus, BatchRowResult, BatchUploadPreview } from '../types/mapping';
import { targetOntologiesOrNull } from '../utils/ontologyPayloads';
import './BatchPage.css';

// ── Constants ────────────────────────────────────────────────────────────────

const CLINICAL_AREA_OPTIONS = [
  { value: 'phenotype',    label: 'Phenotype' },
  { value: 'disease',      label: 'Disease/Condition' },
  { value: 'measurement',  label: 'Lab/Measurement' },
  { value: 'medication',   label: 'Medication' },
  { value: 'demographic',  label: 'Demographic' },
  { value: 'other',        label: 'Other' },
];

const COLUMN_ROLES = [
  { key: 'field_name', label: 'Field variable name', required: true },
  { key: 'label',      label: 'Human-readable label', required: false },
  { key: 'description', label: 'Description',         required: false },
  { key: 'data_type',  label: 'Data type',            required: false },
];

const SAMPLE_CSV = `field_name,label,desc,data_type
systolic_bp,Systolic Blood Pressure,Measured in mmHg at rest,numeric
diastolic_bp,Diastolic Blood Pressure,Measured in mmHg at rest,numeric
heart_rate,Heart Rate,Beats per minute at rest,numeric
smoking_status,Smoking Status,Current smoking habits,categorical
ethnicity,Ethnicity,Patient ethnicity,categorical
age,Age,Patient age in years,numeric
bmi,BMI,Body mass index kg/m2,numeric
diabetes,Diabetes Status,Type 1 or Type 2 diabetes diagnosis,categorical
hypertension,Hypertension,Diagnosed with hypertension,boolean
cholesterol,Total Cholesterol,Total cholesterol in mg/dL,numeric`;

// ── Helpers ──────────────────────────────────────────────────────────────────

function confTier(c: number): 'high' | 'med' | 'low' {
  if (c >= 0.85) return 'high';
  if (c >= 0.5)  return 'med';
  return 'low';
}

function confLabel(c: number): string {
  if (c >= 0.85) return 'High';
  if (c >= 0.5)  return 'Med';
  return 'Low';
}

function estimateMinutes(rows: number, rag: boolean): number {
  return Math.max(1, Math.round((rows * (rag ? 5 : 2)) / 60));
}

function downloadSample() {
  const blob = new Blob([SAMPLE_CSV], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'sample_data_dictionary.csv';
  a.click();
  URL.revokeObjectURL(url);
}

// ── Sub-components ───────────────────────────────────────────────────────────

function ConfBadge({ confidence }: { confidence: number }) {
  const tier = confTier(confidence);
  return (
    <span className={`batch-conf-badge batch-conf-badge--${tier}`}>
      {confidence >= 0.85 ? '✅' : confidence >= 0.5 ? '⚠️' : '❌'}{' '}
      {Math.round(confidence * 100)}% {confLabel(confidence)}
    </span>
  );
}

function DecisionChip({ decision }: { decision: string }) {
  return (
    <span className={`batch-decision-chip batch-decision-chip--${decision}`}>
      {decision.charAt(0).toUpperCase() + decision.slice(1)}
    </span>
  );
}

// ── Step indicator ───────────────────────────────────────────────────────────

type Phase = 'upload' | 'running' | 'review' | 'exported';

function StepIndicator({ phase }: { phase: Phase }) {
  const steps = ['Upload', 'Mapping', 'Review', 'Export'];
  const currentIdx = { upload: 0, running: 1, review: 2, exported: 3 }[phase];

  return (
    <div className="batch-steps">
      {steps.map((label, i) => {
        const active = i === currentIdx;
        const done = i < currentIdx;
        return (
          <>
            <div
              key={label}
              className={`batch-step${active ? ' batch-step--active' : ''}${done ? ' batch-step--done' : ''}`}
            >
              <span className="batch-step-num">{i + 1}</span>
              <span className="batch-step-label">{label}</span>
            </div>
            {i < steps.length - 1 && (
              <div key={`conn-${i}`} className="batch-step-connector" />
            )}
          </>
        );
      })}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

export default function BatchPage() {
  // File & preview
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<BatchUploadPreview | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // Column mapping config
  const [columnMap, setColumnMap] = useState<Record<string, string | null>>({
    field_name: null,
    label: null,
    description: null,
    data_type: null,
  });
  const [clinicalArea, setClinicalArea] = useState<string>('phenotype');
  const [targetOntologies, setTargetOntologies] = useState<string[]>([]);
  const [useRag, setUseRag] = useState(true);
  const [autoAcceptThreshold, setAutoAcceptThreshold] = useState(85);

  // Job state
  const [phase, setPhase] = useState<Phase>('upload');
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<BatchJobStatus | null>(null);

  // Local decision overrides (row_index → decision)
  const [localDecisions, setLocalDecisions] = useState<Record<number, 'accepted' | 'rejected' | 'pending'>>({});

  // Review table state
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [filterStatus, setFilterStatus] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Error
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [starting, setStarting] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { startSession, emitEvent, completeSession } = useSession();
  const batchSessionIdRef = useRef<string | null>(null);
  const lastCompletedRef = useRef<number>(0);

  // ── Polling ────────────────────────────────────────────────────────────────

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!jobId || phase === 'upload') return;

    pollRef.current = setInterval(async () => {
      try {
        const status = await getBatchStatus(jobId);
        setJobStatus(status);

        const sid = batchSessionIdRef.current;
        if (sid && status.completed > lastCompletedRef.current) {
          lastCompletedRef.current = status.completed;
          emitEvent(sid, {
            timestamp: new Date().toISOString(),
            actor: 'system',
            event_type: 'batch_progress',
            payload: { completed: status.completed, total: status.total },
          }).catch(console.error);
        }

        if (status.status === 'done' && sid) {
          const mapped   = status.results.filter(r => !r.suggested_code.toUpperCase().includes('UNMAPPED')).length;
          const unmapped = status.results.filter(r =>  r.suggested_code.toUpperCase().includes('UNMAPPED')).length;
          emitEvent(sid, {
            timestamp: new Date().toISOString(),
            actor: 'system',
            event_type: 'batch_mapping_complete',
            payload: { mapped, unmapped },
          }).catch(console.error);
          completeSession(sid, 'complete', status).catch(console.error);
        }

        if (status.status === 'done' || status.status === 'cancelled') {
          stopPoll();
          setPhase('review');
        }
      } catch {
        // silently ignore transient poll errors
      }
    }, 1500);

    return stopPoll;
  }, [jobId, phase, stopPoll, emitEvent, completeSession]);

  // ── File handling ──────────────────────────────────────────────────────────

  async function handleFileSelected(f: File) {
    setFile(f);
    setError(null);
    setUploading(true);
    try {
      const prev = await uploadPreview(f);
      setPreview(prev);
      // Auto-map columns by guessing common names
      const cols = prev.columns.map((c) => c.toLowerCase());
      const guess = (candidates: string[]) => {
        for (const c of candidates) {
          const match = prev.columns.find((col) => col.toLowerCase() === c);
          if (match) return match;
        }
        return prev.columns[0] || null;
      };
      setColumnMap({
        field_name:  guess(['field_name', 'field', 'variable', 'var_name', 'name']),
        label:       prev.columns.find((c) => cols.includes(c.toLowerCase()) && ['label', 'field_label', 'human_label'].includes(c.toLowerCase())) || null,
        description: prev.columns.find((c) => ['desc', 'description', 'notes', 'comment'].includes(c.toLowerCase())) || null,
        data_type:   prev.columns.find((c) => ['data_type', 'type', 'dtype', 'datatype'].includes(c.toLowerCase())) || null,
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Could not parse file.');
      setFile(null);
      setPreview(null);
    } finally {
      setUploading(false);
    }
  }

  function onFileInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) handleFileSelected(f);
    e.target.value = '';
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) handleFileSelected(f);
  }

  function removeFile() {
    setFile(null);
    setPreview(null);
    setColumnMap({ field_name: null, label: null, description: null, data_type: null });
    setError(null);
  }

  // ── Start mapping ──────────────────────────────────────────────────────────

  async function handleStart() {
    if (!file || !preview) return;
    const fn = columnMap.field_name;
    if (!fn) {
      setError('Please select the column containing field variable names.');
      return;
    }
    setError(null);
    setStarting(true);
    const selectedOntologies = targetOntologiesOrNull(targetOntologies);
    try {
      const { job_id } = await startBatch({
        file,
        columnMap,
        clinicalArea: clinicalArea || null,
        targetOntologies,
        useRag,
        autoAcceptThreshold: autoAcceptThreshold / 100,
      });
      setJobId(job_id);
      setLocalDecisions({});
      lastCompletedRef.current = 0;
      setPhase('running');

      try {
        const sid = await startSession('batch_map', {
          filename: file.name,
          row_count: preview.row_count,
          clinical_area: clinicalArea || undefined,
          target_ontologies: selectedOntologies,
          auto_accept_threshold: autoAcceptThreshold / 100,
        });
        batchSessionIdRef.current = sid;
        emitEvent(sid, {
          timestamp: new Date().toISOString(),
          actor: 'user',
          event_type: 'batch_started',
          payload: {
            filename: file.name,
            row_count: preview.row_count,
            clinical_area: clinicalArea || null,
            target_ontologies: selectedOntologies,
            use_rag: useRag,
            auto_accept_threshold: autoAcceptThreshold / 100,
          },
        }).catch(console.error);
      } catch {
        batchSessionIdRef.current = null;
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start batch job.');
    } finally {
      setStarting(false);
    }
  }

  // ── Cancel ─────────────────────────────────────────────────────────────────

  async function handleCancel() {
    if (!jobId) return;
    const sid = batchSessionIdRef.current;
    if (sid) {
      emitEvent(sid, {
        timestamp: new Date().toISOString(),
        actor: 'user',
        event_type: 'batch_cancelled',
        payload: {},
      }).catch(console.error);
      completeSession(sid, 'error').catch(console.error);
    }
    try {
      await cancelBatch(jobId);
    } catch {
      // ignore
    }
    stopPoll();
    setPhase('review');
  }

  // ── Decision handling ──────────────────────────────────────────────────────

  function getEffectiveDecision(row: BatchRowResult): 'accepted' | 'rejected' | 'pending' {
    return localDecisions[row.row_index] ?? row.decision;
  }

  async function toggleDecision(row: BatchRowResult, newDecision: 'accepted' | 'rejected') {
    if (!jobId) return;
    const current = getEffectiveDecision(row);
    const next: 'accepted' | 'rejected' | 'pending' =
      current === newDecision ? 'pending' : newDecision;
    setLocalDecisions((prev) => ({ ...prev, [row.row_index]: next }));
    apiSetDecision(jobId, row.row_index, next).catch(() => {});
    const sid = batchSessionIdRef.current;
    if (sid) {
      emitEvent(sid, {
        timestamp: new Date().toISOString(),
        actor: 'user',
        event_type: 'row_decision',
        payload: { row_index: row.row_index, field_name: row.field_name, code: row.suggested_code, term: row.suggested_term, decision: next },
      }).catch(console.error);
    }
  }

  async function bulkDecision(type: 'accept_high' | 'reject_unmapped' | 'reset') {
    if (!jobId || !jobStatus) return;
    const threshold = autoAcceptThreshold / 100;
    const updates: Record<number, 'accepted' | 'rejected' | 'pending'> = {};

    for (const row of jobStatus.results) {
      if (type === 'accept_high' && row.confidence >= threshold) {
        updates[row.row_index] = 'accepted';
      } else if (type === 'reject_unmapped' && row.suggested_code.toUpperCase().includes('UNMAPPED')) {
        updates[row.row_index] = 'rejected';
      } else if (type === 'reset') {
        updates[row.row_index] = 'pending';
      }
    }

    setLocalDecisions((prev) => (type === 'reset' ? {} : { ...prev, ...updates }));
    // Fire PATCH calls in background
    for (const [rowIdx, dec] of Object.entries(updates)) {
      apiSetDecision(jobId, Number(rowIdx), dec).catch(() => {});
    }
    const sid = batchSessionIdRef.current;
    if (sid) {
      const operationMap = { accept_high: 'accept_high', reject_unmapped: 'reject_unmapped', reset: 'reset_all' } as const;
      emitEvent(sid, {
        timestamp: new Date().toISOString(),
        actor: 'user',
        event_type: 'bulk_decision',
        payload: { operation: operationMap[type], affected_count: Object.keys(updates).length },
      }).catch(console.error);
    }
  }

  // ── Expand/collapse ────────────────────────────────────────────────────────

  function toggleExpand(rowIndex: number) {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      next.has(rowIndex) ? next.delete(rowIndex) : next.add(rowIndex);
      return next;
    });
  }

  // ── Reset ─────────────────────────────────────────────────────────────────

  function resetAll() {
    setFile(null);
    setPreview(null);
    setColumnMap({ field_name: null, label: null, description: null, data_type: null });
    setClinicalArea('phenotype');
    setTargetOntologies([]);
    setUseRag(true);
    setAutoAcceptThreshold(85);
    setPhase('upload');
    setJobId(null);
    setJobStatus(null);
    setLocalDecisions({});
    setExpandedRows(new Set());
    setFilterStatus('all');
    setSearchQuery('');
    setError(null);
    stopPoll();
    batchSessionIdRef.current = null;
    lastCompletedRef.current = 0;
  }

  // ── Derived stats ──────────────────────────────────────────────────────────

  const results = jobStatus?.results ?? [];
  const accepted = results.filter((r) => getEffectiveDecision(r) === 'accepted').length;
  const rejected = results.filter((r) => getEffectiveDecision(r) === 'rejected').length;
  const pending  = results.filter((r) => getEffectiveDecision(r) === 'pending').length;
  const highCount = results.filter((r) => r.confidence >= 0.85).length;
  const medCount  = results.filter((r) => r.confidence >= 0.5 && r.confidence < 0.85).length;
  const lowCount  = results.filter((r) => r.confidence < 0.5).length;

  const filteredResults = results.filter((r) => {
    const dec = getEffectiveDecision(r);
    const matchesFilter = filterStatus === 'all' || dec === filterStatus;
    const q = searchQuery.toLowerCase();
    const matchesSearch = !q
      || r.field_name.toLowerCase().includes(q)
      || (r.label ?? '').toLowerCase().includes(q)
      || r.suggested_code.toLowerCase().includes(q)
      || r.suggested_term.toLowerCase().includes(q);
    return matchesFilter && matchesSearch;
  });

  const completed = jobStatus?.completed ?? 0;
  const total = jobStatus?.total ?? preview?.row_count ?? 0;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const isRunning = phase === 'running' && jobStatus?.status === 'running';
  const lastField = results[results.length - 1]?.field_name ?? '';

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="batch-page">
      <h1 className="page-title">Batch Data Dictionary Mapping</h1>
      <p className="batch-subtitle">
        Upload your data dictionary, let the AI map all fields, then review and export.
      </p>

      <StepIndicator phase={phase} />

      {error && <div className="batch-error">{error}</div>}

      {/* ── Step 1: Upload + Config ───────────────────────────────────── */}
      {phase === 'upload' && (
        <>
          {/* Upload card */}
          <div className="card">
            <h2 className="batch-section-heading">📂 Upload Your Data Dictionary</h2>

            {!file ? (
              <>
                <div
                  className={`batch-upload-zone${isDragging ? ' batch-upload-zone--dragging' : ''}`}
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={onDrop}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
                  aria-label="Upload file"
                >
                  <div className="batch-upload-icon">☁️</div>
                  <div className="batch-upload-main">
                    {uploading ? 'Parsing file…' : 'Drop file here or click to browse'}
                  </div>
                  <div className="batch-upload-sub">CSV or Excel (.xlsx)</div>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx"
                  style={{ display: 'none' }}
                  onChange={onFileInputChange}
                />
                <p className="batch-upload-hint">
                  Don't have a file ready?{' '}
                  <button className="batch-sample-link" onClick={downloadSample} type="button">
                    Try the sample data dictionary
                  </button>
                </p>
              </>
            ) : (
              <div className="batch-file-selected">
                <span>✅</span>
                <span className="batch-file-name">{file.name}</span>
                {preview && (
                  <span style={{ color: '#6b7280', fontSize: 12 }}>
                    {preview.row_count} rows · {preview.columns.length} columns
                  </span>
                )}
                <button className="batch-file-remove" onClick={removeFile} type="button" title="Remove file">
                  ✕
                </button>
              </div>
            )}
          </div>

          {/* Column mapping card */}
          {preview && (
            <div className="card">
              <h2 className="batch-section-heading">Tell us which columns contain what</h2>
              <p className="field-helper" style={{ marginBottom: 16 }}>
                We detected these column headers:{' '}
                <strong>{preview.columns.join(', ')}</strong>.{' '}
                Match them to the expected roles below.
              </p>

              <div className="batch-col-map-grid">
                {COLUMN_ROLES.map((role) => (
                  <>
                    <label key={`label-${role.key}`} className="batch-col-map-label">
                      {role.label}{' '}
                      {role.required
                        ? <span className="required-mark">*</span>
                        : <span className="optional-mark">(or leave blank)</span>}
                    </label>
                    <select
                      key={`sel-${role.key}`}
                      className="form-select"
                      value={columnMap[role.key] ?? ''}
                      onChange={(e) =>
                        setColumnMap((prev) => ({
                          ...prev,
                          [role.key]: e.target.value || null,
                        }))
                      }
                    >
                      {!role.required && <option value="">— none —</option>}
                      {preview.columns.map((col) => (
                        <option key={col} value={col}>{col}</option>
                      ))}
                    </select>
                  </>
                ))}

                {/* Clinical area */}
                <label className="batch-col-map-label">Clinical area</label>
                <div>
                  <select
                    className="form-select"
                    value={clinicalArea}
                    onChange={(e) => setClinicalArea(e.target.value)}
                  >
                    <option value="">— select —</option>
                    {CLINICAL_AREA_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <p className="field-helper-sm" style={{ marginTop: 4 }}>
                    Set a fixed value for all rows, or choose the column that contains per-row values.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Mapping options card */}
          {preview && (
            <div className="card">
              <h2 className="batch-section-heading">Mapping options</h2>

              <div style={{ marginBottom: 16 }}>
                <label className="batch-rag-row" style={{ cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={useRag}
                    onChange={(e) => setUseRag(e.target.checked)}
                    style={{ width: 15, height: 15, accentColor: '#1d4ed8', cursor: 'pointer' }}
                  />
                  Use RAG grounding
                </label>
                <p className="batch-rag-desc" style={{ marginTop: 4, marginLeft: 23 }}>
                  Recommended — slower but more accurate.
                </p>
              </div>

              <div style={{ marginBottom: 16 }}>
                <OntologyMultiSelect
                  label="Target ontologies"
                  options={ONTOLOGY_OPTIONS}
                  selectedValues={targetOntologies}
                  onChange={setTargetOntologies}
                  helperText="Selected ontologies restrict the mapping results. Leave all unselected for automatic selection."
                />
              </div>

              <div className="batch-threshold-row">
                <label className="field-label" style={{ margin: 0 }}>Auto-accept above</label>
                <input
                  type="number"
                  className="batch-threshold-input"
                  min={0}
                  max={100}
                  value={autoAcceptThreshold}
                  onChange={(e) => setAutoAcceptThreshold(Number(e.target.value))}
                />
                <span className="input-suffix">%</span>
              </div>
              <p className="field-helper" style={{ marginTop: 6 }}>
                Rows above this threshold are pre-ticked as Accepted.
              </p>
            </div>
          )}

          {/* Preview banner + Start button */}
          {preview && (
            <div className="batch-preview-banner">
              <span className="batch-preview-text">
                Preview: <strong>{preview.row_count} rows</strong> detected in{' '}
                <strong>{preview.filename}</strong> · Estimated time:{' '}
                <strong>~{estimateMinutes(preview.row_count, useRag)} minutes</strong>{' '}
                {useRag ? 'with RAG enabled' : 'without RAG'}
              </span>
              <button
                className="btn-primary"
                onClick={handleStart}
                disabled={starting || !columnMap.field_name}
              >
                {starting ? (
                  <><span className="spinner" aria-hidden="true" /> Starting…</>
                ) : (
                  '▶ Start Mapping'
                )}
              </button>
            </div>
          )}
        </>
      )}

      {/* ── Step 2: Progress + Live review ───────────────────────────── */}
      {(phase === 'running' || phase === 'review') && jobStatus && (
        <>
          {/* Preview banner (read-only) */}
          <div className="batch-preview-banner" style={{ marginBottom: 20 }}>
            <span className="batch-preview-text">
              Preview: <strong>{jobStatus.total} rows</strong> detected in{' '}
              <strong>{file?.name ?? 'file'}</strong> · Estimated time:{' '}
              <strong>~{estimateMinutes(jobStatus.total, useRag)} minutes</strong>{' '}
              {useRag ? 'with RAG enabled' : ''}
            </span>
            {phase === 'review' && (
              <button className="btn-primary" onClick={resetAll}>
                ▶ Start Mapping
              </button>
            )}
          </div>

          {/* Progress card */}
          {phase === 'running' && (
            <div className="card">
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <span style={{ fontWeight: 600, fontSize: 15 }}>Mapping in progress…</span>
                <span style={{ fontSize: 13, color: '#6b7280' }}>
                  {completed} / {total} fields
                </span>
              </div>

              <div className="batch-progress-bar-track">
                <div
                  className="batch-progress-bar-fill"
                  style={{ width: `${progressPct}%` }}
                />
              </div>

              <div className="batch-progress-meta">
                {lastField && (
                  <span>
                    Currently mapping: <strong>{lastField}</strong>
                  </span>
                )}
                <span>
                  Estimated time remaining:{' '}
                  <strong>
                    ~{Math.max(1, Math.round(((total - completed) * (useRag ? 5 : 2)) / 60))} min
                  </strong>
                </span>
              </div>

              <div className="batch-confidence-summary">
                <span className="batch-conf-high">
                  ✅ High: {highCount}
                </span>
                <span className="batch-conf-med">
                  ⚠️ Medium: {medCount}
                </span>
                <span className="batch-conf-low">
                  ❌ Low/unmapped: {lowCount}
                </span>
              </div>

              <div className="batch-progress-footer">
                <button className="btn-outline" onClick={handleCancel}>
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Review table */}
          {results.length > 0 && (
            <div className="card">
              <h2 className="batch-section-heading">Review and Approve Mappings</h2>

              {/* Bulk toolbar */}
              <div className="batch-bulk-toolbar">
                <button
                  className="batch-btn-bulk"
                  onClick={() => bulkDecision('accept_high')}
                >
                  Accept all High (≥{autoAcceptThreshold}%)
                </button>
                <button
                  className="batch-btn-bulk"
                  onClick={() => bulkDecision('reject_unmapped')}
                >
                  Reject all Unmapped
                </button>
                <button
                  className="batch-btn-bulk"
                  onClick={() => bulkDecision('reset')}
                >
                  Reset all
                </button>
                <select
                  className="batch-filter-select"
                  value={filterStatus}
                  onChange={(e) => setFilterStatus(e.target.value)}
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
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>

              {/* Table */}
              <div className="batch-table-scroll">
                <table className="batch-table">
                  <thead>
                    <tr>
                      <th>Field name</th>
                      <th>Label</th>
                      <th>Suggested code</th>
                      <th>Confidence</th>
                      <th>Decision</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredResults.map((row) => {
                      const dec = getEffectiveDecision(row);
                      const isExpanded = expandedRows.has(row.row_index);
                      return (
                        <>
                          <tr key={`row-${row.row_index}`} className="batch-table-row">
                            <td style={{ fontFamily: 'ui-monospace, monospace', fontSize: 12, color: '#1d4ed8' }}>
                              {row.field_name}
                            </td>
                            <td style={{ color: '#374151', fontSize: 13 }}>
                              {row.label ?? '—'}
                            </td>
                            <td>
                              {row.suggested_code === 'UNMAPPED' ? (
                                <span style={{ color: '#9ca3af', fontSize: 13 }}>UNMAPPED</span>
                              ) : (
                                <>
                                  <div className="batch-code-main">{row.suggested_code}</div>
                                  <div className="batch-code-term">{row.suggested_term}</div>
                                </>
                              )}
                            </td>
                            <td>
                              <ConfBadge confidence={row.confidence} />
                            </td>
                            <td>
                              <DecisionChip decision={dec} />
                            </td>
                            <td>
                              <div className="batch-actions-cell">
                                <button
                                  className={`batch-action-btn${dec === 'accepted' ? ' batch-action-btn--active-accept' : ''}`}
                                  title="Accept"
                                  onClick={() => toggleDecision(row, 'accepted')}
                                >
                                  👍
                                </button>
                                <button
                                  className={`batch-action-btn${dec === 'rejected' ? ' batch-action-btn--active-reject' : ''}`}
                                  title="Reject"
                                  onClick={() => toggleDecision(row, 'rejected')}
                                >
                                  👎
                                </button>
                                {row.alternatives.length > 0 && (
                                  <button
                                    className="batch-action-btn"
                                    title={isExpanded ? 'Collapse' : 'Show alternatives'}
                                    onClick={() => toggleExpand(row.row_index)}
                                  >
                                    {isExpanded ? '▲' : '▼'}
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {isExpanded && row.alternatives.length > 0 && (
                            <tr key={`alt-${row.row_index}`} className="batch-alt-row">
                              <td colSpan={6}>
                                <div className="batch-alt-list">
                                  {row.alternatives.map((alt) => (
                                    <div key={alt.code} className="batch-alt-item">
                                      <span className="batch-alt-code">{alt.code}</span>
                                      <span>{alt.term}</span>
                                      <ConfBadge confidence={alt.confidence} />
                                    </div>
                                  ))}
                                </div>
                              </td>
                            </tr>
                          )}
                        </>
                      );
                    })}
                    {filteredResults.length === 0 && (
                      <tr>
                        <td colSpan={6} style={{ textAlign: 'center', color: '#9ca3af', padding: '20px 0' }}>
                          {isRunning ? 'Waiting for results…' : 'No rows match filters.'}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              {/* Row summary + export */}
              <div className="batch-row-summary">
                <span>
                  {filteredResults.length} of {results.length} rows shown ·{' '}
                  <span style={{ color: '#166534' }}>{accepted} accepted</span>,{' '}
                  <span style={{ color: '#991b1b' }}>{rejected} rejected</span>,{' '}
                  <span style={{ color: '#6b7280' }}>{pending} pending</span>
                </span>
                <div className="batch-export-actions">
                  <button className="btn-outline" onClick={resetAll}>
                    Back to Upload
                  </button>
                  {jobId && (
                    <a
                      href={exportUrl(jobId)}
                      className="btn-primary"
                      style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', padding: '9px 20px' }}
                      download
                    >
                      Export Results
                    </a>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
