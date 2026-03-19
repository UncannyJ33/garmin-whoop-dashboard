import React from 'react'
import { Link } from 'react-router-dom'

// Skeleton shapes

function SkeletonBlock({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} />
}

export function MetricCardSkeleton() {
  return (
    <div className="card-sm border border-surface-border space-y-2">
      <SkeletonBlock className="h-3 w-20" />
      <SkeletonBlock className="h-7 w-16" />
      <SkeletonBlock className="h-3 w-24" />
    </div>
  )
}

export function ChartSkeleton({ height = 220 }: { height?: number }) {
  return (
    <div className="card space-y-2">
      <SkeletonBlock className="h-4 w-32" />
      <SkeletonBlock className="w-full rounded-xl" style={{ height }} />
    </div>
  )
}

export function WorkoutRowSkeleton() {
  return (
    <div className="card-sm border border-surface-border">
      <div className="flex items-center gap-3">
        <SkeletonBlock className="h-3 w-12" />
        <SkeletonBlock className="h-4 flex-1" />
        <SkeletonBlock className="h-3 w-10" />
        <SkeletonBlock className="h-3 w-8" />
      </div>
    </div>
  )
}

/** Full-page empty state shown when a user has no synced data yet. */
export function NoDataState({ message }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center px-4">
      <div className="mb-4 text-4xl select-none">📡</div>
      <h2 className="text-lg font-semibold text-slate-200 mb-1">No data yet</h2>
      <p className="text-sm text-slate-400 max-w-xs leading-relaxed">
        {message ?? 'Connect a device from Settings to start seeing your insights here.'}
      </p>
      <Link
        to="/settings"
        className="mt-5 inline-block bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-xl px-4 py-2 transition-colors"
      >
        Go to Settings
      </Link>
    </div>
  )
}

export function PageSkeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <SkeletonBlock className="h-8 w-48" />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <MetricCardSkeleton key={i} />
        ))}
      </div>
      <ChartSkeleton />
      <ChartSkeleton height={180} />
    </div>
  )
}
