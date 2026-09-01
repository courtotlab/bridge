import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cancelBatch,
  cancelBatchKeepalive,
  exportUrl,
  getBatchStatus,
  promoteAlternative as apiPromoteAlternative,
  setDecision as apiSetDecision,
  startBatch,
  uploadPreview,
} from '../api/batchApi';
import BatchResultsTable, { filterBatchRows, isUnmappedCode } from '../components/BatchResultsTable';
import OntologyMultiSelect from '../components/OntologyMultiSelect';
import StrictOntologyToggle from '../components/StrictOntologyToggle';
import { ONTOLOGY_OPTIONS } from '../constants/ontologies';
import { useSession } from '../context/SessionContext';
import type { AlternativeResult, BatchJobStatus, BatchRowResult, BatchUploadPreview } from '../types/mapping';
import { interruptActiveBatch, registerActiveBatchInterrupter, type BatchInterruptionOptions } from '../utils/activeBatchInterruption';
import { promoteBatchAlternative } from '../utils/batchPromotion';
import { BATCH_FILE_ACCEPT, isSupportedBatchFile, UNSUPPORTED_BATCH_FILE_MESSAGE } from '../utils/batchFiles';
import { detectColumnMappings } from '../utils/columnDetection';
import { effectiveStrictTargetOntology, targetOntologiesOrNull } from '../utils/ontologyPayloads';
import './BatchPage.css';

// ── Constants ────────────────────────────────────────────────────────────────

const COLUMN_ROLES = [
  { key: 'field_name', label: 'Field variable name', required: true },
  { key: 'label',      label: 'Human-readable label', required: false },
  { key: 'description', label: 'Description',         required: false },
  { key: 'data_type',  label: 'Data type',            required: false },
  {
    key: 'target_ontology',
    label: 'Target ontology',
    required: false,
    helperText: 'Choose a column when each row specifies its target ontology. Leave blank to use the Target ontologies options below.',
  },
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

function isTerminalBatchStatus(status: BatchJobStatus['status'] | undefined): boolean {
  return status === 'done' || status === 'interrupted' || status === 'failed';
}

function initialColumnMap(): Record<string, string | null> {
  return {
    field_name: null,
    label: null,
    description: null,
    data_type: null,
    target_ontology: null,
  };
}

// ── Step indicator ───────────────────────────────────────────────────────────

type Phase = 'upload' | 'running' | 'review' | 'exported';

interface BatchRunLifecycle {
  generation: number;
  jobId: string | null;
  startPending: boolean;
  startSent: boolean;
  abandoned: boolean;
  cancelRequested: boolean;
  cancelInFlight: Promise<boolean> | null;
}

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
  const [columnMap, setColumnMap] = useState<Record<string, string | null>>(initialColumnMap);
  const [targetOntologies, setTargetOntologies] = useState<string[]>([]);
  const [strictTargetOntology, setStrictTargetOntology] = useState(false);
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
  const [cancelling, setCancelling] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fileRef = useRef<File | null>(null);
  const previewRef = useRef<BatchUploadPreview | null>(null);
  const phaseRef = useRef<Phase>('upload');
  const jobIdRef = useRef<string | null>(null);
  const jobStatusRef = useRef<BatchJobStatus | null>(null);
  const interruptingRef = useRef(false);
  const cancellingRef = useRef(false);
  const runGenerationRef = useRef(0);
  const activeLifecycleRef = useRef<BatchRunLifecycle | null>(null);
  const mountedRef = useRef(true);
  const sessionFinalizedRef = useRef(false);

  const { startSession, emitEvent, completeSession } = useSession();
  const batchSessionIdRef = useRef<string | null>(null);
  const lastCompletedRef = useRef<number>(0);
  const [pollGeneration, setPollGeneration] = useState(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    fileRef.current = file;
  }, [file]);

  useEffect(() => {
    previewRef.current = preview;
  }, [preview]);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  useEffect(() => {
    jobIdRef.current = jobId;
  }, [jobId]);

  useEffect(() => {
    jobStatusRef.current = jobStatus;
  }, [jobStatus]);

  // ── Polling ────────────────────────────────────────────────────────────────

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const advanceRunGeneration = useCallback((updateState = true) => {
    const nextGeneration = runGenerationRef.current + 1;
    runGenerationRef.current = nextGeneration;
    if (updateState && mountedRef.current) {
      setPollGeneration(nextGeneration);
    }
    return nextGeneration;
  }, []);

  const invalidatePolling = useCallback((updateState = true) => {
    stopPoll();
    return advanceRunGeneration(updateState);
  }, [advanceRunGeneration, stopPoll]);

  const isCurrentRun = useCallback((expectedJobId: string, generation: number) => (
    jobIdRef.current === expectedJobId && runGenerationRef.current === generation
  ), []);

  const isCurrentLifecycle = useCallback((lifecycle: BatchRunLifecycle) => (
    activeLifecycleRef.current === lifecycle
    && runGenerationRef.current === lifecycle.generation
  ), []);

  const beginRunLifecycle = useCallback(() => {
    const generation = invalidatePolling();
    const lifecycle: BatchRunLifecycle = {
      generation,
      jobId: null,
      startPending: true,
      startSent: false,
      abandoned: false,
      cancelRequested: false,
      cancelInFlight: null,
    };
    activeLifecycleRef.current = lifecycle;
    return lifecycle;
  }, [invalidatePolling]);

  const requestLifecycleCancellation = useCallback((
    lifecycle: BatchRunLifecycle,
    options: BatchInterruptionOptions = {},
  ): Promise<boolean> => {
    const jobToCancel = lifecycle.jobId;
    if (!jobToCancel) return Promise.resolve(false);
    if (lifecycle.cancelRequested) return Promise.resolve(true);
    if (lifecycle.cancelInFlight) return lifecycle.cancelInFlight;

    if (options.keepalive) {
      const accepted = cancelBatchKeepalive(jobToCancel);
      lifecycle.cancelRequested = accepted;
      return Promise.resolve(accepted);
    }

    lifecycle.cancelInFlight = cancelBatch(jobToCancel)
      .then(() => {
        lifecycle.cancelRequested = true;
        return true;
      })
      .catch((err) => {
        console.error(err);
        cancelBatchKeepalive(jobToCancel);
        return false;
      })
      .finally(() => {
        lifecycle.cancelInFlight = null;
      });

    return lifecycle.cancelInFlight;
  }, []);

  const recordInterruptedSession = useCallback(async (
    sid: string | null,
    completed: number,
    total: number,
    reason: string,
  ) => {
    if (!sid || sessionFinalizedRef.current) return;
    sessionFinalizedRef.current = true;
    await emitEvent(sid, {
      timestamp: new Date().toISOString(),
      actor: reason === 'manual' ? 'user' : 'system',
      event_type: 'batch_interrupted',
      payload: { completed, total, reason },
    });
    await completeSession(sid, 'interrupted', {
      status: 'interrupted',
      completed,
      total,
    });
  }, [completeSession, emitEvent]);

  const recordCompletedSession = useCallback(async (
    sid: string | null,
    status: BatchJobStatus,
  ) => {
    if (!sid || sessionFinalizedRef.current) return;
    sessionFinalizedRef.current = true;
    const mapped = status.results.filter(r => !isUnmappedCode(r.suggested_code)).length;
    const unmapped = status.results.filter(r => isUnmappedCode(r.suggested_code)).length;
    await emitEvent(sid, {
      timestamp: new Date().toISOString(),
      actor: 'system',
      event_type: 'batch_mapping_complete',
      payload: { mapped, unmapped },
    });
  }, [emitEvent]);

  const applyBackendJobStatus = useCallback(async (
    status: BatchJobStatus,
    options: { expectedJobId?: string; generation?: number } = {},
  ) => {
    const stillCurrent = () => (
      !options.expectedJobId
      || options.generation === undefined
      || isCurrentRun(options.expectedJobId, options.generation)
    );
    if (!stillCurrent()) return;

    setJobStatus(status);
    jobStatusRef.current = status;

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

    if (status.status === 'done') {
      stopPoll();
      cancellingRef.current = false;
      setCancelling(false);
      try {
        await recordCompletedSession(sid, status);
      } catch (err) {
        console.error(err);
      }
      if (!stillCurrent()) return;
      phaseRef.current = 'review';
      setPhase('review');
      return;
    }

    if (status.status === 'interrupted') {
      stopPoll();
      cancellingRef.current = false;
      setCancelling(false);
      setError(null);
      phaseRef.current = 'review';
      setPhase('review');
      return;
    }

    if (status.status === 'failed') {
      stopPoll();
      cancellingRef.current = false;
      setCancelling(false);
      setError(status.error ?? 'Batch job failed.');
      phaseRef.current = 'upload';
      setPhase('upload');
    }
  }, [emitEvent, isCurrentRun, recordCompletedSession, stopPoll]);

  const interruptRegisteredBatch = useCallback(async (
    options: BatchInterruptionOptions = {},
  ): Promise<boolean> => {
    const lifecycle = activeLifecycleRef.current;
    const currentJobId = lifecycle?.jobId ?? jobIdRef.current;
    const currentStatus = jobStatusRef.current;
    const pendingStart = Boolean(lifecycle?.startPending);

    if (
      (!currentJobId && !pendingStart)
      || (!pendingStart && isTerminalBatchStatus(currentStatus?.status))
    ) {
      return false;
    }

    if (lifecycle) {
      lifecycle.abandoned = true;
    }
    interruptingRef.current = true;
    invalidatePolling(!options.keepalive && mountedRef.current);

    if (!currentJobId) {
      return true;
    }

    if (lifecycle) {
      return requestLifecycleCancellation(lifecycle, options);
    }

    if (options.keepalive) {
      return cancelBatchKeepalive(currentJobId);
    }

    try {
      await cancelBatch(currentJobId);
      return true;
    } catch (err) {
      console.error(err);
      cancelBatchKeepalive(currentJobId);
      return false;
    }
  }, [invalidatePolling, requestLifecycleCancellation]);

  useEffect(() => {
    const unregister = registerActiveBatchInterrupter(interruptRegisteredBatch);
    return () => {
      void interruptActiveBatch({ reason: 'unmount', keepalive: true }).finally(unregister);
    };
  }, [interruptRegisteredBatch]);

  useEffect(() => {
    const handlePageHide = () => {
      void interruptActiveBatch({ reason: 'pagehide', keepalive: true });
    };
    window.addEventListener('pagehide', handlePageHide);
    return () => {
      window.removeEventListener('pagehide', handlePageHide);
    };
  }, []);

  useEffect(() => {
    if (!jobId || phase !== 'running' || pollGeneration === 0) return;

    const pollingJobId = jobId;
    const generation = pollGeneration;

    pollRef.current = setInterval(async () => {
      try {
        const status = await getBatchStatus(pollingJobId);
        if (!isCurrentRun(pollingJobId, generation) || phaseRef.current !== 'running') {
          return;
        }
        applyBackendJobStatus(status, {
          expectedJobId: pollingJobId,
          generation,
        }).catch(console.error);
      } catch {
        // silently ignore transient poll errors
      }
    }, 1500);

    return stopPoll;
  }, [
    jobId,
    phase,
    pollGeneration,
    stopPoll,
    isCurrentRun,
    applyBackendJobStatus,
  ]);

  // ── File handling ──────────────────────────────────────────────────────────

  async function handleFileSelected(f: File) {
    if (!isSupportedBatchFile(f)) {
      setFile(null);
      setPreview(null);
      setError(UNSUPPORTED_BATCH_FILE_MESSAGE);
      return;
    }
    setFile(f);
    setError(null);
    setUploading(true);
    try {
      const prev = await uploadPreview(f);
      setPreview(prev);
      const detected = detectColumnMappings(prev.columns);
      setColumnMap({
        field_name: detected.sourceTerm ?? null,
        label: detected.sourceLabel ?? null,
        description: detected.description ?? null,
        data_type: detected.dataType ?? null,
        target_ontology: detected.targetOntology ?? null,
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
    setColumnMap(initialColumnMap());
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
    const lifecycle = beginRunLifecycle();
    setError(null);
    setStarting(true);
    const selectedOntologies = targetOntologiesOrNull(targetOntologies);
    const strictOntology = effectiveStrictTargetOntology(targetOntologies, strictTargetOntology);
    try {
      interruptingRef.current = false;
      cancellingRef.current = false;
      setCancelling(false);
      sessionFinalizedRef.current = false;
      let sid: string | null = null;
      try {
        sid = await startSession('batch_map', {
          filename: file.name,
          row_count: preview.row_count,
          target_ontology_column: columnMap.target_ontology || undefined,
          target_ontologies: selectedOntologies,
          auto_accept_threshold: autoAcceptThreshold / 100,
          strict_target_ontology: strictOntology,
        });
        batchSessionIdRef.current = sid;
      } catch {
        batchSessionIdRef.current = null;
      }

      if (lifecycle.abandoned || !mountedRef.current || !isCurrentLifecycle(lifecycle)) {
        if (!lifecycle.startSent && sid) {
          recordInterruptedSession(
            sid,
            0,
            preview.row_count,
            'navigation',
          ).catch(console.error);
        }
        return;
      }

      lifecycle.startSent = true;
      const { job_id } = await startBatch({
        file,
        columnMap,
        clinicalArea: null,
        targetOntologyColumn: columnMap.target_ontology,
        targetOntologies,
        useRag,
        autoAcceptThreshold: autoAcceptThreshold / 100,
        sessionId: sid,
        strictTargetOntology: strictOntology,
      });
      lifecycle.startPending = false;
      lifecycle.jobId = job_id;

      if (lifecycle.abandoned || !mountedRef.current || !isCurrentLifecycle(lifecycle)) {
        requestLifecycleCancellation(lifecycle, { reason: 'navigation' }).catch(console.error);
        return;
      }

      jobIdRef.current = job_id;
      setJobId(job_id);
      setLocalDecisions({});
      lastCompletedRef.current = 0;
      phaseRef.current = 'running';
      setPhase('running');

      if (sid) {
        emitEvent(sid, {
          timestamp: new Date().toISOString(),
          actor: 'user',
          event_type: 'batch_started',
          payload: {
            filename: file.name,
            row_count: preview.row_count,
            target_ontology_column: columnMap.target_ontology || null,
            target_ontologies: selectedOntologies,
            use_rag: useRag,
            auto_accept_threshold: autoAcceptThreshold / 100,
            strict_target_ontology: strictOntology,
          },
        }).catch(console.error);
      }
    } catch (e: unknown) {
      lifecycle.startPending = false;
      if (lifecycle.abandoned || !mountedRef.current || !isCurrentLifecycle(lifecycle)) {
        console.error(e);
        return;
      }
      setError(e instanceof Error ? e.message : 'Failed to start batch job.');
    } finally {
      if (mountedRef.current && isCurrentLifecycle(lifecycle)) {
        setStarting(false);
      }
    }
  }

  // ── Cancel ─────────────────────────────────────────────────────────────────

  const resumePollingForCurrentRun = useCallback(() => {
    cancellingRef.current = false;
    setCancelling(false);
    if (jobIdRef.current && phaseRef.current === 'running') {
      advanceRunGeneration();
    }
  }, [advanceRunGeneration]);

  const cancelCurrentBatchManually = useCallback(async (): Promise<boolean> => {
    const currentJobId = jobIdRef.current;
    const currentStatus = jobStatusRef.current;

    if (
      !currentJobId
      || phaseRef.current !== 'running'
      || isTerminalBatchStatus(currentStatus?.status)
    ) {
      return false;
    }
    if (cancellingRef.current) return true;

    cancellingRef.current = true;
    setCancelling(true);
    setError(null);
    const cancelGeneration = invalidatePolling();
    let cancelFailed = false;

    try {
      await cancelBatch(currentJobId);
    } catch {
      cancelFailed = true;
    }

    let confirmedStatus: BatchJobStatus | null = null;
    try {
      confirmedStatus = await getBatchStatus(currentJobId);
    } catch {
      confirmedStatus = null;
    }

    if (!isCurrentRun(currentJobId, cancelGeneration)) {
      return false;
    }

    if (confirmedStatus) {
      if (confirmedStatus.status === 'interrupted') {
        await applyBackendJobStatus(confirmedStatus, {
          expectedJobId: currentJobId,
          generation: cancelGeneration,
        });
        return true;
      }

      if (confirmedStatus.status === 'done' || confirmedStatus.status === 'failed') {
        await applyBackendJobStatus(confirmedStatus, {
          expectedJobId: currentJobId,
          generation: cancelGeneration,
        });
        return false;
      }

      setJobStatus(confirmedStatus);
      jobStatusRef.current = confirmedStatus;
      setError(cancelFailed
        ? 'Cancellation failed and the batch is still running. Try canceling again.'
        : 'Cancellation was requested, but the batch is still running. Try canceling again.');
      resumePollingForCurrentRun();
      return false;
    }

    setError('Could not confirm whether cancellation succeeded. The current results are still shown.');
    resumePollingForCurrentRun();
    return false;
  }, [
    applyBackendJobStatus,
    invalidatePolling,
    isCurrentRun,
    resumePollingForCurrentRun,
  ]);

  async function handleCancel() {
    await cancelCurrentBatchManually();
  }

  // ── Decision handling ──────────────────────────────────────────────────────

  function getEffectiveDecision(row: BatchRowResult): 'accepted' | 'rejected' | 'pending' {
    return localDecisions[row.row_index] ?? row.decision;
  }

  function replaceRowInStatus(
    status: BatchJobStatus,
    updatedRow: BatchRowResult,
  ): BatchJobStatus {
    return {
      ...status,
      results: status.results.map((row) => (
        row.row_index === updatedRow.row_index ? updatedRow : row
      )),
    };
  }

  async function handlePromoteAlternative(row: BatchRowResult, alt: AlternativeResult) {
    if (!jobId || !jobStatus) return;

    const previousStatus = jobStatus;
    const promotedRow = promoteBatchAlternative(row, alt);
    const optimisticStatus = replaceRowInStatus(previousStatus, promotedRow);

    setJobStatus(optimisticStatus);
    setLocalDecisions((prev) => ({ ...prev, [row.row_index]: 'pending' }));

    try {
      const persistedRow = await apiPromoteAlternative(jobId, row.row_index, alt);
      const nextStatus = replaceRowInStatus(optimisticStatus, persistedRow);
      setJobStatus(nextStatus);
      jobStatusRef.current = nextStatus;

      const sid = batchSessionIdRef.current;
      if (sid) {
        emitEvent(sid, {
          timestamp: new Date().toISOString(),
          actor: 'user',
          event_type: 'alternative_promoted',
          payload: {
            row_index: row.row_index,
            field_name: row.field_name,
            promoted_code: alt.code,
            demoted_code: row.suggested_code,
          },
        }).catch(console.error);
        if (nextStatus.status === 'done') {
          completeSession(sid, 'complete', nextStatus).catch(console.error);
        }
      }
    } catch {
      setJobStatus(previousStatus);
      setLocalDecisions((prev) => {
        const next = { ...prev };
        if (row.decision === 'pending') {
          delete next[row.row_index];
        } else {
          next[row.row_index] = row.decision;
        }
        return next;
      });
      setError('Could not update the suggested mapping. Try again.');
    }
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
      } else if (type === 'reject_unmapped' && isUnmappedCode(row.suggested_code)) {
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
    invalidatePolling();
    cancellingRef.current = false;
    setCancelling(false);
    setFile(null);
    setPreview(null);
    setColumnMap(initialColumnMap());
    setTargetOntologies([]);
    setStrictTargetOntology(false);
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
    fileRef.current = null;
    previewRef.current = null;
    phaseRef.current = 'upload';
    jobIdRef.current = null;
    jobStatusRef.current = null;
    interruptingRef.current = false;
    cancellingRef.current = false;
    sessionFinalizedRef.current = false;
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

  const filteredResults = filterBatchRows(results, getEffectiveDecision, filterStatus, searchQuery);

  const completed = jobStatus?.completed ?? 0;
  const total = jobStatus?.total ?? preview?.row_count ?? 0;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const isRunning = phase === 'running' && jobStatus?.status === 'running';
  const lastField = results[results.length - 1]?.field_name ?? '';
  const targetOntologyColumnActive = Boolean(columnMap.target_ontology);

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="batch-page">
      <h1 className="page-title">Batch Data Dictionary Mapping</h1>
      <p className="batch-subtitle">
        Upload your data dictionary, let the AI map all fields, then review and export.
      </p>

      <div className="batch-warning-note" role="note">
        <span className="batch-warning-icon" aria-hidden="true">!</span>
        <span>
          Stay on this page until batch mapping is complete. Leaving this page will interrupt the run and discard all mapping results.
        </span>
      </div>

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
                  <div className="batch-upload-sub">CSV, TSV, or XLSX</div>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept={BATCH_FILE_ACCEPT}
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
                    {'helperText' in role && role.helperText && (
                      <p className="batch-col-map-helper">{role.helperText}</p>
                    )}
                  </>
                ))}
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
                  disabled={targetOntologyColumnActive}
                  helperText={
                    targetOntologyColumnActive
                      ? 'Per-row target ontologies are active. These options will be ignored unless Target ontology is set to "none."'
                      : 'Selected ontologies restrict the mapping results. Leave all unselected for automatic selection.'
                  }
                />
              </div>

              {targetOntologies.includes('EFO') && (
                <div style={{ marginBottom: 16 }}>
                  <StrictOntologyToggle
                    checked={strictTargetOntology}
                    onChange={setStrictTargetOntology}
                  />
                </div>
              )}

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
                <button className="btn-outline" onClick={handleCancel} disabled={cancelling}>
                  {cancelling ? 'Cancelling...' : 'Cancel'}
                </button>
              </div>
            </div>
          )}

          {/* Review table */}
          {results.length > 0 && (
            <div className="card">
              <h2 className="batch-section-heading">Review and Approve Mappings</h2>
              <BatchResultsTable
                rows={results}
                expandedRows={expandedRows}
                filterStatus={filterStatus}
                searchQuery={searchQuery}
                autoAcceptThreshold={autoAcceptThreshold}
                isRunning={isRunning}
                getDecision={getEffectiveDecision}
                onFilterStatusChange={setFilterStatus}
                onSearchQueryChange={setSearchQuery}
                onToggleExpand={toggleExpand}
                onToggleDecision={toggleDecision}
                onBulkDecision={bulkDecision}
                onPromoteAlternative={handlePromoteAlternative}
              />

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
