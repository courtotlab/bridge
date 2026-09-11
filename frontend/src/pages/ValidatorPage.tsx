import { useState } from 'react';

import { validateCodes } from '../api/validatorApi';
import ValidationResultsTable from '../components/ValidationResultsTable';
import { useSession } from '../context/SessionContext';
import type { ValidateCodeResult } from '../types/validator';
import { downloadValidationCsv } from '../utils/csvExport';
import './ValidatorPage.css';

function parseCodes(raw: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const part of raw.split(/[\n,]/)) {
    const code = part.trim();
    if (code && !seen.has(code)) {
      seen.add(code);
      out.push(code);
    }
  }
  return out;
}

export default function ValidatorPage() {
  const [rawInput, setRawInput] = useState('');
  const [results, setResults]   = useState<ValidateCodeResult[] | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const { startSession, emitEvent, completeSession } = useSession();

  async function handleCheck() {
    const codes = parseCodes(rawInput);
    if (!codes.length) return;

    setLoading(true);
    setError(null);

    let sid: string | null = null;
    try {
      sid = await startSession('validation', { codes });
      emitEvent(sid, {
        timestamp: new Date().toISOString(),
        actor: 'user',
        event_type: 'session_started',
        payload: { code_count: codes.length },
      }).catch(console.error);
    } catch {
      // session recording unavailable — continue without logging
    }

    try {
      const resp = await validateCodes({ codes });
      setResults(resp.results);
      if (sid) {
        const valid_count      = resp.results.filter(r => r.status === 'valid').length;
        const deprecated_count = resp.results.filter(r => r.status === 'deprecated').length;
        const not_found_count  = resp.results.filter(r => r.status === 'not-found').length;
        emitEvent(sid, {
          timestamp: new Date().toISOString(),
          actor: 'system',
          event_type: 'validation_complete',
          payload: { total: resp.results.length, valid_count, deprecated_count, not_found_count },
        }).catch(console.error);
        completeSession(sid, 'complete', { results: resp.results }).catch(console.error);
      }
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Something went wrong. Please try again.');
      if (sid) {
        emitEvent(sid, {
          timestamp: new Date().toISOString(),
          actor: 'system',
          event_type: 'session_error',
          payload: { message: detail ?? 'Unknown error' },
        }).catch(console.error);
        completeSession(sid, 'error').catch(console.error);
      }
    } finally {
      setLoading(false);
    }
  }

  const codeCount = parseCodes(rawInput).length;

  return (
    <div className="validator-page">
      <h1 className="page-title">Validator</h1>
      <p className="page-subtitle">
        Check whether ontology codes are valid, not found, or deprecated.
      </p>

      {/* ── Input card ──────────────────────────────────────────────────── */}
      <div className="card">
        <div className="field-group">
          <label className="field-label" htmlFor="val-code-input">
            Ontology codes
          </label>
          <textarea
            id="val-code-input"
            className="val-textarea"
            placeholder={'HP:0000822\nHP:9999999\nMONDO:0005180'}
            value={rawInput}
            rows={6}
            disabled={loading}
            onChange={e => {
              setRawInput(e.target.value);
              if (error) setError(null);
            }}
          />
          <p className="field-helper">
            One code per line or comma-separated. Duplicates are ignored.
            Maximum 200 codes per check.
          </p>
        </div>

        <button
          className="btn-primary"
          onClick={handleCheck}
          disabled={loading || codeCount === 0}
        >
          {loading ? (
            <><span className="spinner" aria-hidden="true" />Checking…</>
          ) : (
            '✓ Check codes'
          )}
        </button>
      </div>

      {/* ── Error ───────────────────────────────────────────────────────── */}
      {error && (
        <div className="search-alert search-alert--err" role="alert">
          {error}
          <button className="alert-link-btn val-dismiss" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      )}

      {/* ── Results ─────────────────────────────────────────────────────── */}
      {results !== null && !loading && (
        <div className="card">
          <div className="val-results-header">
            <h2 className="val-results-heading">Results</h2>
            <span className="val-count-badge">
              {results.length} code{results.length !== 1 ? 's' : ''} checked
            </span>
          </div>

          {results.length === 0 ? (
            <p className="val-empty">No codes to display.</p>
          ) : (
            <>
              <ValidationResultsTable rows={results} />

              <div className="val-footer">
                <button className="btn-outline" onClick={() => downloadValidationCsv(results)}>
                  ⬇ Download results
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
