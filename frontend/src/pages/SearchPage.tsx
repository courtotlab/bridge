import { isAxiosError } from 'axios';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getConfig } from '../api/configApi';
import { mapSingleTerm } from '../api/mappingApi';
import type { AlternativeResult, SingleMappingResponse } from '../types/mapping';

// ── Constants ────────────────────────────────────────────────────────────────

const ONTOLOGY_FULL_NAMES: Record<string, string> = {
  HPO: 'Human Phenotype Ontology',
  MONDO: 'Monarch Disease Ontology',
  NCIT: 'NCI Thesaurus',
  LOINC: 'Logical Observation Identifiers Names and Codes',
  ICD10: 'International Classification of Diseases, 10th Revision',
  CHEBI: 'Chemical Entities of Biological Interest',
  SNOMED: 'SNOMED Clinical Terms',
  RXNORM: 'RxNorm',
};

const LOGIC_TYPE_TOOLTIPS: Record<string, string> = {
  llm: 'AI selected this code from candidates',
  rag: 'Retrieved directly from ontology database',
  direct: 'Exact match found',
  hybrid: 'AI reasoning combined with database retrieval',
};

const DATA_TYPE_OPTIONS = ['Numeric', 'Text', 'Boolean', 'Date', 'Categorical', 'Other'];

const CLINICAL_AREA_OPTIONS = [
  'Phenotype/Symptom',
  'Disease/Condition',
  'Lab/Measurement',
  'Medication',
  'Demographic',
  'Other',
];

const ONTOLOGY_OPTIONS = [
  'Auto-detect',
  'HPO',
  'MONDO',
  'NCIT',
  'LOINC',
  'ICD10',
  'CHEBI',
  'SNOMED',
  'RxNorm',
];

// ── Helpers ──────────────────────────────────────────────────────────────────

function getOntologyName(code: string): string {
  return ONTOLOGY_FULL_NAMES[code.toUpperCase()] ?? code;
}

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

function isNoResult(response: SingleMappingResponse): boolean {
  return (
    response.confidence < 0.1 ||
    !response.target_code ||
    response.target_code === 'UNMAPPED'
  );
}

function buildCsv(response: SingleMappingResponse): string {
  const headers = [
    'source_term',
    'source_label',
    'source_type',
    'target_code',
    'target_term',
    'ontology',
    'confidence',
    'logic_type',
    'notes',
  ];
  const escape = (v: string | number | undefined | null) => {
    if (v === null || v === undefined) return '';
    const s = String(v);
    return s.includes(',') || s.includes('"') || s.includes('\n')
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };
  const row = [
    response.source_term,
    response.source_label,
    response.source_type,
    response.target_code,
    response.target_term,
    response.ontology,
    response.confidence,
    response.logic_type,
    response.notes,
  ].map(escape);
  return `${headers.join(',')}\n${row.join(',')}`;
}

function downloadCsv(response: SingleMappingResponse): void {
  const csv = buildCsv(response);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${response.source_term}_mapping.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Sub-components ───────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const tier = getConfidenceTier(confidence);
  const label = getConfidenceLabel(confidence);
  const pct = Math.round(confidence * 100);
  return (
    <span className={`confidence-badge confidence-badge--${tier}`}>
      ● {pct}% {label}
    </span>
  );
}

function LogicTypeWithTooltip({ logicType }: { logicType: string }) {
  const tooltip = LOGIC_TYPE_TOOLTIPS[logicType.toLowerCase()] ?? logicType;
  return (
    <span className="logic-type-wrap">
      Method: <strong>{logicType}</strong>{' '}
      <span className="logic-type-tooltip" title={tooltip} aria-label={tooltip}>
        ℹ️
      </span>
    </span>
  );
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
  const [targetOntology, setTargetOntology] = useState('Auto-detect');
  const [termError, setTermError] = useState('');

  // Request state
  const [loading, setLoading] = useState(false);
  const [pageError, setPageError] = useState<PageError | null>(null);

  // Result state
  const [bestMatch, setBestMatch] = useState<SingleMappingResponse | null>(null);
  const [altList, setAltList] = useState<AlternativeResult[]>([]);

  // Copy button state
  const [copied, setCopied] = useState(false);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!sourceTerm.trim()) {
      setTermError('Field name is required.');
      return;
    }
    setTermError('');
    setPageError(null);
    setBestMatch(null);
    setAltList([]);
    setLoading(true);

    const onto =
      targetOntology === 'Auto-detect' ? undefined : targetOntology.toUpperCase();

    mapSingleTerm({
      source_term: sourceTerm.trim(),
      source_label: sourceLabel.trim() || undefined,
      source_type: dataType || undefined,
      entity_type: clinicalArea || undefined,
      target_ontologies: onto,
    })
      .then((res) => {
        // Sort alternatives by confidence descending
        const sorted = [...res.alternatives].sort((a, b) => b.confidence - a.confidence);
        setBestMatch(res);
        setAltList(sorted);
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
    // Build a synthetic response for the promoted alternative
    const promoted: SingleMappingResponse = {
      ...bestMatch,
      target_code: alt.code,
      target_term: alt.term,
      ontology: alt.ontology,
      confidence: alt.confidence,
      logic_type: alt.source ?? bestMatch.logic_type,
      notes: undefined,
    };
    // Demote current best match into alternatives
    const demoted: AlternativeResult = {
      code: bestMatch.target_code,
      term: bestMatch.target_term,
      ontology: bestMatch.ontology,
      confidence: bestMatch.confidence,
      source: bestMatch.logic_type,
    };
    const newAlts = [
      demoted,
      ...altList.filter((a) => a.code !== alt.code),
    ].sort((a, b) => b.confidence - a.confidence);
    setBestMatch(promoted);
    setAltList(newAlts);
    setCopied(false);
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
              Human-readable label{' '}
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
            <label className="field-label" htmlFor="target-ontology">
              Target ontologies{' '}
              <span className="optional-mark">(optional)</span>
            </label>
            <select
              id="target-ontology"
              className="form-select"
              value={targetOntology}
              onChange={(e) => setTargetOntology(e.target.value)}
              disabled={formDisabled}
            >
              {ONTOLOGY_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
            <p className="field-helper">
              Auto-detect chooses HPO, MONDO, NCIT, LOINC based on the clinical area.
            </p>
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
        <div className="search-results">

          {/* Best match card */}
          <div className="card result-card">
            <div className="result-card-header">
              <span className="result-card-title-label">Best match</span>
              <ConfidenceBadge confidence={bestMatch.confidence} />
            </div>

            <p className="result-code-term">
              {bestMatch.target_code} · {bestMatch.target_term}
            </p>

            <p className="result-meta-line">
              Ontology: {getOntologyName(bestMatch.ontology)}
            </p>
            <p className="result-meta-line">
              <LogicTypeWithTooltip logicType={bestMatch.logic_type} />
            </p>

            {bestMatch.notes && (
              <blockquote className="result-notes">{bestMatch.notes}</blockquote>
            )}

            <div className="result-actions">
              <button
                className="btn-outline"
                onClick={handleCopy}
              >
                {copied ? '✅ Copied!' : `📋 Copy code: ${bestMatch.target_code}`}
              </button>
              <button
                className="btn-outline"
                onClick={() => downloadCsv(bestMatch)}
              >
                💾 Download as CSV
              </button>
            </div>
          </div>

          {/* Alternatives table */}
          {altList.length > 0 && (
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
                  {altList.map((alt) => (
                    <tr
                      key={alt.code}
                      className="alternatives-row"
                      onClick={() => handlePromote(alt)}
                      tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && handlePromote(alt)}
                      role="button"
                      aria-label={`Promote ${alt.code} to best match`}
                    >
                      <td className="alt-code">{alt.code}</td>
                      <td>{alt.term}</td>
                      <td>
                        <ConfidenceBadge confidence={alt.confidence} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="field-helper-sm" style={{ marginTop: 8 }}>
                Click any row to promote it to the best-match card.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
