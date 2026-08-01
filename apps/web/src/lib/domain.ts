import type {
  CaseStatus,
  CaseType,
  LegalRisk,
  MonetizationTier,
  ResolutionStatus,
  RiskFlag,
  SourceGateFailureReason,
  SourceTier,
} from '../api/cases';

export const caseTypeLabels: Record<CaseType, string> = {
  homicide: 'Homicide',
  disappearance: 'Disappearance',
  unexplained_event: 'Unexplained event',
  historical_horror: 'Historical horror',
  maritime: 'Maritime',
  disaster: 'Disaster',
  institutional_abuse: 'Institutional abuse',
};

export const resolutionStatusLabels: Record<ResolutionStatus, string> = {
  convicted: 'Convicted',
  acquitted: 'Acquitted',
  unsolved: 'Unsolved',
  officially_ruled: 'Officially ruled',
  disputed: 'Disputed',
};

export const caseStatusLabels: Record<CaseStatus, string> = {
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

export const riskFlagLabels: Record<RiskFlag, string> = {
  child_victim: 'Child victim',
  sexual_violence: 'Sexual violence',
  graphic_injury_central: 'Graphic injury central',
  suicide_central: 'Suicide central',
  ongoing_litigation: 'Ongoing litigation',
  named_living_suspect: 'Named living suspect',
  recent_event: 'Recent event',
  political_violence: 'Political violence',
  hate_motivated: 'Hate motivated',
};

export const gateFailureReasonLabels: Record<SourceGateFailureReason, string> = {
  insufficient_verified_sources: 'Needs 3 verified sources',
  missing_primary_record: 'Needs a primary record',
  insufficient_distinct_domains: 'Needs 3 distinct source domains',
};
