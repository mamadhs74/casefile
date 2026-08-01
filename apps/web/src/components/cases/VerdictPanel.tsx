import type { EligibilityResultRead, MonetizationTier } from '../../api/cases';
import { monetizationTierDescriptions } from '../../lib/domain';
import { tierClasses } from '../../lib/tier-style';
import { TierIcon } from './TierIcon';
import { RiskFlag } from './RiskFlag';
import { Skeleton } from '../ui/Skeleton';

export type VerdictState = 'incomplete' | 'pending-first' | 'pending-refresh' | 'resolved' | 'error';

interface VerdictPanelProps {
  state: VerdictState;
  result?: EligibilityResultRead;
  errorMessage?: string;
  /** Human-readable names of required fields still empty, in form order. Used only when state is 'incomplete'. */
  missingFields?: string[];
}

function joinWithAnd(items: string[]): string {
  if (items.length === 0) return '';
  if (items.length === 1) return items[0];
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`;
}

const PANEL_HEADING = (
  <h2 className="font-sans text-xs font-semibold uppercase tracking-wide text-ink-muted">
    Verdict
  </h2>
);

function VerdictContent({
  tier,
  result,
}: {
  tier: MonetizationTier;
  result: EligibilityResultRead;
}) {
  const classes = tierClasses[tier];
  return (
    <div className="flex items-start gap-3">
      <TierIcon tier={tier} className={`h-7 w-7 shrink-0 ${classes.text}`} />
      <div className="flex flex-1 flex-col gap-2">
        <p className={`font-sans text-lg font-bold leading-tight ${classes.text}`}>
          {monetizationTierDescriptions[tier]}
        </p>
        <RiskFlag risk={result.legal_risk} />
        {result.notes.length > 0 && (
          <ul className="mt-1 flex flex-col gap-1 border-t border-ink/10 pt-2 text-sm text-ink-muted">
            {result.notes.map((note, i) => (
              <li key={i}>· {note}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * The signature interaction: the verdict arrives, it isn't a form field
 * updating. But "not retrieved yet" and "actively rendering" have to look
 * different, or the blur reads as a rendering bug instead of a state:
 *
 * - incomplete: the form can't be scored yet. Plain, sharp text naming what's
 *   still missing. No blur -- there is nothing to bring into focus.
 * - pending-first: scorable, but no verdict has ever resolved for this draft.
 *   A skeleton, since there's no real previous content to blur.
 * - pending-refresh: a new verdict is resolving while a previous one exists.
 *   The previous verdict blurs -- sharpening back up is a real, visible
 *   change, not a swap from decoy placeholder text to real text.
 * - resolved: sharp, full colour.
 *
 * Reduced motion collapses the blur/sharpen transition to an instant swap
 * globally (see index.css), not handled here.
 */
export function VerdictPanel({
  state,
  result,
  errorMessage,
  missingFields = [],
}: VerdictPanelProps) {
  if (state === 'error') {
    return (
      <div className="rounded-lg border border-folder-rust/40 bg-folder-rust/8 p-5">
        <h2 className="font-sans text-xs font-semibold uppercase tracking-wide text-folder-rust">
          Verdict
        </h2>
        <p className="mt-2 text-sm font-semibold text-folder-rust">Couldn't check eligibility</p>
        <p className="mt-1 text-sm text-ink-muted">{errorMessage ?? 'Something went wrong.'}</p>
      </div>
    );
  }

  if (state === 'incomplete') {
    return (
      <div className="rounded-lg border border-ink/10 bg-paper-raised p-5">
        {PANEL_HEADING}
        <p className="mt-3 text-sm text-ink-muted">
          {missingFields.length > 0
            ? `Fill in ${joinWithAnd(missingFields)} to score this case.`
            : 'Fill in the case above to score it.'}
        </p>
      </div>
    );
  }

  if (state === 'pending-first') {
    return (
      <div className="rounded-lg border border-ink/10 bg-paper-raised p-5">
        {PANEL_HEADING}
        <div className="mt-3 flex items-start gap-3">
          <Skeleton className="h-7 w-7 shrink-0 rounded-full" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        </div>
      </div>
    );
  }

  // pending-refresh or resolved: both render the real content, pending-refresh just blurs it.
  const focused = state === 'resolved';
  const tier: MonetizationTier = result?.tier ?? 'unknown';
  const classes = tierClasses[tier];

  return (
    <div
      className={`rounded-lg border p-5 transition-colors duration-500 ${
        focused ? `${classes.borderSoft} ${classes.bgSoft}` : 'border-ink/10 bg-paper-raised'
      }`}
    >
      {PANEL_HEADING}
      <div
        className={`mt-3 transition-[filter,opacity] duration-500 ease-out ${
          focused ? 'opacity-100 blur-none' : 'opacity-60 blur-sm'
        }`}
      >
        {result && <VerdictContent tier={tier} result={result} />}
      </div>
    </div>
  );
}
