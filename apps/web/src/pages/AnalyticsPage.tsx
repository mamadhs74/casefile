import { EmptyState } from '../components/ui/EmptyState';

export function AnalyticsPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 font-sans text-2xl font-semibold text-ink">Analytics</h1>
      <EmptyState
        title="No metrics yet"
        description="Retention curves and cross-platform comparison arrive after the first episode publishes. There's nothing to report before then."
      />
    </div>
  );
}
