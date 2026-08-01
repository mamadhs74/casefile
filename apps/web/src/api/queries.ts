import { useQuery } from '@tanstack/react-query';
import { getCase, getCaseGate, listCases, listCaseSources, type ListCasesParams } from './cases';

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
