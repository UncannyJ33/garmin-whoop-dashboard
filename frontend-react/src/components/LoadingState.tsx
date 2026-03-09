import React from 'react'

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
