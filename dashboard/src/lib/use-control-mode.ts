import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getAsvDataMode } from './asv-data-mode'
import { fetchControlMode, putControlMode } from './direct-live'
import { asvBridgeUrl } from './stream-urls'
import type { AsvDataMode } from './asv-data-mode'
import type { ControlMode } from './control-mode'

export function useControlMode(
  asvId: string,
  dataMode: AsvDataMode = getAsvDataMode(import.meta.env.VITE_ASV_DATA_MODE),
) {
  const queryClient = useQueryClient()
  const queryKey = ['asv-control-mode', asvId, dataMode] as const
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      dataMode === 'fixture'
        ? Promise.resolve<ControlMode>('AUTONOMOUS')
        : fetchControlMode(asvBridgeUrl, signal),
    staleTime: dataMode === 'fixture' ? Number.POSITIVE_INFINITY : 0,
    refetchInterval: dataMode === 'direct' ? 2000 : false,
  })
  const mutation = useMutation({
    mutationFn: (nextMode: ControlMode) => putControlMode(asvBridgeUrl, nextMode),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey })
      return queryKey
    },
    onSuccess: (nextMode, _variables, mutationQueryKey) => {
      queryClient.setQueryData(mutationQueryKey, nextMode)
    },
  })
  const updateMode: typeof mutation.mutate =
    dataMode === 'fixture' ? () => {} : mutation.mutate

  return {
    mode: query.data ?? null,
    isLoading: query.isPending,
    isError: query.isError || mutation.isError,
    error: mutation.error ?? query.error ?? null,
    isUpdating: mutation.isPending,
    canEdit: dataMode === 'direct' && query.isSuccess,
    readOnly: dataMode === 'fixture',
    updateMode,
  }
}
