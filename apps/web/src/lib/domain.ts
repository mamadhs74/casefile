import type {
  LegalRisk,
  MonetizationTier,
  ResolutionStatus,
  SourceGateFailureReason,
  SourceTier,
  SubjectStatus,
} from '../api/subjects';

/**
 * case_type and risk-flag labels used to live here as static maps. They
 * can't anymore -- which category and risk-flag values are valid depends on
 * which strategy a subject belongs to (packages/strategies/<slug>/), and
 * that's no longer a single, compile-time-known set. Components fetch a
 * strategy's own vocabulary (StrategyRead.risk_flags,
 * StrategyRead.attributes_schema) and use humanize() below for display,
 * rather than importing a fixed label table. See docs/SCHEMA.md.
 */
export function humanize(value: string): string {
  const spaced = value.replaceAll('_', ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/**
 * A subject's attributes are a strategy-shaped bag with no fixed field
 * names -- criminal-cases has exactly one (case_type), a future strategy
 * might have several or none. Rather than hardcode "case_type" here, show
 * every value present, humanized. For criminal-cases today this reproduces
 * exactly what the old case_type-only display showed.
 */
export function attributeSummary(attributes: Record<string, unknown>): string {
  return Object.values(attributes)
    .map((value) => humanize(String(value)))
    .join(' · ');
}

export const resolutionStatusLabels: Record<ResolutionStatus, string> = {
  convicted: 'Convicted',
  acquitted: 'Acquitted',
  unsolved: 'Unsolved',
  officially_ruled: 'Officially ruled',
  disputed: 'Disputed',
};

export const subjectStatusLabels: Record<SubjectStatus, string> = {
  candidate: 'Candidate',
  researching: 'Researching',
  ready: 'Ready',
  in_production: 'In production',
  published: 'Published',
  rejected: 'Rejected',
};

export const monetizationTierLabels: Record<MonetizationTier, string> = {
  green: 'Green',
  yellow: 'Yellow',
  red: 'Red',
  unknown: 'Unknown',
};

export const monetizationTierDescriptions: Record<MonetizationTier, string> = {
  green: 'Can be produced',
  yellow: 'Needs review',
  red: 'Not producible',
  unknown: 'Not yet scored',
};

export const legalRiskLabels: Record<LegalRisk, string> = {
  low: 'Low',
  medium: 'Medium',
  high: 'High',
};

export const sourceTierLabels: Record<SourceTier, string> = {
  primary_record: 'Primary record',
  contemporaneous: 'Contemporaneous',
  retrospective: 'Retrospective',
  book: 'Book',
  reference: 'Reference',
  unverified: 'Unverified',
};

export const gateFailureReasonLabels: Record<SourceGateFailureReason, string> = {
  insufficient_verified_sources: 'Needs more verified sources',
  missing_primary_record: 'Needs a primary record',
  insufficient_distinct_domains: 'Needs more distinct source domains',
};
