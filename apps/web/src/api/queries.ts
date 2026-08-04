import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createSubject,
  getStrategy,
  getSubject,
  getSubjectGate,
  listChannels,
  listStrategies,
  listSubjects,
  listSubjectSources,
  previewEligibility,
  type ListSubjectsParams,
  type SubjectCreate,
} from './subjects';

export function useSubjects(params: ListSubjectsParams) {
  return useQuery({
    queryKey: ['subjects', params],
    queryFn: () => listSubjects(params),
    placeholderData: (previous) => previous,
  });
}

export function useSubject(subjectId: number) {
  return useQuery({
    queryKey: ['subject', subjectId],
    queryFn: () => getSubject(subjectId),
  });
}

export function useSubjectGate(subjectId: number) {
  return useQuery({
    queryKey: ['subject', subjectId, 'gate'],
    queryFn: () => getSubjectGate(subjectId),
  });
}

export function useSubjectSources(subjectId: number) {
  return useQuery({
    queryKey: ['subject', subjectId, 'sources'],
    queryFn: () => listSubjectSources(subjectId),
  });
}

/** payload is null until the form has enough to score -- the query stays disabled until then. */
export function useEligibilityPreview(payload: SubjectCreate | null) {
  return useQuery({
    queryKey: ['preview-eligibility', payload],
    queryFn: () => previewEligibility(payload as SubjectCreate),
    enabled: payload !== null,
    placeholderData: (previous) => previous,
  });
}

export function useCreateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createSubject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subjects'] });
    },
  });
}

export function useStrategies() {
  return useQuery({
    queryKey: ['strategies'],
    queryFn: listStrategies,
    staleTime: Infinity, // strategies are seed/migration data, not edited at runtime
  });
}

export function useStrategy(slug: string | undefined) {
  return useQuery({
    queryKey: ['strategy', slug],
    queryFn: () => getStrategy(slug as string),
    enabled: slug !== undefined,
    staleTime: Infinity,
  });
}

export function useChannels(strategySlug: string) {
  return useQuery({
    queryKey: ['strategy', strategySlug, 'channels'],
    queryFn: () => listChannels(strategySlug),
  });
}

/**
 * UI copy should say "case" for criminal-cases, not the schema word
 * "subject" -- see docs/SCHEMA.md. With exactly one strategy registered,
 * "the first strategy's noun" and "the right noun" are the same thing;
 * this falls back to "case"/"cases" while strategies are still loading so
 * copy doesn't flash a placeholder. Once a second strategy exists, call
 * sites that show a single, filtered strategy should prefer that
 * strategy's own noun over this cross-strategy default.
 */
export function useSubjectNoun(): { singular: string; plural: string } {
  const { data: strategies } = useStrategies();
  const primary = strategies?.[0];
  return {
    singular: primary?.subject_noun_singular ?? 'case',
    plural: primary?.subject_noun_plural ?? 'cases',
  };
}
