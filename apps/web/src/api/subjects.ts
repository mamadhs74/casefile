import { apiFetch } from './client';
import type { components } from './schema';

export type SubjectRead = components['schemas']['SubjectRead'];
export type SubjectCreate = components['schemas']['SubjectCreate'];
export type SubjectListResponse = components['schemas']['SubjectListResponse'];
export type EligibilityResultRead = components['schemas']['EligibilityResultRead'];
export type GateResultRead = components['schemas']['GateResultRead'];
export type SourceRead = components['schemas']['SourceRead'];
export type StrategyRead = components['schemas']['StrategyRead'];
export type ChannelRead = components['schemas']['ChannelRead'];
export type ChannelCreate = components['schemas']['ChannelCreate'];
export type ChannelUpdate = components['schemas']['ChannelUpdate'];
export type Platform = components['schemas']['Platform'];
export type SubjectStatus = components['schemas']['SubjectStatus'];
export type MonetizationTier = components['schemas']['MonetizationTier'];
export type LegalRisk = components['schemas']['LegalRisk'];
export type ResolutionStatus = components['schemas']['ResolutionStatus'];
export type SourceTier = components['schemas']['SourceTier'];
export type ArchiveProvider = components['schemas']['ArchiveProvider'];
export type SourceGateFailureReason = components['schemas']['SourceGateFailureReason'];

export interface ListSubjectsParams {
  status?: SubjectStatus;
  monetization_tier?: MonetizationTier;
  strategy_slug?: string;
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

export function listSubjects(params: ListSubjectsParams = {}): Promise<SubjectListResponse> {
  return apiFetch<SubjectListResponse>(`/subjects${toQueryString(params)}`);
}

export function getSubject(subjectId: number): Promise<SubjectRead> {
  return apiFetch<SubjectRead>(`/subjects/${subjectId}`);
}

export function getSubjectGate(subjectId: number): Promise<GateResultRead> {
  return apiFetch<GateResultRead>(`/subjects/${subjectId}/gate`);
}

export function listSubjectSources(subjectId: number): Promise<SourceRead[]> {
  return apiFetch<SourceRead[]>(`/subjects/${subjectId}/sources`);
}

export function previewEligibility(payload: SubjectCreate): Promise<EligibilityResultRead> {
  return apiFetch<EligibilityResultRead>('/subjects/preview-eligibility', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createSubject(payload: SubjectCreate): Promise<SubjectRead> {
  return apiFetch<SubjectRead>('/subjects', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listStrategies(): Promise<StrategyRead[]> {
  return apiFetch<StrategyRead[]>('/strategies');
}

export function getStrategy(slug: string): Promise<StrategyRead> {
  return apiFetch<StrategyRead>(`/strategies/${slug}`);
}

export function listChannels(strategySlug: string): Promise<ChannelRead[]> {
  return apiFetch<ChannelRead[]>(`/strategies/${strategySlug}/channels`);
}

export function createChannel(
  strategySlug: string,
  payload: ChannelCreate,
): Promise<ChannelRead> {
  return apiFetch<ChannelRead>(`/strategies/${strategySlug}/channels`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateChannel(
  strategySlug: string,
  channelId: number,
  payload: ChannelUpdate,
): Promise<ChannelRead> {
  return apiFetch<ChannelRead>(`/strategies/${strategySlug}/channels/${channelId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}
