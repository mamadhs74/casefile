import { EmptyState } from '../components/ui/EmptyState';

export function StudioPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-6 font-sans text-2xl font-semibold text-ink">Studio</h1>
      <EmptyState
        title="Nothing to produce yet"
        description="Script generation, voice synthesis, and rendering aren't built. Once a case clears Gate A, its script, shot list, and voiceover will live here."
      />
    </div>
  );
}
