import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Readiness } from './pages/Readiness'
import { Workouts } from './pages/Workouts'
import { Sleep } from './pages/Sleep'
import { Trends } from './pages/Trends'
import { Settings } from './pages/Settings'
import { RecoveryActivities } from './pages/RecoveryActivities'
import { Showcase } from './pages/Showcase'
import { ApiTest } from './pages/ApiTest'

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

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Readiness />} />
            <Route path="/workouts" element={<Workouts />} />
            <Route path="/sleep" element={<Sleep />} />
            <Route path="/trends" element={<Trends />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/recovery-activities" element={<RecoveryActivities />} />
            <Route path="/showcase" element={<Showcase />} />
            <Route path="/dev/api-test" element={<ApiTest />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
