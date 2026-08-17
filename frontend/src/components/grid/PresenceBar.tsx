import { useAuthStore } from '@/stores/authStore'
import type { PresenceUser } from '@/hooks/useSheetSocket'

interface PresenceBarProps {
  users: PresenceUser[]
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function PresenceBar({ users }: PresenceBarProps) {
  const currentUserId = useAuthStore((s) => s.user?.id)

  // Collapse multiple tabs/connections from the same user into one avatar
  const byUser = new Map<string, PresenceUser>()
  users.forEach((u) => { if (!byUser.has(u.user_id)) byUser.set(u.user_id, u) })
  const uniqueUsers = Array.from(byUser.values())

  if (uniqueUsers.length === 0) return null

  return (
    <div className="flex shrink-0 items-center -space-x-2">
      {uniqueUsers.slice(0, 5).map((u) => (
        <div
          key={u.user_id}
          title={u.user_id === currentUserId ? `${u.full_name} (you)` : u.full_name}
          className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-background text-[10px] font-semibold text-white"
          style={{ backgroundColor: u.color }}
        >
          {initials(u.full_name || u.email)}
        </div>
      ))}
      {uniqueUsers.length > 5 && (
        <div className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-background bg-muted text-[10px] font-semibold text-muted-foreground">
          +{uniqueUsers.length - 5}
        </div>
      )}
    </div>
  )
}
