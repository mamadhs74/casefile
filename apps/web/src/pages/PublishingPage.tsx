import { EmptyState } from '../components/ui/EmptyState';

export function PublishingPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 font-sans text-2xl font-semibold text-ink">Publishing</h1>
      <EmptyState
        title="No publish targets built yet"
        description="YouTube, TikTok, and Instagram adapters aren't built. Once a render clears Gate B, uploads and per-platform metadata will live here."
      />
    </div>
  );
}
