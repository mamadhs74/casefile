import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createCase,
  getCase,
  getCaseGate,
  listCases,
  listCaseSources,
  previewEligibility,
  type CaseCreate,
  type ListCasesParams,
} from './cases';

export function useCases(params: ListCasesParams) {
  return useQuery({
    queryKey: ['cases', params],
    queryFn: () => listCases(params),
    placeholderData: (previous) => previous,
  });
}

export function useCase(caseId: number) {
  return useQuery({
    queryKey: ['case', caseId],
    queryFn: () => getCase(caseId),
  });
}

export function useCaseGate(caseId: number) {
  return useQuery({
    queryKey: ['case', caseId, 'gate'],
    queryFn: () => getCaseGate(caseId),
  });
}

export function useCaseSources(caseId: number) {
  return useQuery({
    queryKey: ['case', caseId, 'sources'],
    queryFn: () => listCaseSources(caseId),
  });
}

/** payload is null until the form has enough to score -- the query stays disabled until then. */
export function useEligibilityPreview(payload: CaseCreate | null) {
  return useQuery({
    queryKey: ['preview-eligibility', payload],
    queryFn: () => previewEligibility(payload as CaseCreate),
    enabled: payload !== null,
    placeholderData: (previous) => previous,
  });
}

export function useCreateCase() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createCase,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['cases'] });
    },
  });
}
