import type { LegalRisk, MonetizationTier } from '../api/cases';

interface TierClasses {
  text: string;
  border: string;
  borderSoft: string;
  bgSoft: string;
  bgSolid: string;
}

export const tierClasses: Record<MonetizationTier, TierClasses> = {
  green: {
    text: 'text-folder-green',
    border: 'border-folder-green',
    borderSoft: 'border-folder-green/40',
    bgSoft: 'bg-folder-green/12',
    bgSolid: 'bg-folder-green',
  },
  yellow: {
    text: 'text-folder-ochre',
    border: 'border-folder-ochre',
    borderSoft: 'border-folder-ochre/40',
    bgSoft: 'bg-folder-ochre/12',
    bgSolid: 'bg-folder-ochre',
  },
  red: {
    text: 'text-folder-rust',
    border: 'border-folder-rust',
    borderSoft: 'border-folder-rust/40',
    bgSoft: 'bg-folder-rust/12',
    bgSolid: 'bg-folder-rust',
  },
  unknown: {
    text: 'text-ink-muted',
    border: 'border-ink-muted',
    borderSoft: 'border-ink-muted/40',
    bgSoft: 'bg-ink-muted/10',
    bgSolid: 'bg-ink-muted',
  },
};

interface RiskClasses {
  border: string;
  bg: string;
  text: string;
}

/**
 * Three distinct visual weights, not three colours of the same weight — low
 * is an outline that barely registers, medium is a soft tinted chip, high is
 * a solid fill with dark-on-rust text. HIGH means do not produce, so it has
 * to look like the loudest thing on the card, not just a different hue.
 */
export const riskClasses: Record<LegalRisk, RiskClasses> = {
  low: { border: 'border-ink/25', bg: 'bg-transparent', text: 'text-ink-muted' },
  medium: {
    border: 'border-folder-ochre/40',
    bg: 'bg-folder-ochre/15',
    text: 'text-folder-ochre',
  },
  high: { border: 'border-folder-rust', bg: 'bg-folder-rust', text: 'text-paper' },
};
