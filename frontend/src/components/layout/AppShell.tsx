import { useState } from 'react'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { TopBar } from './TopBar'
import { Sidebar } from './Sidebar'
import { cn } from '@/lib/utils'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true)

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-background text-foreground">
      <TopBar />

      <div className="flex min-h-0 flex-1">
        {/* Sidebar — nav rail: Dashboard / Upload / Files */}
        <div
          className={cn(
            'shrink-0 transition-all duration-200',
            sidebarOpen ? 'w-[200px]' : 'w-0 overflow-hidden',
          )}
        >
          <Sidebar />
        </div>

        {/* Toggle button */}
        <button
          className="relative z-10 -ml-px flex h-full w-5 shrink-0 items-center justify-center border-r border-border bg-background hover:bg-accent"
          onClick={() => setSidebarOpen((v) => !v)}
          aria-label={sidebarOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          {sidebarOpen ? (
            <PanelLeftClose className="h-3.5 w-3.5 text-muted-foreground" />
          ) : (
            <PanelLeftOpen className="h-3.5 w-3.5 text-muted-foreground" />
          )}
        </button>

        {/* Main content */}
        <main className="min-w-0 flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  )
}
