import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  approveRemaining,
  executePlan,
  fetchPlan,
  regeneratePlan,
  updateStep,
} from '../api/client';

export function usePlan(cardId: number | null) {
  return useQuery({
    queryKey: ['plan', cardId],
    queryFn: () => fetchPlan(cardId!),
    enabled: cardId !== null,
    retry: false,
  });
}

export function useUpdateStep(cardId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { stepIndex: number; status?: string; draft_content?: string; feedback?: string }) =>
      updateStep(cardId, args.stepIndex, args),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan', cardId] }),
  });
}

export function useApproveRemaining(cardId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fromIndex?: number) => approveRemaining(cardId, fromIndex),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan', cardId] }),
  });
}

export function useExecutePlan(cardId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => executePlan(cardId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan', cardId] }),
  });
}

export function useRegeneratePlan(cardId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feedback: string) => regeneratePlan(cardId, feedback),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['plan', cardId] }),
  });
}
