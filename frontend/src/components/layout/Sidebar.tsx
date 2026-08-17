import { useLocation, useNavigate } from 'react-router-dom'
import { FolderOpen, LayoutDashboard, Upload } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Dashboard', icon: LayoutDashboard, path: '/', exact: true, color: 'text-blue-500', bg: 'bg-blue-500/10' },
  { label: 'Upload', icon: Upload, path: '/upload', exact: true, color: 'text-emerald-500', bg: 'bg-emerald-500/10' },
  { label: 'Files', icon: FolderOpen, path: '/files', exact: false, color: 'text-rose-500', bg: 'bg-rose-500/10' },
]

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()

  const isActive = (path: string, exact: boolean) =>
    exact ? location.pathname === path : location.pathname.startsWith(path)

  return (
    <aside className="flex h-full w-full flex-col gap-1 border-r border-border bg-background p-2.5">
      {NAV_ITEMS.map(({ label, icon: Icon, path, exact, color, bg }) => {
        const active = isActive(path, exact)
        return (
          <button
            key={path}
            onClick={() => navigate(path)}
            className={cn(
              'group flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm font-medium text-muted-foreground transition-all hover:bg-accent hover:text-foreground',
              active && 'bg-accent text-foreground shadow-soft',
            )}
          >
            <span
              className={cn(
                'flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition-colors',
                active ? bg : 'bg-muted/60 group-hover:bg-muted',
              )}
            >
              <Icon className={cn('h-4 w-4 transition-colors', active ? color : 'text-muted-foreground')} />
            </span>
            {label}
          </button>
        )
      })}
    </aside>
  )
}
