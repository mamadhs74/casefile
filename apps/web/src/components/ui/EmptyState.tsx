import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description: string;
  action?: ReactNode;
  tone?: 'neutral' | 'error';
}

/** An invitation to act, not an apology — and for errors, what happened and what to do next. */
export function EmptyState({ title, description, action, tone = 'neutral' }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg border border-ink/10 bg-paper-raised px-6 py-8">
      <h2
        className={`font-sans text-base font-semibold ${tone === 'error' ? 'text-folder-rust' : 'text-ink'}`}
      >
        {title}
      </h2>
      <p className="max-w-prose text-sm text-ink-muted">{description}</p>
      {action}
    </div>
  );
}
