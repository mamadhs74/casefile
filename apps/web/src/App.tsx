import { Navigate, Route, Routes } from 'react-router';
import { AppShell } from './components/layout/AppShell';
import { CasesLibraryPage } from './pages/CasesLibraryPage';
import { CaseDetailPage } from './pages/CaseDetailPage';
import { StudioPage } from './pages/StudioPage';
import { PublishingPage } from './pages/PublishingPage';
import { AnalyticsPage } from './pages/AnalyticsPage';

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/cases" replace />} />
        <Route path="/cases" element={<CasesLibraryPage />} />
        <Route path="/cases/:caseId" element={<CaseDetailPage />} />
        <Route path="/studio" element={<StudioPage />} />
        <Route path="/publishing" element={<PublishingPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="*" element={<Navigate to="/cases" replace />} />
      </Routes>
    </AppShell>
  );
}
