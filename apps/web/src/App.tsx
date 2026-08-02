import { Navigate, Route, Routes } from 'react-router';
import { AppShell } from './components/layout/AppShell';
import { SubjectsLibraryPage } from './pages/SubjectsLibraryPage';
import { NewSubjectPage } from './pages/NewSubjectPage';
import { SubjectDetailPage } from './pages/SubjectDetailPage';
import { StudioPage } from './pages/StudioPage';
import { PublishingPage } from './pages/PublishingPage';
import { AnalyticsPage } from './pages/AnalyticsPage';

export function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Navigate to="/subjects" replace />} />
        <Route path="/subjects" element={<SubjectsLibraryPage />} />
        <Route path="/subjects/new" element={<NewSubjectPage />} />
        <Route path="/subjects/:subjectId" element={<SubjectDetailPage />} />
        <Route path="/studio" element={<StudioPage />} />
        <Route path="/publishing" element={<PublishingPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="*" element={<Navigate to="/subjects" replace />} />
      </Routes>
    </AppShell>
  );
}
