import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  isChunkError: boolean
}

/**
 * Catches render errors from lazy-loaded routes (chunk load failures)
 * and other unexpected component errors. Shows a recovery UI instead
 * of a blank screen.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, isChunkError: false }

  static getDerivedStateFromError(error: Error): State {
    // Detect chunk load failures — these happen when a deploy invalidates
    // cached chunk URLs while a user has the old page open.
    const isChunkError =
      error.name === 'ChunkLoadError' ||
      error.message.includes('Failed to fetch dynamically imported module') ||
      error.message.includes('Loading chunk')
    return { hasError: true, isChunkError }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack)
  }

  handleRetry = () => {
    if (this.state.isChunkError) {
      // Hard reload picks up new chunk URLs from the latest deploy
      window.location.reload()
    } else {
      this.setState({ hasError: false, isChunkError: false })
    }
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <div className="flex flex-col items-center justify-center gap-4 rounded-2xl border border-poor/20 bg-poor/5 px-8 py-12 text-center max-w-md">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-poor/10">
            <svg className="h-6 w-6 text-poor" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
              />
            </svg>
          </div>
          <div className="space-y-1">
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">
              {this.state.isChunkError ? 'New version available' : 'Something went wrong'}
            </p>
            <p className="text-xs text-slate-400 max-w-xs">
              {this.state.isChunkError
                ? 'A newer version of PulseEngine has been deployed. Reload to get the latest.'
                : 'An unexpected error occurred while loading this page.'}
            </p>
          </div>
          <button
            onClick={this.handleRetry}
            className="rounded-lg bg-surface-overlay px-4 py-2 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-surface-border transition-colors border border-surface-border"
          >
            {this.state.isChunkError ? 'Reload' : 'Try again'}
          </button>
        </div>
      </div>
    )
  }
}
