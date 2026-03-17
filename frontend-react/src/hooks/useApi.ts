import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { todayISO } from './useDateRange'
import type {
  DataStats,
  EnrichedAnomalyPoint,
  EnrichedWorkout,
  ExerciseSet,
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
  WeeklyDigestResponse,
  WeeklySummary,
  WithWithoutResponse,
  WorkoutTypeSummary,
} from '../types/api'

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export function useReadinessToday() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['readiness', 'today', userId],
    queryFn: ({ signal }) => api.get<ReadinessResult>(`/api/readiness/today?date=${todayISO()}`, signal),
    staleTime: 5 * 60 * 1000,
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
    staleTime: 15 * 60 * 1000,
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
    staleTime: 5 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useWorkoutDetail(id: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'detail', id, userId],
    queryFn: ({ signal }) => api.get<EnrichedWorkout>(`/api/workouts/${id}`, signal),
    staleTime: 30 * 60 * 1000, // workout details don't change
    retry: 1,
    enabled: !!id && !!userId,
  })
}

export function useExerciseSets(workoutId: string, enabled = true) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'exercise-sets', workoutId, userId],
    queryFn: ({ signal }) => api.get<ExerciseSet[]>(`/api/workouts/${workoutId}/exercise-sets`, signal),
    staleTime: 30 * 60 * 1000,
    retry: 1,
    enabled: !!workoutId && enabled && !!userId,
  })
}

export function useStrengthVolume(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'strength-volume', start, end, userId],
    queryFn: ({ signal }) => api.get<StrengthVolume[]>(`/api/workouts/strength-volume?start=${start}&end=${end}`, signal),
    staleTime: 5 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useStrengthMaxWeight(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['workouts', 'strength-max-weight', start, end, userId],
    queryFn: ({ signal }) => api.get<StrengthMaxWeight[]>(`/api/workouts/strength-max-weight?start=${start}&end=${end}`, signal),
    staleTime: 5 * 60 * 1000,
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
    staleTime: 5 * 60 * 1000,
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
    staleTime: 15 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useSleepCorrelations(days: number = 30) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sleep', 'correlations', days, userId],
    queryFn: ({ signal }) => api.get<SleepCorrelations>(`/api/sleep/correlations?days=${days}`, signal),
    staleTime: 15 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useSleepConsistency(days: number = 30) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sleep', 'consistency', days, userId],
    queryFn: ({ signal }) => api.get<SleepConsistency>(`/api/sleep/consistency?days=${days}`, signal),
    staleTime: 15 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

// ---------------------------------------------------------------------------
// Trends
// ---------------------------------------------------------------------------

export function useMetricTrend(metric: string, start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['trends', metric, start, end, userId],
    queryFn: ({ signal }) => api.get<MetricTrend>(`/api/trends/${metric}?start=${start}&end=${end}`, signal),
    staleTime: 15 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
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
    staleTime: 5 * 60 * 1000,
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
      api.get<Array<{ date: string; metric: string; value: number; direction: string; severity: number }>>(
        `/api/trends/anomalies?start=${start}&end=${end}`,
        signal,
      ),
    staleTime: 15 * 60 * 1000,
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
      api.get<EnrichedAnomalyPoint[]>(
        `/api/trends/anomalies/enriched?start=${start}&end=${end}`,
        signal,
      ),
    staleTime: 30 * 60 * 1000,
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
    staleTime: 5 * 60 * 1000,
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
  return useQuery({
    queryKey: ['readiness', 'limiting-factors', topN, userId],
    queryFn: ({ signal }) =>
      api.get<LimitingFactor[]>(`/api/readiness/limiting-factors?top_n=${topN}`, signal),
    staleTime: 5 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useTrainingLoadRatio(date?: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['training', 'load-ratio', date ?? 'today', userId],
    queryFn: ({ signal }) =>
      api.get<TrainingLoadResponse>(
        date ? `/api/training/load-ratio?date=${date}` : '/api/training/load-ratio',
        signal,
      ),
    staleTime: 5 * 60 * 1000,
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
    staleTime: 5 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useRecoveryWithWithout(start: string, end: string) {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['recovery', 'with-without', start, end, userId],
    queryFn: ({ signal }) => api.get<WithWithoutResponse>(`/api/recovery/with-without?start=${start}&end=${end}`, signal),
    staleTime: 5 * 60 * 1000,
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
    queryFn: ({ signal }) => api.get<{ connected: boolean }>('/api/auth/whoop/status', signal),
    staleTime: 5 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useGarminStatus() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['auth', 'garmin-status', userId],
    queryFn: ({ signal }) => api.get<{ connected: boolean }>('/api/auth/garmin/status', signal),
    staleTime: 5 * 60 * 1000,
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
    staleTime: 5 * 60 * 1000,
    retry: 1,
    enabled: !!userId,
  })
}

export function useSyncStatus() {
  const { userId } = useAuth()
  return useQuery({
    queryKey: ['sync', 'status', userId],
    queryFn: ({ signal }) => api.get<SyncStatus>('/api/sync/status', signal),
    staleTime: 60 * 1000, // 1 min — sync status should feel fresh
    retry: 1,
    refetchOnWindowFocus: true,
    enabled: !!userId,
  })
}

export function useTriggerSync() {
  const queryClient = useQueryClient()
  const { userId } = useAuth()
  return useMutation({
    mutationFn: (source: string) =>
      api.post<SyncTriggerResponse>(`/api/sync/trigger/${source}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sync', 'stats', userId] })
      void queryClient.invalidateQueries({ queryKey: ['sync', 'status', userId] })
      void queryClient.invalidateQueries({ queryKey: ['readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['workouts'] })
      void queryClient.invalidateQueries({ queryKey: ['sleep'] })
      void queryClient.invalidateQueries({ queryKey: ['trends'] })
    },
  })
}
