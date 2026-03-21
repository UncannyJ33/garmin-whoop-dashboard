import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Today } from './pages/Today'
import { Training } from './pages/Training'
import { Recovery } from './pages/Recovery'
import { Insights } from './pages/Insights'
import { Settings } from './pages/Settings'
import { Landing } from './pages/Landing'
import { Login } from './pages/Login'
import { Onboarding } from './pages/Onboarding'
import { Privacy } from './pages/Privacy'
import { GarminHelp } from './pages/GarminHelp'
import { Demo } from './pages/Demo'
import { Showcase } from './pages/Showcase'
import { ApiTest } from './pages/ApiTest'
import { AuthProvider, useAuth } from './context/AuthContext'
import { setAuthToken } from './api/client'

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
  return <Today />
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <TokenSync />
          <Routes>
            {/* Public routes */}
            <Route path="/" element={<HomeRoute />} />
            <Route path="/login" element={<Login />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/help/garmin-export" element={<GarminHelp />} />
            <Route path="/demo" element={<Demo />} />
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
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
