import './App.css';
import SettingsPanel from './components/SettingsPanel';
import SingleTermMappingPage from './pages/SingleTermMappingPage';

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">Bridge</h1>
        <span className="app-subtitle">Ontology Mapping Workspace</span>
      </header>
      <div className="app-body">
        <aside className="app-sidebar">
          <SettingsPanel />
        </aside>
        <main className="app-main">
          <SingleTermMappingPage />
        </main>
      </div>
    </div>
  );
}
