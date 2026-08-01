import type { MonetizationTier } from '../../api/cases';

/**
 * Shape carries the same information as colour, independently — tier is the
 * most important signal in the product and red/green is the most common
 * colour-blindness axis. Each tier gets a distinct silhouette, not just a
 * distinct hue.
 */
export function TierIcon({ tier, className }: { tier: MonetizationTier; className?: string }) {
  switch (tier) {
    case 'green':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
          <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M5.25 8.25L7.15 10.15L10.75 6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case 'yellow':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
          <path
            d="M8 2.25L14.25 13.25H1.75L8 2.25Z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path d="M8 6.5V9.25" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="8" cy="11.25" r="0.85" fill="currentColor" />
        </svg>
      );
    case 'red':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
          <path
            d="M5.2 1.75H10.8L14.25 5.2V10.8L10.8 14.25H5.2L1.75 10.8V5.2L5.2 1.75Z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
          <path d="M5.5 8H10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case 'unknown':
      return (
        <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
          <circle
            cx="8"
            cy="8"
            r="6.25"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeDasharray="2.2 2.2"
          />
          <path
            d="M6.4 6.4C6.4 5.5 7.1 4.85 8 4.85C8.9 4.85 9.6 5.5 9.6 6.35C9.6 7.55 8 7.5 8 8.9"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
          <circle cx="8" cy="11.1" r="0.8" fill="currentColor" />
        </svg>
      );
  }
}
