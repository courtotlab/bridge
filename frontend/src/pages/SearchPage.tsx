import { isAxiosError } from 'axios';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getConfig } from '../api/configApi';
import { mapSingleTerm } from '../api/mappingApi';
import OntologyMultiSelect from '../components/OntologyMultiSelect';
import TermSearchResultView from '../components/TermSearchResultView';
import { ONTOLOGY_OPTIONS } from '../constants/ontologies';
import { useSession } from '../context/SessionContext';
import type { AlternativeResult, SingleMappingResponse } from '../types/mapping';
import { downloadTermMappingCsv } from '../utils/csvExport';
import { targetOntologiesOrNull } from '../utils/ontologyPayloads';

// ── Constants ────────────────────────────────────────────────────────────────

const DATA_TYPE_OPTIONS = ['Numeric', 'Text', 'Boolean', 'Date', 'Categorical', 'Other'];

const CLINICAL_AREA_OPTIONS = [
  'Phenotype/Symptom',
  'Disease/Condition',
  'Lab/Measurement',
  'Medication',
  'Demographic',
  'Other',
];

const SINGLE_TERM_RESULT_STORAGE_KEY = 'bridge:single-term-result';

// ── Helpers ──────────────────────────────────────────────────────────────────

function isNoResult(response: SingleMappingResponse): boolean {
  return (
    response.confidence < 0.1 ||
    !response.target_code ||
    response.target_code === 'UNMAPPED'
  );
}

interface StoredSingleTermResultState {
  bestMatch: SingleMappingResponse;
  altList: AlternativeResult[];
}

function readStoredResultState(): StoredSingleTermResultState | null {
  try {
    const raw = window.sessionStorage.getItem(SINGLE_TERM_RESULT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredSingleTermResultState>;
    if (!parsed.bestMatch) return null;
    return {
      bestMatch: parsed.bestMatch,
      altList: Array.isArray(parsed.altList) ? parsed.altList : [],
    };
  } catch {
    return null;
  }
}

function writeStoredResultState(state: StoredSingleTermResultState): void {
  try {
    window.sessionStorage.setItem(SINGLE_TERM_RESULT_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Session persistence is a convenience; mapping results still render in memory.
  }
}

function clearStoredResultState(): void {
  try {
    window.sessionStorage.removeItem(SINGLE_TERM_RESULT_STORAGE_KEY);
  } catch {
    // Ignore unavailable storage.
  }
}

// ── Main component ───────────────────────────────────────────────────────────

type PageError =
  | { kind: 'not_configured' }
  | { kind: 'unreachable' }
  | { kind: 'timeout' }
  | { kind: 'generic'; message: string };

export default function SearchPage() {
  const navigate = useNavigate();

  // Form state
  const [sourceTerm, setSourceTerm] = useState('');
  const [sourceLabel, setSourceLabel] = useState('');
  const [description, setDescription] = useState('');
  const [dataType, setDataType] = useState('');
  const [clinicalArea, setClinicalArea] = useState('');
  const [targetOntologies, setTargetOntologies] = useState<string[]>([]);
  const [termError, setTermError] = useState('');

  // Request state
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState<PageError | null>(null);

  // Result state
  const [storedResultState] = useState(() => readStoredResultState());
  const [bestMatch, setBestMatch] = useState<SingleMappingResponse | null>(
    () => storedResultState?.bestMatch ?? null,
  );
  const [altList, setAltList] = useState<AlternativeResult[]>(
    () => storedResultState?.altList ?? [],
  );

  // Copy button state
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { startSession, emitEvent, completeSession } = useSession();
  const sessionIdRef = useRef<string | null>(null);

  // On mount: check pipeline is configured
  useEffect(() => {
    getConfig()
      .then((cfg) => {
        if (!cfg.provider || !cfg.model) {
          setPageError({ kind: 'not_configured' });
        }
      })
      .catch(() => {
        // Backend unreachable — let them try to search; error will surface on submit
      });
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!sourceTerm.trim()) {
      setTermError('Field name is required.');
      return;
    }
    setTermError('');
    setPageError(null);
    clearStoredResultState();
    setBestMatch(null);
    setAltList([]);
    setLoading(true);

    const selectedOntologies = targetOntologiesOrNull(targetOntologies);

    try {
      const sid = await startSession('term_search', {
        term: sourceTerm.trim(),
        clinical_area: clinicalArea || undefined,
        target_ontologies: selectedOntologies,
      });
      sessionIdRef.current = sid;
      emitEvent(sid, {
        timestamp: new Date().toISOString(),
        actor: 'user',
        event_type: 'session_started',
        payload: {
          term: sourceTerm.trim(),
          clinical_area: clinicalArea || null,
          target_ontologies: selectedOntologies,
        },
      }).catch(console.error);
    } catch {
      sessionIdRef.current = null;
    }

    mapSingleTerm({
      source_term: sourceTerm.trim(),
      source_label: sourceLabel.trim() || undefined,
      source_description: description.trim() || undefined,
      source_type: dataType || undefined,
      entity_type: clinicalArea || undefined,
      target_ontologies: selectedOntologies,
    })
      .then((res) => {
        // Sort alternatives by confidence descending
        const sorted = [...res.alternatives].sort((a, b) => b.confidence - a.confidence);
        setBestMatch(res);
        setAltList(sorted);
        writeStoredResultState({ bestMatch: res, altList: sorted });
        const sid = sessionIdRef.current;
        if (sid) {
          emitEvent(sid, {
            timestamp: new Date().toISOString(),
            actor: 'system',
            event_type: 'mapping_complete',
            payload: {
              code: res.target_code,
              term: res.target_term,
              confidence: res.confidence,
              logic_type: res.logic_type,
              retrieval_mode: res.retrieval_mode ?? null,
            },
          }).catch(console.error);
          completeSession(sid, 'complete', res).catch(console.error);
        }
      })
      .catch((err) => {
        if (isAxiosError(err)) {
          const status = err.response?.status;
          const detail: string = err.response?.data?.detail ?? '';
          if (
            status === 422 &&
            detail.toLowerCase().includes('configured')
          ) {
            setPageError({ kind: 'not_configured' });
          } else if (
            status === 503 &&
            detail.toLowerCase().includes('timed out')
          ) {
            setPageError({ kind: 'timeout' });
          } else if (status === 503) {
            setPageError({ kind: 'unreachable' });
          } else {
            setPageError({ kind: 'generic', message: detail || 'An unexpected error occurred.' });
          }
        } else {
          setPageError({ kind: 'generic', message: 'An unexpected error occurred.' });
        }
        const sid = sessionIdRef.current;
        if (sid) {
          const message = isAxiosError(err)
            ? (err.response?.data?.detail ?? 'Unknown error')
            : 'An unexpected error occurred.';
          emitEvent(sid, {
            timestamp: new Date().toISOString(),
            actor: 'system',
            event_type: 'session_error',
            payload: { message },
          }).catch(console.error);
          completeSession(sid, 'error').catch(console.error);
        }
      })
      .finally(() => setLoading(false));
  }

  function handleCopy() {
    if (!bestMatch) return;
    navigator.clipboard.writeText(bestMatch.target_code).then(() => {
      setCopied(true);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }

  function handlePromote(alt: AlternativeResult) {
    if (!bestMatch) return;
    // Build a synthetic response for the promoted alternative.
    // configured_provider/configured_model/retrieval_mode are inherited via spread —
    // they come from config, not from the individual result, so they stay stable.
    const promoted: SingleMappingResponse = {
      ...bestMatch,
      target_code: alt.code,
      target_term: alt.term,
      ontology: alt.ontology,
      confidence: alt.confidence,
      logic_type: alt.source ?? bestMatch.logic_type,
      notes: undefined,
      explanation: alt.explanation,
    };
    // Demote current best match into alternatives
    const demoted: AlternativeResult = {
      code: bestMatch.target_code,
      term: bestMatch.target_term,
      ontology: bestMatch.ontology,
      confidence: bestMatch.confidence,
      source: bestMatch.logic_type,
      explanation: bestMatch.explanation ?? bestMatch.notes,
    };
    const newAlts = [
      demoted,
      ...altList.filter((a) => a.code !== alt.code),
    ].sort((a, b) => b.confidence - a.confidence);
    setBestMatch(promoted);
    setAltList(newAlts);
    writeStoredResultState({ bestMatch: promoted, altList: newAlts });
    setCopied(false);

    const sid = sessionIdRef.current;
    if (sid) {
      emitEvent(sid, {
        timestamp: new Date().toISOString(),
        actor: 'user',
        event_type: 'alternative_promoted',
        payload: { promoted_code: alt.code, demoted_code: bestMatch.target_code },
      }).catch(console.error);
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const formDisabled = loading;

  return (
    <div className="search-page">
      <h1 className="page-title">Search for an Ontology Code</h1>
      <p className="page-subtitle">
        Type a clinical variable or description to find its standard code.
      </p>

      {/* ── Input form card ─────────────────────────────────────────────── */}
      <div className="card search-form-card">
        <form onSubmit={handleSubmit} noValidate>

          {/* Field name */}
          <div className="field-group">
            <label className="field-label" htmlFor="source-term">
              Field name / variable <span className="required-mark">*</span>
            </label>
            <input
              id="source-term"
              className={`form-input${termError ? ' form-input--error' : ''}`}
              type="text"
              placeholder="systolic_blood_pressure"
              value={sourceTerm}
              onChange={(e) => { setSourceTerm(e.target.value); setTermError(''); }}
              disabled={formDisabled}
              autoComplete="off"
            />
            {termError && <p className="field-error">{termError}</p>}
            <p className="field-helper">
              The variable name from your dataset (e.g. sbp_avg)
            </p>
          </div>

          {/* Human-readable label */}
          <div className="field-group">
            <label className="field-label" htmlFor="source-label">
              The label of the field/variable from your dataset{' '}
              <span className="optional-mark">(optional)</span>
            </label>
            <input
              id="source-label"
              className="form-input"
              type="text"
              placeholder="Systolic Blood Pressure"
              value={sourceLabel}
              onChange={(e) => setSourceLabel(e.target.value)}
              disabled={formDisabled}
              autoComplete="off"
            />
            <p className="field-helper">
              The column header your team uses (e.g. Systolic BP (mmHg))
            </p>
          </div>

          {/* Description */}
          <div className="field-group">
            <label className="field-label" htmlFor="description">
              Description{' '}
              <span className="optional-mark">(optional)</span>
            </label>
            <input
              id="description"
              className="form-input"
              type="text"
              placeholder="Measured in mmHg at rest ..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={formDisabled}
              autoComplete="off"
            />
          </div>

          {/* Data type + Clinical area row */}
          <div className="search-form-row">
            <div className="field-group">
              <label className="field-label" htmlFor="data-type">
                Data type{' '}
                <span className="optional-mark">(optional)</span>
              </label>
              <select
                id="data-type"
                className="form-select"
                value={dataType}
                onChange={(e) => setDataType(e.target.value)}
                disabled={formDisabled}
              >
                <option value="">— select —</option>
                {DATA_TYPE_OPTIONS.map((o) => (
                  <option key={o} value={o.toLowerCase()}>
                    {o}
                  </option>
                ))}
              </select>
            </div>

            <div className="field-group">
              <label className="field-label" htmlFor="clinical-area">
                Clinical area{' '}
                <span className="optional-mark">(optional)</span>
              </label>
              <select
                id="clinical-area"
                className="form-select"
                value={clinicalArea}
                onChange={(e) => setClinicalArea(e.target.value)}
                disabled={formDisabled}
              >
                <option value="">— select —</option>
                {CLINICAL_AREA_OPTIONS.map((o) => (
                  <option key={o} value={o.toLowerCase().replace(/\//g, '_')}>
                    {o}
                  </option>
                ))}
              </select>
              <p className="field-helper-sm">
                {CLINICAL_AREA_OPTIONS.join(', ')}
              </p>
            </div>
          </div>

          {/* Target ontologies */}
          <div className="field-group">
            <OntologyMultiSelect
              label="Target ontologies"
              options={ONTOLOGY_OPTIONS}
              selectedValues={targetOntologies}
              onChange={setTargetOntologies}
              disabled={formDisabled}
              helperText="Selected ontologies restrict the mapping results. Leave all unselected for automatic selection."
            />
          </div>

          {/* Submit */}
          <div className="search-form-actions">
            <button
              type="submit"
              className="btn-primary"
              disabled={formDisabled}
            >
              {loading ? (
                <>
                  <span className="spinner" aria-hidden="true" /> Searching…
                </>
              ) : (
                '🔍 Search'
              )}
            </button>
          </div>
        </form>
      </div>

      {/* ── Error states ────────────────────────────────────────────────── */}
      {pageError && (
        <div className={`search-alert search-alert--${pageError.kind === 'not_configured' ? 'warn' : 'err'}`}>
          {pageError.kind === 'not_configured' && (
            <>
              Pipeline not configured — go to{' '}
              <button
                className="alert-link-btn"
                onClick={() => navigate('/settings')}
              >
                Settings
              </button>{' '}
              and save your configuration before searching.
            </>
          )}
          {pageError.kind === 'unreachable' && (
            'Could not reach the AI provider — check your connection settings and try again.'
          )}
          {pageError.kind === 'timeout' && (
            'The search timed out. Try again or check that your AI provider is running.'
          )}
          {pageError.kind === 'generic' && pageError.message}
        </div>
      )}

      {/* ── No result state ─────────────────────────────────────────────── */}
      {bestMatch && isNoResult(bestMatch) && (
        <div className="search-alert search-alert--warn">
          ⚠️ No confident match found. Try adding a human-readable label or description to improve results.
        </div>
      )}

      {/* ── Results ─────────────────────────────────────────────────────── */}
      {bestMatch && !isNoResult(bestMatch) && (
        <TermSearchResultView
          bestMatch={bestMatch}
          alternatives={altList}
          copied={copied}
          onCopy={handleCopy}
          onDownloadCsv={() => downloadTermMappingCsv(bestMatch)}
          onPromote={handlePromote}
        />
      )}
    </div>
  );
}
