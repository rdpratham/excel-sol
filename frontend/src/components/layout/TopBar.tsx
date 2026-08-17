import { LogOut, ChevronDown } from 'lucide-react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import * as Avatar from '@radix-ui/react-avatar'
import { useAuthStore } from '@/stores/authStore'
import { authApi } from '@/lib/api'
import { Logo } from '@/components/ui/logo'
import { cn } from '@/lib/utils'

const ROLE_BADGE: Record<string, string> = {
  admin: 'bg-violet-100 text-violet-700 dark:bg-violet-900 dark:text-violet-300',
  editor: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  viewer: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
}

export function TopBar() {
  const { user, clearAuth } = useAuthStore()

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {
      // Best-effort — clear local state regardless
    }
    clearAuth()
    window.location.href = '/login'
  }

  if (!user) return null

  const initials = user.full_name
    .split(' ')
    .map((n) => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <header className="flex h-12 items-center justify-between border-b border-border bg-background px-4">
      {/* Brand */}
      <Logo size="sm" />

      {/* User menu */}
      <DropdownMenu.Root>
        <DropdownMenu.Trigger asChild>
          <button className="flex items-center gap-2 rounded-md px-2 py-1 text-sm hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <Avatar.Root className="h-7 w-7 rounded-full bg-primary">
              <Avatar.Fallback className="flex h-full w-full items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                {initials}
              </Avatar.Fallback>
            </Avatar.Root>
            <span className="hidden font-medium sm:inline">{user.full_name}</span>
            <span className={cn('hidden rounded px-1.5 py-0.5 text-xs font-medium sm:inline', ROLE_BADGE[user.role])}>
              {user.role}
            </span>
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
          </button>
        </DropdownMenu.Trigger>

        <DropdownMenu.Portal>
          <DropdownMenu.Content
            className="z-50 min-w-[180px] rounded-md border bg-popover p-1 shadow-md"
            align="end"
            sideOffset={4}
          >
            <div className="px-2 py-1.5 text-xs text-muted-foreground">{user.email}</div>
            <DropdownMenu.Separator className="my-1 h-px bg-border" />
            <DropdownMenu.Item
              className="flex cursor-pointer items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent"
              onSelect={handleLogout}
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </DropdownMenu.Item>
          </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </header>
  )
}
