import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Rows3, HardDrive, MessageSquare, Files, Loader2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AppShell } from '@/components/layout/AppShell'
import { useAuthStore } from '@/stores/authStore'
import { statsApi } from '@/lib/api'
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

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    ready: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300',
    processing: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
    uploading: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300',
    failed: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  }
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ${styles[status] ?? ''}`}>
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
    { label: 'Total Files', icon: Files, value: stats ? formatNum(stats.total_files) : '—' },
    { label: 'Total Sheets', icon: FileSpreadsheet, value: stats ? formatNum(stats.total_sheets) : '—' },
    { label: 'Total Rows', icon: Rows3, value: stats ? formatNum(stats.total_rows) : '—' },
    { label: 'Storage Used', icon: HardDrive, value: stats ? formatBytes(stats.storage_bytes) : '—' },
    { label: 'AI Queries (month)', icon: MessageSquare, value: stats ? formatNum(stats.ai_queries_this_month) : '—' },
  ]

  return (
    <AppShell>
      <div className="p-6">
        {/* Welcome */}
        <div className="mb-6">
          <h2 className="text-xl font-semibold">
            Welcome back, {user?.full_name.split(' ')[0]}
          </h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Here's what's happening with your data.
          </p>
        </div>

        {/* KPI cards */}
        <div className="mb-8 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
          {kpiCards.map(({ label, icon: Icon, value }) => (
            <Card key={label}>
              <CardHeader className="flex flex-row items-center justify-between pb-2 pt-4">
                <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
                <Icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent className="pb-4">
                {isLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                ) : (
                  <p className="font-mono text-2xl font-semibold">{value}</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Recent files */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Recent Files</CardTitle>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : !stats?.recent_files?.length ? (
              <div className="flex flex-col items-center gap-3 py-10 text-center">
                <FileSpreadsheet className="h-10 w-10 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">
                  Upload a file using the sidebar to get started.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs text-muted-foreground">
                      <th className="pb-2 font-medium">Name</th>
                      <th className="pb-2 font-medium">Sheets</th>
                      <th className="pb-2 font-medium">Rows</th>
                      <th className="pb-2 font-medium">Size</th>
                      <th className="pb-2 font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {stats.recent_files.map((file) => (
                      <tr
                        key={file.id}
                        className="cursor-pointer hover:bg-accent/50"
                        onClick={() => file.sheets[0] && handleSheetSelect(file, file.sheets[0])}
                      >
                        <td className="py-2 pr-4 font-medium">{file.display_name}</td>
                        <td className="py-2 pr-4 tabular-nums text-muted-foreground">{file.sheet_count}</td>
                        <td className="py-2 pr-4 tabular-nums text-muted-foreground">
                          {file.total_rows.toLocaleString()}
                        </td>
                        <td className="py-2 pr-4 text-muted-foreground">{formatBytes(file.size_bytes)}</td>
                        <td className="py-2">
                          <StatusBadge status={file.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
