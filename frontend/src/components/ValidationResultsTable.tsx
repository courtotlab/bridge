import type { ValidateCodeResult } from '../types/validator';

export function ValidationStatusBadge({ status }: { status: ValidateCodeResult['status'] | 'error' }) {
  if (status === 'valid') return <span className="val-badge val-badge--valid">✓ Valid</span>;
  if (status === 'deprecated') return <span className="val-badge val-badge--deprecated">⚠ Deprecated</span>;
  if (status === 'error') return <span className="val-badge val-badge--error">Error</span>;
  return <span className="val-badge val-badge--notfound">✗ Not found</span>;
}

interface ValidationResultsTableProps {
  rows: ValidateCodeResult[];
  showOntology?: boolean;
}

export default function ValidationResultsTable({ rows, showOntology = false }: ValidationResultsTableProps) {
  return (
    <div className="val-table-wrap">
      <table className="val-table">
        <thead>
          <tr>
            <th>Code</th>
            <th>Status</th>
            <th>Term</th>
            {showOntology && <th>Ontology</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.code}>
              <td className="val-code">{row.code}</td>
              <td><ValidationStatusBadge status={row.status} /></td>
              <td className="val-term">
                {row.term ?? <span className="val-dash">—</span>}
              </td>
              {showOntology && (
                <td className="val-term">
                  {row.ontology ?? <span className="val-dash">—</span>}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
