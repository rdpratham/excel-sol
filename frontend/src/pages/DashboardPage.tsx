import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Rows3, HardDrive, MessageSquare, Files, Loader2, Sparkles, Upload } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { AppShell } from '@/components/layout/AppShell'
import { useAuthStore } from '@/stores/authStore'
import { statsApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { SpreadsheetFile, Sheet } from '@/types'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toString()
}

const STATUS_STYLES: Record<string, string> = {
  ready: 'bg-emerald-500',
  processing: 'bg-blue-500',
  uploading: 'bg-amber-500',
  failed: 'bg-red-500',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium capitalize text-muted-foreground">
      <span className={cn('h-1.5 w-1.5 rounded-full', STATUS_STYLES[status] ?? 'bg-muted-foreground')} />
      {status}
    </span>
  )
}

export function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const navigate = useNavigate()

  const { data: stats, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: () => statsApi.get().then((r) => r.data),
  })

  const handleSheetSelect = (file: SpreadsheetFile, sheet: Sheet) => {
    navigate(`/files/${file.id}/sheets/${sheet.id}`)
  }

  const kpiCards = [
    {
      label: 'Total Files', icon: Files,
      value: stats ? formatNum(stats.total_files) : '—',
      color: 'text-blue-500', bg: 'bg-blue-500/10',
    },
    {
      label: 'Total Sheets', icon: FileSpreadsheet,
      value: stats ? formatNum(stats.total_sheets) : '—',
      color: 'text-emerald-500', bg: 'bg-emerald-500/10',
    },
    {
      label: 'Total Rows', icon: Rows3,
      value: stats ? formatNum(stats.total_rows) : '—',
      color: 'text-violet-500', bg: 'bg-violet-500/10',
    },
    {
      label: 'Storage Used', icon: HardDrive,
      value: stats ? formatBytes(stats.storage_bytes) : '—',
      color: 'text-amber-500', bg: 'bg-amber-500/10',
    },
    {
      label: 'AI Queries (month)', icon: MessageSquare,
      value: stats ? formatNum(stats.ai_queries_this_month) : '—',
      color: 'text-rose-500', bg: 'bg-rose-500/10',
    },
  ]

  return (
    <AppShell>
      <div className="brand-mesh min-h-full p-6">
        {/* Welcome */}
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4 animate-fade-in-up">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">
              Welcome back, <span className="brand-gradient-text">{user?.full_name.split(' ')[0]}</span>
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Here's what's happening with your data.
            </p>
          </div>
          <button
            onClick={() => navigate('/upload')}
            className="brand-gradient hover-lift flex shrink-0 items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-soft"
          >
            <Upload className="h-4 w-4" />
            Upload a file
          </button>
        </div>

        {/* KPI cards */}
        <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {kpiCards.map(({ label, icon: Icon, value, color, bg }, i) => (
            <Card
              key={label}
              className="hover-lift animate-fade-in-up p-4"
              style={{ animationDelay: `${i * 60}ms` }}
            >
              <div className={cn('mb-3 flex h-9 w-9 items-center justify-center rounded-lg', bg)}>
                <Icon className={cn('h-[18px] w-[18px]', color)} />
              </div>
              <p className="text-xs font-medium text-muted-foreground">{label}</p>
              {isLoading ? (
                <Loader2 className="mt-1.5 h-5 w-5 animate-spin text-muted-foreground" />
              ) : (
                <p className="mt-1 font-mono text-2xl font-bold tabular-nums">{value}</p>
              )}
            </Card>
          ))}
        </div>

        {/* Recent files */}
        <Card className="animate-fade-in-up overflow-hidden" style={{ animationDelay: '300ms' }}>
          <div className="flex items-center justify-between border-b border-border px-5 py-3.5">
            <h3 className="text-sm font-semibold">Recent Files</h3>
            {!isLoading && !!stats?.recent_files?.length && (
              <button
                onClick={() => navigate('/files')}
                className="text-xs font-medium text-primary hover:underline"
              >
                View all
              </button>
            )}
          </div>
          <CardContent className="p-0">
            {isLoading ? (
              <div className="flex items-center justify-center py-10">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : !stats?.recent_files?.length ? (
              <div className="flex flex-col items-center gap-3 py-14 text-center">
                <div className="brand-gradient flex h-14 w-14 items-center justify-center rounded-2xl shadow-soft">
                  <Sparkles className="h-6 w-6 text-white" />
                </div>
                <p className="text-sm text-muted-foreground">
                  No files yet — upload one to get started.
                </p>
                <button
                  onClick={() => navigate('/upload')}
                  className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                >
                  Upload a file
                </button>
              </div>
            ) : (
              <div className="divide-y divide-border">
                {stats.recent_files.map((file) => (
                  <button
                    key={file.id}
                    className="flex w-full items-center gap-3 px-5 py-3 text-left transition-colors hover:bg-accent/60"
                    onClick={() => file.sheets[0] && handleSheetSelect(file, file.sheets[0])}
                  >
                    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
                      <FileSpreadsheet className="h-[18px] w-[18px] text-emerald-500" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{file.display_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {file.sheet_count} sheet{file.sheet_count !== 1 ? 's' : ''} · {file.total_rows.toLocaleString()} rows · {formatBytes(file.size_bytes)}
                      </p>
                    </div>
                    <StatusBadge status={file.status} />
                  </button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
