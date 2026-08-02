import { Link, useParams } from 'react-router';
import {
  useStrategies,
  useSubject,
  useSubjectGate,
  useSubjectNoun,
  useSubjectSources,
} from '../api/queries';
import { attributeSummary, humanize, resolutionStatusLabels, subjectStatusLabels } from '../lib/domain';
import { TierTag } from '../components/subjects/TierTag';
import { RiskFlag } from '../components/subjects/RiskFlag';
import { GateStatus } from '../components/subjects/GateStatus';
import { SourceList } from '../components/subjects/SourceList';
import { EmptyState } from '../components/ui/EmptyState';
import { Skeleton } from '../components/ui/Skeleton';

export function SubjectDetailPage() {
  const params = useParams<{ subjectId: string }>();
  const subjectId = Number(params.subjectId);

  const subjectQuery = useSubject(subjectId);
  const gateQuery = useSubjectGate(subjectId);
  const sourcesQuery = useSubjectSources(subjectId);
  const { data: strategies } = useStrategies();
  const noun = useSubjectNoun();

  if (subjectQuery.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-2/3" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (subjectQuery.isError || !subjectQuery.data) {
    return (
      <EmptyState
        tone="error"
        title="Not found"
        description={
          subjectQuery.error instanceof Error
            ? subjectQuery.error.message
            : "This doesn't exist, or has been removed."
        }
        action={
          <Link to="/subjects" className="text-sm font-semibold text-ledger-blue">
            Back to {noun.plural}
          </Link>
        }
      />
    );
  }

  const item = subjectQuery.data;
  const strategy = strategies?.find((s) => s.id === item.strategy_id);
  const pluralNoun = strategy?.subject_noun_plural ?? noun.plural;

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <Link to="/subjects" className="text-sm text-ink-muted hover:text-ledger-blue">
        ← Back to {pluralNoun}
      </Link>

      <div className="overflow-hidden rounded-lg border border-ink/10 bg-paper-raised">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TierTag tier={item.monetization_tier} variant="tab" />
          <div className="pr-4">
            <RiskFlag risk={item.legal_risk} />
          </div>
        </div>
        <div className="flex flex-col gap-3 px-5 py-4">
          <h1 className="font-sans text-xl font-semibold text-ink">{item.title}</h1>
          <p className="font-mono text-xs text-ink-muted">
            {item.country}
            {item.region ? `, ${item.region}` : ''} · {item.event_year} ·{' '}
            {attributeSummary(item.attributes)}
          </p>
          <p className="text-sm text-ink">{item.summary}</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
            <span>{resolutionStatusLabels[item.resolution_status]}</span>
            <span>{subjectStatusLabels[item.status]}</span>
            {item.documentation_score != null && (
              <span className="font-mono">Documentation score {item.documentation_score}</span>
            )}
            {item.estimated_runtime_min != null && (
              <span className="font-mono">~{item.estimated_runtime_min} min runtime</span>
            )}
            {item.living_persons_involved && <span>Living persons involved</span>}
          </div>
          {item.risk_flags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {item.risk_flags.map((flag) => (
                <span
                  key={flag}
                  className="rounded border border-ink/15 px-1.5 py-0.5 font-mono text-[11px] text-ink-muted"
                >
                  {humanize(flag)}
                </span>
              ))}
            </div>
          )}
          {item.eligibility_notes.length > 0 && (
            <ul className="flex flex-col gap-1 border-t border-ink/10 pt-3 text-sm text-ink-muted">
              {item.eligibility_notes.map((note, i) => (
                <li key={i}>· {note}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="font-sans text-sm font-semibold uppercase tracking-wide text-ink">
          Source gate
        </h2>
        {gateQuery.isLoading && <Skeleton className="h-24 w-full" />}
        {gateQuery.isError && (
          <EmptyState
            tone="error"
            title="Couldn't load the gate result"
            description={
              gateQuery.error instanceof Error ? gateQuery.error.message : 'Something went wrong.'
            }
          />
        )}
        {gateQuery.data && strategy && (
          <GateStatus
            gate={gateQuery.data}
            minVerifiedSources={strategy.min_verified_sources}
            minPrimaryRecords={strategy.min_primary_records}
            minDistinctDomains={strategy.min_distinct_domains}
          />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-baseline gap-2">
          <h2 className="font-sans text-sm font-semibold uppercase tracking-wide text-ink">
            Sources
          </h2>
          {sourcesQuery.data && (
            <span className="font-mono text-xs text-ink-muted">{sourcesQuery.data.length}</span>
          )}
        </div>
        {sourcesQuery.isLoading && (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}
        {sourcesQuery.isError && (
          <EmptyState
            tone="error"
            title="Couldn't load sources"
            description={
              sourcesQuery.error instanceof Error
                ? sourcesQuery.error.message
                : 'Something went wrong.'
            }
          />
        )}
        {sourcesQuery.data && <SourceList sources={sourcesQuery.data} />}
      </section>
    </div>
  );
}
