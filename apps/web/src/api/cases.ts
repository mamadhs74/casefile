import { apiFetch } from './client';
import type { components } from './schema';

export type CaseRead = components['schemas']['CaseRead'];
export type CaseCreate = components['schemas']['CaseCreate'];
export type CaseListResponse = components['schemas']['CaseListResponse'];
export type EligibilityResultRead = components['schemas']['EligibilityResultRead'];
export type GateResultRead = components['schemas']['GateResultRead'];
export type SourceRead = components['schemas']['SourceRead'];
export type CaseStatus = components['schemas']['CaseStatus'];
export type CaseType = components['schemas']['CaseType'];
export type MonetizationTier = components['schemas']['MonetizationTier'];
export type LegalRisk = components['schemas']['LegalRisk'];
export type ResolutionStatus = components['schemas']['ResolutionStatus'];
export type RiskFlag = components['schemas']['RiskFlag'];
export type SourceTier = components['schemas']['SourceTier'];
export type SourceGateFailureReason = components['schemas']['SourceGateFailureReason'];

export interface ListCasesParams {
  status?: CaseStatus;
  monetization_tier?: MonetizationTier;
  case_type?: CaseType;
  offset?: number;
  limit?: number;
}

function toQueryString(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params) as [string, string | number | undefined][]) {
    if (value !== undefined) search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

export function listCases(params: ListCasesParams = {}): Promise<CaseListResponse> {
  return apiFetch<CaseListResponse>(`/cases${toQueryString(params)}`);
}

export function getCase(caseId: number): Promise<CaseRead> {
  return apiFetch<CaseRead>(`/cases/${caseId}`);
}

export function getCaseGate(caseId: number): Promise<GateResultRead> {
  return apiFetch<GateResultRead>(`/cases/${caseId}/gate`);
}

export function listCaseSources(caseId: number): Promise<SourceRead[]> {
  return apiFetch<SourceRead[]>(`/cases/${caseId}/sources`);
}

export function previewEligibility(payload: CaseCreate): Promise<EligibilityResultRead> {
  return apiFetch<EligibilityResultRead>('/cases/preview-eligibility', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createCase(payload: CaseCreate): Promise<CaseRead> {
  return apiFetch<CaseRead>('/cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
