import { useEffect, useRef, useState } from 'react'
import { sheetSocketUrl } from '@/lib/ws'
import { useAuthStore } from '@/stores/authStore'

export interface PresenceUser {
  connection_id: string
  user_id: string
  email: string
  full_name: string
  color: string
}

interface CellEditMsg {
  type: 'cell_edit'
  row_index: number
  cells: { col_key: string; value: unknown }[]
  user_id: string
}

interface RowAddedMsg {
  type: 'row_added'
  row_index: number
  user_id: string
}

interface RowsDeletedMsg {
  type: 'rows_deleted'
  row_indexes: number[]
  user_id: string
}

interface PresenceStateMsg {
  type: 'presence_state'
  users: PresenceUser[]
  self: PresenceUser
}

interface PresenceJoinMsg {
  type: 'presence_join'
  user: PresenceUser
}

interface PresenceLeaveMsg {
  type: 'presence_leave'
  connection_id: string
}

type ServerMsg =
  | CellEditMsg
  | RowAddedMsg
  | RowsDeletedMsg
  | PresenceStateMsg
  | PresenceJoinMsg
  | PresenceLeaveMsg

interface UseSheetSocketHandlers {
  onCellEdit?: (rowIndex: number, cells: { col_key: string; value: unknown }[]) => void
  onRowAdded?: () => void
  onRowsDeleted?: () => void
}

const MAX_BACKOFF_MS = 10_000

export function useSheetSocket(sheetId: string | undefined, handlers: UseSheetSocketHandlers) {
  const accessToken = useAuthStore((s) => s.accessToken)
  const [presence, setPresence] = useState<PresenceUser[]>([])
  const [selfConnectionId, setSelfConnectionId] = useState<string | null>(null)

  // Keep latest handlers/state in refs so the socket effect doesn't churn on every render
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  useEffect(() => {
    if (!sheetId || !accessToken) return

    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let attempt = 0
    let closedByEffect = false

    const connect = () => {
      ws = new WebSocket(sheetSocketUrl(sheetId, accessToken))

      ws.onopen = () => {
        attempt = 0
      }

      ws.onmessage = (event) => {
        let msg: ServerMsg
        try {
          msg = JSON.parse(event.data)
        } catch {
          return
        }

        switch (msg.type) {
          case 'presence_state':
            setPresence(msg.users)
            setSelfConnectionId(msg.self.connection_id)
            break
          case 'presence_join':
            setPresence((prev) => {
              if (prev.some((u) => u.connection_id === msg.user.connection_id)) return prev
              return [...prev, msg.user]
            })
            break
          case 'presence_leave':
            setPresence((prev) => prev.filter((u) => u.connection_id !== msg.connection_id))
            break
          case 'cell_edit':
            handlersRef.current.onCellEdit?.(msg.row_index, msg.cells)
            break
          case 'row_added':
            handlersRef.current.onRowAdded?.()
            break
          case 'rows_deleted':
            handlersRef.current.onRowsDeleted?.()
            break
        }
      }

      ws.onclose = () => {
        if (closedByEffect) return
        setPresence([])
        setSelfConnectionId(null)
        const delay = Math.min(1000 * 2 ** attempt, MAX_BACKOFF_MS)
        attempt += 1
        reconnectTimer = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        ws?.close()
      }
    }

    connect()

    return () => {
      closedByEffect = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [sheetId, accessToken])

  return { presence, selfConnectionId }
}
