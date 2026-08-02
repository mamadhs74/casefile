import { Link } from 'react-router';
import type { SubjectRead } from '../../api/subjects';
import { attributeSummary, resolutionStatusLabels, subjectStatusLabels } from '../../lib/domain';
import { TierTag } from './TierTag';
import { RiskFlag } from './RiskFlag';

export function SubjectCard({ item }: { item: SubjectRead }) {
  return (
    <Link
      to={`/subjects/${item.id}`}
      className="group relative flex flex-col overflow-hidden rounded-lg border border-ink/10 bg-paper-raised transition-colors hover:border-ledger-blue/40"
    >
      <TierTag tier={item.monetization_tier} variant="tab" />
      <div className="absolute right-3 top-2">
        <RiskFlag risk={item.legal_risk} compact />
      </div>
      <div className="flex flex-1 flex-col gap-2 px-4 py-3">
        <h3 className="font-sans text-sm font-semibold text-ink group-hover:text-ledger-blue">
          {item.title}
        </h3>
        <p className="font-mono text-xs text-ink-muted">
          {item.country} · {item.event_year} · {attributeSummary(item.attributes)}
        </p>
        <p className="line-clamp-2 text-sm text-ink-muted">{item.summary}</p>
        <div className="mt-auto flex flex-wrap items-center gap-x-2 gap-y-1 pt-2 text-xs text-ink-muted">
          <span>{resolutionStatusLabels[item.resolution_status]}</span>
          <span aria-hidden="true">·</span>
          <span>{subjectStatusLabels[item.status]}</span>
          {item.documentation_score != null && (
            <>
              <span aria-hidden="true">·</span>
              <span className="font-mono">Doc {item.documentation_score}</span>
            </>
          )}
        </div>
      </div>
    </Link>
  );
}
