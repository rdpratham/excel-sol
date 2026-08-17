import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Download,
  Loader2,
  Plus,
  Redo2,
  Trash2,
  Undo2,
} from 'lucide-react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { SpreadsheetGrid, type GridRow } from '@/components/grid/SpreadsheetGrid'
import { PresenceBar } from '@/components/grid/PresenceBar'
import { filesApi, rowsApi } from '@/lib/api'
import { useAuthStore } from '@/stores/authStore'
import { useSheetSocket } from '@/hooks/useSheetSocket'
import { toast } from '@/hooks/useToast'
import type { SpreadsheetFile, Sheet } from '@/types'

const PAGE_SIZE = 500

interface HistoryEntry {
  rowIndex: number
  colKey: string
  oldValue: unknown
  newValue: unknown
}

export function SheetPage() {
  const { fileId, sheetId } = useParams<{ fileId: string; sheetId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const accessToken = useAuthStore((s) => s.accessToken)

  // Local rows buffer — loaded from API, mutated locally for instant feedback
  const [localRows, setLocalRows] = useState<GridRow[]>([])
  const [page, setPage] = useState(1)
  const [totalRows, setTotalRows] = useState(0)
  const [selectedRows, setSelectedRows] = useState<number[]>([])

  // Undo / redo stacks
  const undoStack = useRef<HistoryEntry[]>([])
  const redoStack = useRef<HistoryEntry[]>([])

  // Pending saves (debounced) — col_key → value per row
  const pendingSaves = useRef<Map<string, { rowIndex: number; col_key: string; value: unknown }>>(new Map())
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Fetch file metadata ────────────────────────────────────────────────────
  const { data: file } = useQuery({
    queryKey: ['file', fileId],
    queryFn: () => filesApi.get(fileId!).then((r) => r.data),
    enabled: !!fileId,
  })
  const sheet = file?.sheets.find((s) => s.id === sheetId)

  // ── Fetch rows ─────────────────────────────────────────────────────────────
  const { data: rowsData, isLoading } = useQuery({
    queryKey: ['rows', fileId, sheetId, page],
    queryFn: () => filesApi.getRows(fileId!, sheetId!, page, PAGE_SIZE).then((r) => r.data),
    enabled: !!fileId && !!sheetId,
  })

  useEffect(() => {
    if (rowsData) {
      setLocalRows(rowsData.rows as GridRow[])
      setTotalRows(rowsData.total)
    }
  }, [rowsData])

  // ── Real-time sync — other tabs/users editing the same sheet ───────────────
  // Cell edits apply straight to local state (indices are stable). Row
  // add/delete can shift every row_index after them, so those just refetch
  // the current page rather than trying to patch indices locally.
  const handleRemoteCellEdit = useCallback(
    (rowIndex: number, cells: { col_key: string; value: unknown }[]) => {
      setLocalRows((prev) => {
        if (rowIndex >= prev.length) return prev
        const next = [...prev]
        const patch: GridRow = {}
        cells.forEach((c) => { patch[c.col_key] = c.value })
        next[rowIndex] = { ...next[rowIndex], ...patch }
        return next
      })
    },
    [],
  )

  const handleRemoteRowsChanged = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['rows', fileId, sheetId, page] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }, [queryClient, fileId, sheetId, page])

  const { presence } = useSheetSocket(sheetId, {
    onCellEdit: handleRemoteCellEdit,
    onRowAdded: handleRemoteRowsChanged,
    onRowsDeleted: handleRemoteRowsChanged,
  })

  // ── Cell edit — instant local update + debounced save ─────────────────────
  const handleCellEdited = useCallback(
    (rowIndex: number, colKey: string, newValue: unknown) => {
      setLocalRows((prev) => {
        const oldValue = prev[rowIndex]?.[colKey]
        // Push to undo stack
        undoStack.current.push({ rowIndex, colKey, oldValue, newValue })
        redoStack.current = []

        const next = [...prev]
        next[rowIndex] = { ...next[rowIndex], [colKey]: newValue }
        return next
      })

      // Queue debounced save (500ms)
      const key = `${rowIndex}:${colKey}`
      pendingSaves.current.set(key, { rowIndex, col_key: colKey, value: newValue })

      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(flushSaves, 500)
    },
    [],
  )

  const flushSaves = useCallback(async () => {
    if (!fileId || !sheetId || pendingSaves.current.size === 0) return

    // Group pending saves by row
    const byRow = new Map<number, { col_key: string; value: unknown }[]>()
    pendingSaves.current.forEach(({ rowIndex, col_key, value }) => {
      if (!byRow.has(rowIndex)) byRow.set(rowIndex, [])
      byRow.get(rowIndex)!.push({ col_key, value })
    })
    pendingSaves.current.clear()

    try {
      await Promise.all(
        Array.from(byRow.entries()).map(([rowIndex, cells]) =>
          rowsApi.patch(fileId, sheetId, rowIndex, cells),
        ),
      )
    } catch {
      toast({ variant: 'destructive', title: 'Autosave failed', description: 'Changes may not have been saved' })
    }
  }, [fileId, sheetId])

  // Flush on unmount
  useEffect(() => () => { flushSaves() }, [flushSaves])

  // ── Undo ──────────────────────────────────────────────────────────────────
  const handleUndo = useCallback(() => {
    const entry = undoStack.current.pop()
    if (!entry) return
    redoStack.current.push({ ...entry, oldValue: entry.newValue, newValue: entry.oldValue })
    setLocalRows((prev) => {
      const next = [...prev]
      next[entry.rowIndex] = { ...next[entry.rowIndex], [entry.colKey]: entry.oldValue }
      return next
    })
    pendingSaves.current.set(`${entry.rowIndex}:${entry.colKey}`, {
      rowIndex: entry.rowIndex, col_key: entry.colKey, value: entry.oldValue,
    })
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(flushSaves, 500)
  }, [flushSaves])

  // ── Redo ──────────────────────────────────────────────────────────────────
  const handleRedo = useCallback(() => {
    const entry = redoStack.current.pop()
    if (!entry) return
    undoStack.current.push({ ...entry, oldValue: entry.newValue, newValue: entry.oldValue })
    setLocalRows((prev) => {
      const next = [...prev]
      next[entry.rowIndex] = { ...next[entry.rowIndex], [entry.colKey]: entry.oldValue }
      return next
    })
    pendingSaves.current.set(`${entry.rowIndex}:${entry.colKey}`, {
      rowIndex: entry.rowIndex, col_key: entry.colKey, value: entry.oldValue,
    })
    if (saveTimer.current) clearTimeout(saveTimer.current)
    saveTimer.current = setTimeout(flushSaves, 500)
  }, [flushSaves])

  // ── Keyboard shortcuts ────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) { e.preventDefault(); handleUndo() }
      if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); handleRedo() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [handleUndo, handleRedo])

  // ── Add row ───────────────────────────────────────────────────────────────
  const handleAddRow = useCallback(async () => {
    if (!fileId || !sheetId) return
    const emptyRow: GridRow = {}
    sheet?.columns?.forEach((c) => { emptyRow[c.name] = '' })
    try {
      await rowsApi.append(fileId, sheetId, emptyRow)
      setLocalRows((prev) => [...prev, emptyRow])
      setTotalRows((n) => n + 1)
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    } catch {
      toast({ variant: 'destructive', title: 'Failed to add row' })
    }
  }, [fileId, sheetId, sheet, queryClient])

  // ── Delete selected rows ──────────────────────────────────────────────────
  const handleDeleteRows = useCallback(async () => {
    if (!fileId || !sheetId || selectedRows.length === 0) return
    try {
      await rowsApi.deleteRows(fileId, sheetId, selectedRows)
      setLocalRows((prev) => prev.filter((_, i) => !selectedRows.includes(i)))
      setTotalRows((n) => n - selectedRows.length)
      setSelectedRows([])
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      queryClient.invalidateQueries({ queryKey: ['file', fileId] })
    } catch {
      toast({ variant: 'destructive', title: 'Failed to delete rows' })
    }
  }, [fileId, sheetId, selectedRows, queryClient])

  // ── Export ────────────────────────────────────────────────────────────────
  const handleExport = useCallback(async () => {
    if (!fileId || !sheetId || !accessToken) return
    const url = rowsApi.exportUrl(fileId, sheetId)
    const res = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } })
    if (!res.ok) { toast({ variant: 'destructive', title: 'Export failed' }); return }
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${file?.display_name ?? 'export'}_${sheet?.name ?? 'sheet'}.xlsx`
    a.click()
    URL.revokeObjectURL(a.href)
  }, [fileId, sheetId, accessToken, file, sheet])

  const handleSheetSelect = (f: SpreadsheetFile, s: Sheet) => {
    navigate(`/files/${f.id}/sheets/${s.id}`)
  }

  const columns = sheet?.columns ?? rowsData?.columns ?? []

  return (
    <AppShell activeSheetId={sheetId} onSheetSelect={handleSheetSelect}>
      <div className="flex h-full flex-col">
        {/* ── Toolbar ───────────────────────────────────────────────────── */}
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5">
          {/* File / sheet name */}
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-muted-foreground">{file?.display_name}</p>
            <p className="truncate text-sm font-semibold">{sheet?.name ?? '…'}</p>
          </div>

          {/* Row / col count */}
          {!isLoading && (
            <p className="shrink-0 text-xs text-muted-foreground">
              {totalRows.toLocaleString()} rows · {columns.length} cols
            </p>
          )}

          {/* Who else is viewing this sheet right now */}
          <PresenceBar users={presence} />

          <div className="h-4 w-px bg-border" />

          {/* Undo / Redo */}
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={handleUndo} title="Undo (Ctrl+Z)">
            <Undo2 className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={handleRedo} title="Redo (Ctrl+Y)">
            <Redo2 className="h-3.5 w-3.5" />
          </Button>

          <div className="h-4 w-px bg-border" />

          {/* Add row */}
          <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs" onClick={handleAddRow}>
            <Plus className="h-3.5 w-3.5" />
            Add row
          </Button>

          {/* Delete selected */}
          {selectedRows.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 px-2 text-xs text-destructive hover:text-destructive"
              onClick={handleDeleteRows}
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete {selectedRows.length}
            </Button>
          )}

          <div className="h-4 w-px bg-border" />

          {/* Export */}
          <Button variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs" onClick={handleExport}>
            <Download className="h-3.5 w-3.5" />
            Export
          </Button>
        </div>

        {/* ── Grid ─────────────────────────────────────────────────────── */}
        <div className="min-h-0 flex-1">
          {isLoading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : columns.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              This sheet is empty
            </div>
          ) : (
            <SpreadsheetGrid
              columns={columns}
              rows={localRows}
              totalRows={totalRows}
              onCellEdited={handleCellEdited}
              onSelectionChange={setSelectedRows}
            />
          )}
        </div>

        {/* ── Pagination (for sheets > PAGE_SIZE rows) ──────────────────── */}
        {totalRows > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-border px-4 py-1.5">
            <p className="text-xs text-muted-foreground">
              Showing rows {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, totalRows)} of {totalRows.toLocaleString()}
            </p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" className="h-7 text-xs" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
                Prev
              </Button>
              <Button variant="outline" size="sm" className="h-7 text-xs" disabled={page * PAGE_SIZE >= totalRows} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
