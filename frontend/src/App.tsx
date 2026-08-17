import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from '@/components/ui/toaster'
import { useAuthStore } from '@/stores/authStore'
import { authApi } from '@/lib/api'

// Route-level code splitting: SheetPage alone pulls in glide-data-grid,
// which was ~700KB of the ~760KB single bundle every page paid for on
// first load. Splitting it (and the other pages) into separate chunks
// means Login/Dashboard/Upload/Files load fast, and the grid's weight is
// only ever fetched when someone actually opens a sheet.
const LoginPage = lazy(() => import('@/pages/LoginPage').then((m) => ({ default: m.LoginPage })))
const DashboardPage = lazy(() => import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const UploadPage = lazy(() => import('@/pages/UploadPage').then((m) => ({ default: m.UploadPage })))
const FilesPage = lazy(() => import('@/pages/FilesPage').then((m) => ({ default: m.FilesPage })))
const SheetPage = lazy(() => import('@/pages/SheetPage').then((m) => ({ default: m.SheetPage })))

function RouteFallback() {
  return (
    <div className="flex h-screen items-center justify-center">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
    </div>
  )
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})

function AuthBootstrap({ children }: { children: React.ReactNode }) {
  const { setAuth, setLoading, clearAuth } = useAuthStore()

  // On every hard page load, always refresh via the httpOnly cookie — the
  // access token is memory-only (by design) so it's gone after a refresh
  // even though `user` survives in localStorage. Skipping this when `user`
  // was already cached let pages render with accessToken still null, which
  // the axios interceptor could paper over reactively on 401 for normal API
  // calls, but not for the sheet WebSocket handshake (no retry-on-401 there).
  useEffect(() => {
    setLoading(true)
    authApi
      .refresh()
      .then(({ data }) => setAuth(data.user, data.access_token))
      .catch(() => clearAuth())
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return <>{children}</>
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuthStore()

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuthStore()
  if (isLoading) return null
  if (user) return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthBootstrap>
          <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route
              path="/login"
              element={
                <RedirectIfAuthed>
                  <LoginPage />
                </RedirectIfAuthed>
              }
            />
            <Route
              path="/"
              element={
                <RequireAuth>
                  <DashboardPage />
                </RequireAuth>
              }
            />
            <Route
              path="/upload"
              element={
                <RequireAuth>
                  <UploadPage />
                </RequireAuth>
              }
            />
            <Route
              path="/files"
              element={
                <RequireAuth>
                  <FilesPage />
                </RequireAuth>
              }
            />
            <Route
              path="/files/:fileId/sheets/:sheetId"
              element={
                <RequireAuth>
                  <SheetPage />
                </RequireAuth>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </Suspense>
          <Toaster />
        </AuthBootstrap>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
