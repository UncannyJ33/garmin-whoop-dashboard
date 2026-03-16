import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { todayISO } from './useDateRange'
import type {
  DataStats,
  EnrichedWorkout,
  ExerciseSet,
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
  WeeklySummary,
  WithWithoutResponse,
  WorkoutTypeSummary,
} from '../types/api'

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export function useReadinessToday() {
  return useQuery({
    queryKey: ['readiness', 'today'],
    queryFn: () => api.get<ReadinessResult>(`/api/readiness/today?date=${todayISO()}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: true,
  })
}

export function useReadinessHistory(start: string, end: string) {
  return useQuery({
    queryKey: ['readiness', 'history', start, end],
    queryFn: () =>
      api.get<ReadinessHistoryPoint[]>(`/api/readiness/history?start=${start}&end=${end}`),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
}

// ---------------------------------------------------------------------------
// Workouts
// ---------------------------------------------------------------------------

export function useWorkouts(start: string, end: string) {
  return useQuery({
    queryKey: ['workouts', start, end],
    queryFn: () => api.get<EnrichedWorkout[]>(`/api/workouts?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

export function useWorkoutDetail(id: string) {
  return useQuery({
    queryKey: ['workouts', 'detail', id],
    queryFn: () => api.get<EnrichedWorkout>(`/api/workouts/${id}`),
    staleTime: 30 * 60 * 1000, // workout details don't change
    retry: 1,
    enabled: !!id,
  })
}

export function useExerciseSets(workoutId: string, enabled = true) {
  return useQuery({
    queryKey: ['workouts', 'exercise-sets', workoutId],
    queryFn: () => api.get<ExerciseSet[]>(`/api/workouts/${workoutId}/exercise-sets`),
    staleTime: 30 * 60 * 1000,
    retry: 1,
    enabled: !!workoutId && enabled,
  })
}

export function useStrengthVolume(start: string, end: string) {
  return useQuery({
    queryKey: ['workouts', 'strength-volume', start, end],
    queryFn: () => api.get<StrengthVolume[]>(`/api/workouts/strength-volume?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

export function useStrengthMaxWeight(start: string, end: string) {
  return useQuery({
    queryKey: ['workouts', 'strength-max-weight', start, end],
    queryFn: () => api.get<StrengthMaxWeight[]>(`/api/workouts/strength-max-weight?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

// Backend returns list[WorkoutTypeSummaryItem] sorted by count desc
export function useWorkoutSummary(start: string, end: string) {
  return useQuery({
    queryKey: ['workouts', 'summary', start, end],
    queryFn: () =>
      api.get<WorkoutTypeSummary[]>(`/api/workouts/summary?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

// ---------------------------------------------------------------------------
// Sleep
// ---------------------------------------------------------------------------

export function useSleepInsights(start: string, end: string) {
  return useQuery({
    queryKey: ['sleep', 'insights', start, end],
    queryFn: () => api.get<SleepInsight[]>(`/api/sleep/insights?start=${start}&end=${end}`),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
}

export function useSleepCorrelations(days: number = 30) {
  return useQuery({
    queryKey: ['sleep', 'correlations', days],
    queryFn: () => api.get<SleepCorrelations>(`/api/sleep/correlations?days=${days}`),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
}

export function useSleepConsistency(days: number = 30) {
  return useQuery({
    queryKey: ['sleep', 'consistency', days],
    queryFn: () => api.get<SleepConsistency>(`/api/sleep/consistency?days=${days}`),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
}

// ---------------------------------------------------------------------------
// Trends
// ---------------------------------------------------------------------------

export function useMetricTrend(metric: string, start: string, end: string) {
  return useQuery({
    queryKey: ['trends', metric, start, end],
    queryFn: () => api.get<MetricTrend>(`/api/trends/${metric}?start=${start}&end=${end}`),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
}

// date param maps to the `end` query param (backend defaults to today if omitted)
export function useWeeklySummary(date?: string) {
  return useQuery({
    queryKey: ['trends', 'weekly', date ?? 'today'],
    queryFn: () =>
      api.get<WeeklySummary>(
        date ? `/api/trends/weekly-summary?end=${date}` : '/api/trends/weekly-summary',
      ),
    staleTime: 5 * 60 * 1000,
    retry: 1,
    refetchOnWindowFocus: true,
  })
}

export function useAnomalies(start: string, end: string) {
  return useQuery({
    queryKey: ['trends', 'anomalies', start, end],
    queryFn: () =>
      api.get<Array<{ date: string; metric: string; value: number; direction: string; severity: number }>>(
        `/api/trends/anomalies?start=${start}&end=${end}`,
      ),
    staleTime: 15 * 60 * 1000,
    retry: 1,
  })
}

// ---------------------------------------------------------------------------
// Recovery Activities
// ---------------------------------------------------------------------------

export function useRecovery(start: string, end: string) {
  return useQuery({
    queryKey: ['recovery', start, end],
    queryFn: () => api.get<RecoveryActivity[]>(`/api/recovery?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

export function useRecoveryWithWithout(start: string, end: string) {
  return useQuery({
    queryKey: ['recovery', 'with-without', start, end],
    queryFn: () => api.get<WithWithoutResponse>(`/api/recovery/with-without?start=${start}&end=${end}`),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

// ---------------------------------------------------------------------------
// Sync / Settings
// ---------------------------------------------------------------------------

// Backend returns list[SyncStatusItem] for whoop + garmin
export function useDataStats() {
  return useQuery({
    queryKey: ['sync', 'stats'],
    queryFn: () => api.get<DataStats>('/api/sync/stats'),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })
}

export function useSyncStatus() {
  return useQuery({
    queryKey: ['sync', 'status'],
    queryFn: () => api.get<SyncStatus>('/api/sync/status'),
    staleTime: 60 * 1000, // 1 min — sync status should feel fresh
    retry: 1,
    refetchOnWindowFocus: true,
  })
}

export function useTriggerSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (source: string) =>
      api.post<SyncTriggerResponse>(`/api/sync/trigger/${source}`),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sync'] })
      void queryClient.invalidateQueries({ queryKey: ['readiness'] })
      void queryClient.invalidateQueries({ queryKey: ['workouts'] })
      void queryClient.invalidateQueries({ queryKey: ['sleep'] })
      void queryClient.invalidateQueries({ queryKey: ['trends'] })
    },
  })
}
