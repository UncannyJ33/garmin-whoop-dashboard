import { lazy, Suspense, useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { Layout } from './components/layout/Layout'
import { PageSkeleton } from './components/LoadingState'
import { AuthProvider, useAuth } from './context/AuthContext'
import { setAuthToken } from './api/client'

// ── Eagerly loaded (critical path — first paint) ─────────────────────────────
import { Today } from './pages/Today'
import { Landing } from './pages/Landing'
import { Login } from './pages/Login'

// ── Lazy-loaded (code-split into separate chunks) ────────────────────────────
const Training = lazy(() => import('./pages/Training').then(m => ({ default: m.Training })))
const Recovery = lazy(() => import('./pages/Recovery').then(m => ({ default: m.Recovery })))
const Insights = lazy(() => import('./pages/Insights').then(m => ({ default: m.Insights })))
const Settings = lazy(() => import('./pages/Settings').then(m => ({ default: m.Settings })))
const Onboarding = lazy(() => import('./pages/Onboarding').then(m => ({ default: m.Onboarding })))
const Privacy = lazy(() => import('./pages/Privacy').then(m => ({ default: m.Privacy })))
const GarminHelp = lazy(() => import('./pages/GarminHelp').then(m => ({ default: m.GarminHelp })))
const Showcase = lazy(() => import('./pages/Showcase').then(m => ({ default: m.Showcase })))
const ApiTest = lazy(() => import('./pages/ApiTest').then(m => ({ default: m.ApiTest })))

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      retry: 1,
      // Serve stale cache when offline instead of pausing/erroring
      networkMode: 'offlineFirst',
    },
  },
})

/** Keeps the module-level auth token in client.ts in sync with AuthContext. */
function TokenSync() {
  const { token } = useAuth()
  useEffect(() => {
    setAuthToken(token)
  }, [token])
  return null
}

/** Redirect unauthenticated users to /login. Hold while silent token refresh is in progress. */
function ProtectedLayout() {
  const { isAuthenticated, isInitializing } = useAuth()
  if (isInitializing) return null
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Layout />
}

/**
 * Home route: shows the landing page when not authenticated, Today when logged in.
 * Holds rendering while a silent token refresh is in progress.
 */
function HomeRoute() {
  const { isAuthenticated, isInitializing } = useAuth()
  if (isInitializing) return null
  if (!isAuthenticated) return <Landing />
  return <Layout><Today /></Layout>
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <TokenSync />
          <ErrorBoundary>
          <Suspense fallback={<PageSkeleton />}>
            <Routes>
              {/* Public routes */}
              <Route path="/" element={<HomeRoute />} />
              <Route path="/login" element={<Login />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/help/garmin-export" element={<GarminHelp />} />
              <Route element={<ProtectedLayout />}>
                {/* Authenticated routes */}
                <Route path="/onboarding" element={<Onboarding />} />
                <Route path="/training" element={<Training />} />
                <Route path="/recovery" element={<Recovery />} />
                <Route path="/insights" element={<Insights />} />
                <Route path="/settings" element={<Settings />} />
                {/* Dev / showcase */}
                <Route path="/showcase" element={<Showcase />} />
                <Route path="/dev/api-test" element={<ApiTest />} />
                {/* Legacy redirects — preserve bookmarks from old URL structure */}
                <Route path="/readiness" element={<Navigate to="/" replace />} />
                <Route path="/workouts" element={<Navigate to="/training" replace />} />
                <Route path="/sleep" element={<Navigate to="/recovery" replace />} />
                <Route path="/trends" element={<Navigate to="/insights" replace />} />
                <Route path="/recovery-activities" element={<Navigate to="/recovery" replace />} />
              </Route>
            </Routes>
          </Suspense>
          </ErrorBoundary>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
