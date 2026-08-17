import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, BarChart3, Brain, Shield, Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Logo } from '@/components/ui/logo'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { toast } from '@/hooks/useToast'
import type { ApiError } from '@/types'
import type { AxiosError } from 'axios'

const FEATURES = [
  { icon: Brain, label: 'AI-Powered Analysis', desc: 'Ask questions in plain English' },
  { icon: BarChart3, label: 'Live Spreadsheet Grid', desc: 'Excel-class editing experience' },
  { icon: Shield, label: 'Enterprise Security', desc: 'RBAC · audit trail · JWT auth' },
]

export function LoginPage() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsLoading(true)
    try {
      const { data } = await authApi.login(email.trim(), password)
      setAuth(data.user, data.access_token)
      navigate('/', { replace: true })
    } catch (err) {
      const axiosErr = err as AxiosError<ApiError>
      const msg = axiosErr.response?.data?.error?.message ?? 'Sign-in failed. Please try again.'
      setError(msg)
      toast({ variant: 'destructive', title: 'Sign in failed', description: msg })
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      {/* ── Left panel: feature showcase ── */}
      <div className="relative hidden flex-col justify-between overflow-hidden bg-foreground p-10 text-background lg:flex lg:w-5/12">
        <div
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              'radial-gradient(700px circle at 15% 15%, hsl(217 91% 52% / 0.20), transparent 60%),' +
              'radial-gradient(700px circle at 85% 40%, hsl(152 76% 40% / 0.16), transparent 60%),' +
              'radial-gradient(700px circle at 30% 100%, hsl(0 84% 55% / 0.14), transparent 60%)',
          }}
        />
        <Logo size="md" showText />

        <div className="space-y-8">
          <h2 className="text-4xl font-bold leading-tight">
            Spreadsheets,{' '}
            <span className="brand-gradient-text">reimagined</span>{' '}
            for the AI era.
          </h2>
          <p className="text-lg text-muted-foreground" style={{ color: 'hsl(215 20% 65%)' }}>
            Upload any Excel or CSV file, query it in plain English, and collaborate live — all in the browser.
          </p>

          <div className="space-y-5">
            {FEATURES.map(({ icon: Icon, label, desc }) => (
              <div key={label} className="flex items-start gap-3">
                <div className="brand-gradient mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl shadow-soft">
                  <Icon className="h-4 w-4 text-white" />
                </div>
                <div>
                  <p className="font-semibold text-white">{label}</p>
                  <p className="text-sm" style={{ color: 'hsl(215 20% 65%)' }}>{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs" style={{ color: 'hsl(215 20% 45%)' }}>
          © {new Date().getFullYear()} MindSpread. All rights reserved. Created by Pratham Jain.
        </p>
      </div>

      {/* ── Right panel: login form ── */}
      <div className="brand-mesh flex flex-1 flex-col items-center justify-center bg-background px-6 py-12">
        {/* Mobile logo */}
        <div className="mb-8 lg:hidden">
          <Logo size="md" />
        </div>

        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">Sign in</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Enter your credentials to access your workspace.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div className="space-y-1.5">
              <Label htmlFor="email">Email address</Label>
              <Input
                id="email"
                type="email"
                placeholder="you@company.com"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isLoading}
                className="h-10"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                  className="h-10 pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  disabled={isLoading}
                  tabIndex={-1}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-muted-foreground hover:text-foreground disabled:opacity-50"
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error && (
              <div
                role="alert"
                className="rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-xs text-destructive"
              >
                {error}
              </div>
            )}

            <Button
              type="submit"
              className="hover-lift h-10 w-full gap-2 text-sm font-semibold shadow-soft"
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Signing in…
                </>
              ) : (
                'Sign in'
              )}
            </Button>
          </form>

          <p className="mt-6 text-center text-xs text-muted-foreground">
            Don't have an account?{' '}
            <span className="font-medium text-primary">Contact your administrator.</span>
          </p>

          {/* Blue / Green / Red brand accent dots */}
          <div className="mt-10 flex items-center justify-center gap-2">
            <span className="h-2 w-2 rounded-full bg-blue-500" />
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            <span className="h-2 w-2 rounded-full bg-red-500" />
          </div>
        </div>
      </div>
    </div>
  )
}
