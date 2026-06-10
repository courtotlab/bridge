import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { getStatus } from '../api/configApi';
import type { LayerStatus } from '../types/config';

const NAV_LINKS = [
  { label: 'Term Search', to: '/search' },
  { label: 'Batch Map', to: '/batch' },
  { label: 'Validator', to: '/validator' },
  { label: 'History', to: '/history' },
  { label: 'Settings', to: '/settings' },
];

const STATUS_ICON: Record<string, string> = {
  ok: '✅',
  warning: '🟡',
  disabled: '⚪',
  error: '🔴',
};

const STATUS_LABEL: Record<string, string> = {
  ok: 'Ready',
  warning: 'Warning',
  disabled: 'Disabled',
  error: 'Error',
};

const LAYER_STATUS_LABEL: Record<keyof LayerStatus, Partial<Record<string, string>>> = {
  layer1: {},
  layer2: { warning: 'Retrieval not checked' },
  layer3: {},
};

function layerStatusIcon(state: string): string {
  return STATUS_ICON[state] ?? STATUS_ICON.warning;
}

function layerStatusLabel(key: keyof LayerStatus, state: string): string {
  return LAYER_STATUS_LABEL[key][state] ?? STATUS_LABEL[state] ?? 'Unknown';
}

export default function Sidebar() {
  const [layerStatus, setLayerStatus] = useState<LayerStatus | null>(null);

  function fetchStatus() {
    getStatus()
      .then((r) => setLayerStatus(r.status))
      .catch(() => {});
  }

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30_000);
    window.addEventListener('bridge:status-refresh', fetchStatus);
    return () => {
      clearInterval(interval);
      window.removeEventListener('bridge:status-refresh', fetchStatus);
    };
  }, []);

  return (
    <nav className="sidebar">
      <div className="sidebar-brand">
        <span className="sidebar-brand-icon">⚕️</span>
        <span className="sidebar-brand-name">Bridge</span>
      </div>

      <ul className="sidebar-nav">
        {NAV_LINKS.map(({ label, to }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) => `sidebar-link ${isActive ? 'sidebar-link-active' : ''}`}
            >
              {label}
            </NavLink>
            {to === '/settings' && (
              <div className="sidebar-status-panel">
                <p className="sidebar-status-title">Pipeline</p>
                {(
                  [
                    { label: 'Layer 1 — NER', key: 'layer1' as const },
                    { label: 'Layer 2 — Retrieval', key: 'layer2' as const },
                    { label: 'Layer 3 — LLM', key: 'layer3' as const },
                  ] as const
                ).map(({ label: rowLabel, key }) => {
                  const state = layerStatus?.[key] ?? 'warning';
                  return (
                    <div key={key} className="sidebar-status-row">
                      <span className="sidebar-status-label">{rowLabel}</span>
                      <span className="sidebar-status-icon" title={layerStatusLabel(key, state)}>
                        {layerStatusIcon(state)}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
