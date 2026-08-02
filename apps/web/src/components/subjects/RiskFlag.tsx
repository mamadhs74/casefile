import { legalRiskLabels } from '../../lib/domain';
import { riskClasses } from '../../lib/tier-style';
import type { LegalRisk } from '../../api/subjects';

const shortRiskLabels: Record<LegalRisk, string> = {
  low: 'LOW',
  medium: 'MED',
  high: 'HIGH',
};

function FlagIcon({ filled, className }: { filled: boolean; className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} aria-hidden="true">
      <path
        d="M3.5 1.5V14.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M3.5 2.25H12.25L10.1 4.85L12.25 7.45H3.5Z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface RiskFlagProps {
  risk: LegalRisk;
  /** compact: a small labelled mark for card corners. Otherwise a full-word chip. */
  compact?: boolean;
}

/**
 * A small index flag clipped to a folder edge — distinct object from the
 * tier tab, so tier and legal risk read as two different facts even though
 * both carry colour. Low risk gets an outline flag, never a hidden one:
 * risk is always visible, only its weight changes — and HIGH is a solid
 * fill so it can't be mistaken for a quiet detail.
 */
export function RiskFlag({ risk, compact = false }: RiskFlagProps) {
  const classes = riskClasses[risk];
  const filled = risk !== 'low';

  if (compact) {
    return (
      <span
        className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold tracking-wide ${classes.border} ${classes.bg} ${classes.text}`}
        title={`Legal risk: ${legalRiskLabels[risk]}`}
      >
        <FlagIcon filled={filled} className="h-3 w-3 shrink-0" />
        {shortRiskLabels[risk]}
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-semibold ${classes.border} ${classes.bg} ${classes.text}`}
    >
      <FlagIcon filled={filled} className="h-3.5 w-3.5 shrink-0" />
      Legal risk: {legalRiskLabels[risk]}
    </span>
  );
}
