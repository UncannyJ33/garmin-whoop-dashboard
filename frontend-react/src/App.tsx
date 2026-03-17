import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Readiness } from './pages/Readiness'
import { Today } from './pages/Today'
import { Workouts } from './pages/Workouts'
import { Sleep } from './pages/Sleep'
import { Trends } from './pages/Trends'
import { Settings } from './pages/Settings'
import { RecoveryActivities } from './pages/RecoveryActivities'
import { Login } from './pages/Login'
import { Privacy } from './pages/Privacy'
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

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <TokenSync />
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route element={<ProtectedLayout />}>
              <Route path="/" element={<Today />} />
              <Route path="/readiness" element={<Readiness />} />
              <Route path="/workouts" element={<Workouts />} />
              <Route path="/sleep" element={<Sleep />} />
              <Route path="/trends" element={<Trends />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/recovery-activities" element={<RecoveryActivities />} />
              <Route path="/showcase" element={<Showcase />} />
              <Route path="/dev/api-test" element={<ApiTest />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
