import { useSearchParams } from 'react-router';
import { useCases } from '../api/queries';
import type { CaseRead, CaseStatus, CaseType, MonetizationTier } from '../api/cases';
import { caseStatusLabels, caseTypeLabels, monetizationTierLabels } from '../lib/domain';
import { CaseCard } from '../components/cases/CaseCard';
import { EmptyState } from '../components/ui/EmptyState';
import { Skeleton } from '../components/ui/Skeleton';

const PAGE_SIZE = 24;

const CASE_STATUSES = Object.keys(caseStatusLabels) as CaseStatus[];
const CASE_TYPES = Object.keys(caseTypeLabels) as CaseType[];
const TIERS = Object.keys(monetizationTierLabels) as MonetizationTier[];

function FilterSelect<T extends string>({
  label,
  value,
  options,
  labels,
  onChange,
}: {
  label: string;
  value: T | undefined;
  options: T[];
  labels: Record<T, string>;
  onChange: (value: T | undefined) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-ink-muted">
      {label}
      <select
        value={value ?? ''}
        onChange={(e) => onChange((e.target.value || undefined) as T | undefined)}
        className="rounded-md border border-ink/15 bg-paper px-2.5 py-1.5 font-sans text-sm text-ink focus-visible:outline-2 focus-visible:outline-ledger-blue"
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {labels[option]}
          </option>
        ))}
      </select>
    </label>
  );
}

const GRID_CLASSES = 'grid gap-4 grid-cols-[repeat(auto-fit,minmax(280px,1fr))]';

function CardGridSkeleton() {
  return (
    <div className={GRID_CLASSES}>
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-44 w-full" />
      ))}
    </div>
  );
}

function CardGrid({ items }: { items: CaseRead[] }) {
  return (
    <div className={GRID_CLASSES}>
      {items.map((item) => (
        <CaseCard key={item.id} item={item} />
      ))}
    </div>
  );
}

export function CasesLibraryPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const status = (searchParams.get('status') ?? undefined) as CaseStatus | undefined;
  const monetizationTier = (searchParams.get('monetization_tier') ?? undefined) as
    | MonetizationTier
    | undefined;
  const caseType = (searchParams.get('case_type') ?? undefined) as CaseType | undefined;
  const offset = Number(searchParams.get('offset') ?? 0);

  function updateFilter(key: string, value: string | undefined) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete('offset');
    setSearchParams(next);
  }

  function goToOffset(next: number) {
    const params = new URLSearchParams(searchParams);
    params.set('offset', String(next));
    setSearchParams(params);
  }

  const { data, isLoading, isError, error, isPlaceholderData } = useCases({
    status,
    monetization_tier: monetizationTier,
    case_type: caseType,
    offset,
    limit: PAGE_SIZE,
  });

  const hasFilters = Boolean(status || monetizationTier || caseType);

  return (
    <div className="flex max-w-6xl flex-col gap-6">
      <div>
        <h1 className="font-sans text-2xl font-semibold text-ink">Cases</h1>
      </div>

      <div className="flex flex-wrap items-end gap-4 rounded-lg border border-ink/10 bg-paper-raised p-4">
        <FilterSelect
          label="Status"
          value={status}
          options={CASE_STATUSES}
          labels={caseStatusLabels}
          onChange={(v) => updateFilter('status', v)}
        />
        <FilterSelect
          label="Monetization tier"
          value={monetizationTier}
          options={TIERS}
          labels={monetizationTierLabels}
          onChange={(v) => updateFilter('monetization_tier', v)}
        />
        <FilterSelect
          label="Case type"
          value={caseType}
          options={CASE_TYPES}
          labels={caseTypeLabels}
          onChange={(v) => updateFilter('case_type', v)}
        />
      </div>

      {isError && (
        <EmptyState
          tone="error"
          title="Couldn't load cases"
          description={error instanceof Error ? error.message : 'Something went wrong.'}
        />
      )}

      {isLoading && <CardGridSkeleton />}

      {!isLoading && !isError && data && data.items.length === 0 && (
        <EmptyState
          title={hasFilters ? 'No cases match these filters' : 'No cases yet'}
          description={
            hasFilters
              ? 'Clear a filter to widen the search.'
              : 'The library is empty — case intake happens outside this screen for now.'
          }
        />
      )}

      {!isLoading && !isError && data && data.items.length > 0 && (
        <div className={isPlaceholderData ? 'opacity-60 transition-opacity' : undefined}>
          {monetizationTier ? (
            <CardGrid items={data.items} />
          ) : (
            <GroupedCards items={data.items} />
          )}
        </div>
      )}

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm text-ink-muted">
          <span className="font-mono">
            {data.offset + 1}–{Math.min(data.offset + data.items.length, data.total)} of{' '}
            {data.total}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => goToOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded-md border border-ink/15 px-3 py-1.5 font-sans text-sm text-ink disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={offset + PAGE_SIZE >= data.total}
              onClick={() => goToOffset(offset + PAGE_SIZE)}
              className="rounded-md border border-ink/15 px-3 py-1.5 font-sans text-sm text-ink disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const GROUPS: { tiers: MonetizationTier[]; title: string; description: string }[] = [
  { tiers: ['green'], title: 'Ready to produce', description: 'Cleared to write' },
  { tiers: ['yellow'], title: 'Needs review', description: 'Producible with caution' },
  {
    tiers: ['red', 'unknown'],
    title: 'Not producible',
    description: 'Cannot earn, or not yet scored',
  },
];

function GroupedCards({ items }: { items: CaseRead[] }) {
  return (
    <div className="flex flex-col gap-8">
      {GROUPS.map((group) => {
        const groupItems = items.filter((item) => group.tiers.includes(item.monetization_tier));
        if (groupItems.length === 0) return null;

        const heading = (
          <div className="flex items-baseline gap-2">
            <h2 className="font-sans text-xs font-semibold uppercase tracking-wide text-ink-muted group-hover:text-ink">
              {group.title}
            </h2>
            <span className="text-xs text-ink-muted">
              {group.description} · {groupItems.length}
            </span>
          </div>
        );

        if (group.title === 'Not producible') {
          return (
            <details key={group.title} className="group">
              <summary className="mb-3 flex cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                <svg
                  viewBox="0 0 16 16"
                  className="h-3 w-3 shrink-0 text-ink-muted transition-transform group-hover:text-ink group-open:rotate-90"
                  aria-hidden="true"
                >
                  <path
                    d="M5.5 3L10.5 8L5.5 13"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {heading}
              </summary>
              <div className="opacity-80">
                <CardGrid items={groupItems} />
              </div>
            </details>
          );
        }

        return (
          <section key={group.title}>
            <div className="mb-3">{heading}</div>
            <CardGrid items={groupItems} />
          </section>
        );
      })}
    </div>
  );
}
