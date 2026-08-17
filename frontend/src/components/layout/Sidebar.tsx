import { useLocation, useNavigate } from 'react-router-dom'
import { FolderOpen, LayoutDashboard, Upload } from 'lucide-react'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Dashboard', icon: LayoutDashboard, path: '/', exact: true },
  { label: 'Upload', icon: Upload, path: '/upload', exact: true },
  { label: 'Files', icon: FolderOpen, path: '/files', exact: false },
]

export function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()

  const isActive = (path: string, exact: boolean) =>
    exact ? location.pathname === path : location.pathname.startsWith(path)

  return (
    <aside className="flex h-full w-full flex-col border-r border-border bg-background py-2">
      {NAV_ITEMS.map(({ label, icon: Icon, path, exact }) => {
        const active = isActive(path, exact)
        return (
          <button
            key={path}
            onClick={() => navigate(path)}
            className={cn(
              'flex items-center gap-2.5 border-l-2 border-transparent px-4 py-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
              active && 'border-primary bg-accent text-foreground',
            )}
          >
            <Icon className="h-4 w-4" />
            {label}
          </button>
        )
      })}
    </aside>
  )
}
