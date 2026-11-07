import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useLocalToday } from './useDateRange'

const STALE = {
  SHORT:  5 * 60 * 1000,   // 5 min — user data that changes frequently (today's readiness, sync status)
  MEDIUM: 15 * 60 * 1000,  // 15 min — slower-moving analytics (sleep correlations, metric trends)
  LONG:   30 * 60 * 1000,  // 30 min — historical data that rarely changes (workout details, enriched anomalies)
  STATIC: 60 * 60 * 1000,  // 1 hour — feature flags, settings
} as const

import type {
  Anomaly,
  DataStats,
  EnrichedAnomaly,
  EnrichedWorkout,
  ExerciseSet,
  GarminStatus,
  LimitingFactor,
  MetricTrend,
  ReadinessHistoryPoint,
  ReadinessResult,
  RecoveryActivity,
  SleepConsistency,
  SleepCorrelations,
  SleepInsight,
  StrengthMaxWeight,
  StrengthVolume,
  SyncStatus,
  SyncTriggerResponse,
  TrainingLoadResponse,
  UploadResult,
  WeeklyDigestResponse,
  WeeklySummary,
  WhoopStatus,
  ExerciseSummaryItem,
  WithWithoutResponse,
  WorkoutTypeSummary,
} from '../types/api'

/** Invalidate every query that depends on synced/imported workout and health data. */
export function invalidateWorkoutQueries(queryClient: QueryClient, userId: string | null | undefined) {
  for (const key of ['workouts', 'training', 'readiness', 'sleep', 'trends', 'insights', 'recovery']) {
    void queryClient.invalidateQueries({ queryKey: [key], refetchType: 'active' })
  }
  void queryClient.invalidateQueries({ queryKey: ['sync', 'stats', userId], refetchType: 'active' })
}

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export function useReadinessToday() {
  const { userId } = useAuth()
  const today = useLocalToday() // in the key so the query refetches after midnight
  return useQuery({
    queryKey: ['readiness', 'today', today, userId],
    queryFn: ({ signal }) =>
      // 204 No Content when there is no readiness data for the date
      api.get<ReadinessResult | null>(`/api/readiness/today?date=${today}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    refetchOnWindowFocus: true,
    enabled: !!userId,
  })
}

export function useReadinessHistory(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['readiness', 'history', start, end, userId],
    queryFn: ({ signal }) =>
      api.get<ReadinessHistoryPoint[]>(`/api/readiness/history?start=${start}&end=${end}`, signal),
    staleTime: STALE.MEDIUM,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Workouts
// ---------------------------------------------------------------------------

export function useWorkouts(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', start, end, userId],
    queryFn: ({ signal }) => api.get<EnrichedWorkout[]>(`/api/workouts?start=${start}&end=${end}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

export function useWorkoutDetail(id: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'detail', id, userId],
    queryFn: ({ signal }) => api.get<EnrichedWorkout>(`/api/workouts/${id}`, signal),
    staleTime: STALE.LONG,
    retry: 1,
    enabled: !!id && !!userId,
  })
}

export function useExerciseSets(workoutId: string, enabled = true) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'exercise-sets', workoutId, userId],
    queryFn: ({ signal }) => api.get<ExerciseSet[]>(`/api/workouts/${workoutId}/exercise-sets`, signal),
    staleTime: STALE.LONG,
    retry: 1,
    enabled: !!workoutId && enabled && !!userId,
  })
}

export function useExerciseSummary(workoutId: string, enabled = true) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'exercise-summary', workoutId, userId],
    queryFn: ({ signal }) => api.get<ExerciseSummaryItem[]>(`/api/workouts/${workoutId}/exercise-summary`, signal),
    staleTime: STALE.LONG,
    retry: 1,
    enabled: !!workoutId && enabled && !!userId,
  })
}

export function useStrengthVolume(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'strength-volume', start, end, userId],
    queryFn: ({ signal }) => api.get<StrengthVolume[]>(`/api/workouts/strength-volume?start=${start}&end=${end}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

export function useStrengthMaxWeight(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'strength-max-weight', start, end, userId],
    queryFn: ({ signal }) => api.get<StrengthMaxWeight[]>(`/api/workouts/strength-max-weight?start=${start}&end=${end}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

// Backend returns list[WorkoutTypeSummaryItem] sorted by count desc
export function useWorkoutSummary(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'summary', start, end, userId],
    queryFn: ({ signal }) =>
      api.get<WorkoutTypeSummary[]>(`/api/workouts/summary?start=${start}&end=${end}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Sleep
// ---------------------------------------------------------------------------

export function useSleepInsights(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sleep', 'insights', start, end, userId],
    queryFn: ({ signal }) => api.get<SleepInsight[]>(`/api/sleep/insights?start=${start}&end=${end}`, signal),
    staleTime: STALE.MEDIUM,
    retry: 1,
    enabled: !!userId,
  })
}

export function useSleepCorrelations(days: number = 30) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sleep', 'correlations', days, userId],
    queryFn: ({ signal }) => api.get<SleepCorrelations>(`/api/sleep/correlations?days=${days}`, signal),
    staleTime: STALE.MEDIUM,
    retry: 1,
    enabled: !!userId,
  })
}

export function useSleepConsistency(days: number = 30) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sleep', 'consistency', days, userId],
    queryFn: ({ signal }) => api.get<SleepConsistency>(`/api/sleep/consistency?days=${days}`, signal),
    staleTime: STALE.MEDIUM,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Trends
// ---------------------------------------------------------------------------

export function useMetricTrend(metric: string, start: string, end: string, enabled = true) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['trends', metric, start, end, userId],
    queryFn: ({ signal }) => api.get<MetricTrend>(`/api/trends/${metric}?start=${start}&end=${end}`, signal),
    staleTime: STALE.MEDIUM,
    retry: 1,
    enabled: !!userId && enabled,
  })
}

// date param maps to the `end` query param (backend defaults to today if omitted)
export function useWeeklySummary(date?: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['trends', 'weekly', date ?? 'today', userId],
    queryFn: ({ signal }) =>
      api.get<WeeklySummary>(
        date ? `/api/trends/weekly-summary?end=${date}` : '/api/trends/weekly-summary',
        signal,
      ),
    staleTime: STALE.SHORT,
    retry: 1,
    refetchOnWindowFocus: true,
    enabled: !!userId,
  })
}

export function useAnomalies(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['trends', 'anomalies', start, end, userId],
    queryFn: ({ signal }) =>
      api.get<Anomaly[]>(`/api/trends/anomalies?start=${start}&end=${end}`, signal),
    staleTime: STALE.MEDIUM,
    retry: 1,
    enabled: !!userId,
  })
}

/** Enriched anomalies — includes surrounding context, co-anomalies, and training/sleep notes. */
export function useEnrichedAnomalies(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['trends', 'anomalies', 'enriched', start, end, userId],
    queryFn: ({ signal }) =>
      api.get<EnrichedAnomaly[]>(
        `/api/trends/anomalies/enriched?start=${start}&end=${end}`,
        signal,
      ),
    staleTime: STALE.LONG,
    retry: 1,
    enabled: !!userId,
  })
}

/** Server-generated weekly digest with takeaways and metrics snapshot. */
export function useWeeklyDigest(date?: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['insights', 'weekly-digest', date ?? 'today', userId],
    queryFn: ({ signal }) =>
      api.get<WeeklyDigestResponse>(
        date ? `/api/insights/weekly-digest?end=${date}` : '/api/insights/weekly-digest',
        signal,
      ),
    staleTime: STALE.SHORT,
    retry: 1,
    refetchOnWindowFocus: true,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Training Load
// ---------------------------------------------------------------------------

export function useLimitingFactors(topN = 2) {
  const { userId } = useAuth()
  const today = useLocalToday() // in the key so the query refetches after midnight
  return useQuery({
    queryKey: ['readiness', 'limiting-factors', topN, today, userId],
    queryFn: ({ signal }) =>
      api.get<LimitingFactor[]>(`/api/readiness/limiting-factors?top_n=${topN}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

export function useTrainingLoadRatio(date?: string) {
  const { userId } = useAuth()
  const today = useLocalToday() // in the key so the query refetches after midnight
  return useQuery({
    queryKey: ['training', 'load-ratio', date ?? today, userId],
    queryFn: ({ signal }) =>
      api.get<TrainingLoadResponse>(
        date ? `/api/training/load-ratio?date=${date}` : '/api/training/load-ratio',
        signal,
      ),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Recovery Activities
// ---------------------------------------------------------------------------

export function useRecovery(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['recovery', start, end, userId],
    queryFn: ({ signal }) => api.get<RecoveryActivity[]>(`/api/recovery?start=${start}&end=${end}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

export function useRecoveryWithWithout(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['recovery', 'with-without', start, end, userId],
    queryFn: ({ signal }) => api.get<WithWithoutResponse>(`/api/recovery/with-without?start=${start}&end=${end}`, signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Whoop connection status
// ---------------------------------------------------------------------------

export function useWhoopStatus() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['auth', 'whoop-status', userId],
    queryFn: ({ signal }) => api.get<WhoopStatus>('/api/auth/whoop/status', signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

export function useGarminUpload() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()
  return useMutation({
    mutationFn: ({ file, units }: { file: File; units: 'miles' | 'km' }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('units', units)
      return api.postForm<UploadResult>('/api/garmin/upload', form)
    },
    onSuccess: () => invalidateWorkoutQueries(queryClient, userId),
  })
}

export function useGarminStatus() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['auth', 'garmin-status', userId],
    queryFn: ({ signal }) => api.get<GarminStatus>('/api/auth/garmin/status', signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Sync / Settings
// ---------------------------------------------------------------------------

// Backend returns list[SyncStatusItem] for whoop + garmin
export function useDataStats() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sync', 'stats', userId],
    queryFn: ({ signal }) => api.get<DataStats>('/api/sync/stats', signal),
    staleTime: STALE.SHORT,
    retry: 1,
    enabled: !!userId,
  })
}

export function useSyncStatus() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sync', 'status', userId],
    queryFn: ({ signal }) => api.get<SyncStatus>('/api/sync/status', signal),
    staleTime: STALE.SHORT,
    retry: 1,
    refetchOnWindowFocus: true,
    enabled: !!userId,
    // Poll every 3s while any source is actively syncing; stop when idle
    refetchInterval: (query) => {
      const data = query.state.data
      if (Array.isArray(data) && data.some((s) => s.is_running)) return 3000
      return false
    },
  })
}

export function useDisconnectWhoop() {
  const { userId } = useAuth()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => api.delete('/api/auth/whoop/disconnect'),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['auth', 'whoop-status', userId] })
      void queryClient.invalidateQueries({ queryKey: ['sync', 'status', userId] })
    },
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api.post<null>('/api/auth/change-password', body),
  })
}

export function useTriggerSync() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()
  return useMutation({
    mutationFn: (source: string) =>
      api.post<SyncTriggerResponse>(`/api/sync/trigger/${source}`),
    onSuccess: () => {
      // Kick off status polling immediately — data queries are invalidated
      // by Settings.tsx once the status transitions back to is_running=false.
      void queryClient.invalidateQueries({ queryKey: ['sync', 'status', userId] })
    },
  })
}
