import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import './App.css';
import Sidebar from './components/Sidebar';
import { SessionProvider } from './context/SessionContext';
import BatchPage from './pages/BatchPage';
import ExportPage from './pages/ExportPage';
import HistoryPage from './pages/HistoryPage';
import ReviewPage from './pages/ReviewPage';
import SearchPage from './pages/SearchPage';
import SettingsPage from './pages/SettingsPage';
import ValidatorPage from './pages/ValidatorPage';

export default function App() {
  return (
    <SessionProvider>
    <Router>
      <div className="app-shell">
        <Sidebar />
        <main className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/settings" replace />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/batch" element={<BatchPage />} />
            <Route path="/validator" element={<ValidatorPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/history" element={<HistoryPage />} />
            <Route path="/export" element={<ExportPage />} />
          </Routes>
        </main>
      </div>
    </Router>
    </SessionProvider>
  );
}
