import { monetizationTierDescriptions, monetizationTierLabels } from '../../lib/domain';
import { tierClasses } from '../../lib/tier-style';
import type { MonetizationTier } from '../../api/subjects';
import { TierIcon } from './TierIcon';

interface TierTagProps {
  tier: MonetizationTier;
  variant?: 'tab' | 'pill';
}

/** The folder-tab colour block. Used at the top of every subject card and detail header. */
export function TierTag({ tier, variant = 'pill' }: TierTagProps) {
  const classes = tierClasses[tier];

  if (variant === 'tab') {
    return (
      <div
        className={`flex w-full items-center gap-2 rounded-t-lg border-b-2 px-3 py-2 ${classes.bgSoft} ${classes.border}`}
      >
        <TierIcon tier={tier} className={`h-4 w-4 shrink-0 ${classes.text}`} />
        <span className={`font-sans text-sm font-semibold ${classes.text}`}>
          {monetizationTierDescriptions[tier]}
        </span>
      </div>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${classes.borderSoft} ${classes.bgSoft} ${classes.text}`}
    >
      <TierIcon tier={tier} className="h-3.5 w-3.5 shrink-0" />
      {monetizationTierLabels[tier]}
    </span>
  );
}
