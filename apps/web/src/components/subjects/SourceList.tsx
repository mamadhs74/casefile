import type { SourceRead } from '../../api/subjects';
import { sourceTierLabels } from '../../lib/domain';

/** A stack of retrieval slips, not a table — one card per source, scannable. */
export function SourceList({ sources }: { sources: SourceRead[] }) {
  if (sources.length === 0) {
    return <p className="text-sm text-ink-muted">No sources retrieved yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {sources.map((source) => (
        <li
          key={source.id}
          className="rounded-md border border-ink/10 bg-paper-raised px-4 py-3"
        >
          <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
            <a
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className="font-sans text-sm font-medium text-ink hover:text-ledger-blue"
            >
              {source.title}
            </a>
            <span className="shrink-0 rounded border border-ink/15 px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
              {sourceTierLabels[source.tier]}
            </span>
          </div>
          <p className="mt-1 font-mono text-xs text-ink-muted">
            {source.publisher} · {source.domain}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Retrieved {new Date(source.retrieved_at).toLocaleDateString()}
            {source.published_date &&
              ` · Published ${new Date(source.published_date).toLocaleDateString()}`}{' '}
            · {source.word_count.toLocaleString()} words
          </p>
        </li>
      ))}
    </ul>
  );
}
