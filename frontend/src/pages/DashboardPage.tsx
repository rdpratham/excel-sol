import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Rows3, HardDrive, MessageSquare, Files } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AppShell } from '@/components/layout/AppShell'
import { useAuthStore } from '@/stores/authStore'
import type { SpreadsheetFile, Sheet } from '@/types'

// Phase 2 will wire these to real API data via TanStack Query.
// For Phase 1 we render the shell with zero-state UI.

const KPI_CARDS = [
  { label: 'Total Files', icon: Files, value: '—' },
  { label: 'Total Sheets', icon: FileSpreadsheet, value: '—' },
  { label: 'Total Rows', icon: Rows3, value: '—' },
  { label: 'Storage Used', icon: HardDrive, value: '—' },
  { label: 'AI Queries (month)', icon: MessageSquare, value: '—' },
]

export function DashboardPage() {
  const user = useAuthStore((s) => s.user)
  const navigate = useNavigate()

  const handleSheetSelect = (file: SpreadsheetFile, sheet: Sheet) => {
    navigate(`/files/${file.id}/sheets/${sheet.id}`)
  }

  return (
    <AppShell onSheetSelect={handleSheetSelect}>
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
          {KPI_CARDS.map(({ label, icon: Icon, value }) => (
            <Card key={label}>
              <CardHeader className="flex flex-row items-center justify-between pb-2 pt-4">
                <CardTitle className="text-xs font-medium text-muted-foreground">{label}</CardTitle>
                <Icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent className="pb-4">
                <p className="font-mono text-2xl font-semibold">{value}</p>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Recent files placeholder */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">Recent Files</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center gap-3 py-10 text-center">
              <FileSpreadsheet className="h-10 w-10 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">
                Upload a file using the sidebar to get started.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}
