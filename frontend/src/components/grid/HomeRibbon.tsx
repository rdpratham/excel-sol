import { useState } from 'react'
import type { AxiosError } from 'axios'
import type { GridSelection } from '@glideapps/glide-data-grid'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  DollarSign,
  Eraser,
  Hash,
  Italic,
  PaintBucket,
  Percent,
  Plus,
  Trash2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { formattingApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { getSelectedCellRefs, getSelectedColumnKeys } from '@/lib/cellFormat'
import { toast } from '@/hooks/useToast'
import type { ApiError, CellAlign, CellStylePatch, NumberFormat, SheetColumn } from '@/types'

interface HomeRibbonProps {
  fileId: string
  sheetId: string
  columns: SheetColumn[]
  rowCount: number
  selection: GridSelection
  onCellStyleApplied: (cells: { row_index: number; col_key: string }[], patch: CellStylePatch) => void
  onColumnFormatApplied: (colKey: string, patch: { format?: NumberFormat; align?: CellAlign }) => void
  onColumnsMutated: () => void
  // A column filter can make the grid's display non-contiguous in real row
  // indices, which breaks range-based per-cell actions (they'd assume
  // display position === row index) — disable just those while filtered.
  disableCellActions?: boolean
}

const btnClass = 'flex h-7 w-7 shrink-0 items-center justify-center rounded hover:bg-accent cursor-pointer'

function apiErrorMessage(err: unknown, fallback: string): string {
  const axiosErr = err as AxiosError<ApiError>
  return axiosErr.response?.data?.error?.message ?? fallback
}

export function HomeRibbon({
  fileId,
  sheetId,
  columns,
  rowCount,
  selection,
  onCellStyleApplied,
  onColumnFormatApplied,
  onColumnsMutated,
  disableCellActions = false,
}: HomeRibbonProps) {
  const [showInsertInput, setShowInsertInput] = useState(false)
  const [newColName, setNewColName] = useState('')

  const applyCellStyle = async (patch: CellStylePatch) => {
    if (disableCellActions) {
      toast({ title: 'Clear the column filter first', description: 'Per-cell formatting is disabled while a filter is active.' })
      return
    }
    const refs = getSelectedCellRefs(selection, columns, rowCount)
    if (refs.length === 0) {
      toast({ title: 'Select a cell or range first' })
      return
    }
    onCellStyleApplied(refs, patch)
    try {
      await formattingApi.updateCellStyle(fileId, sheetId, refs, patch)
    } catch {
      toast({ variant: 'destructive', title: 'Failed to apply formatting' })
    }
  }

  const applyAlign = (align: CellAlign) => applyCellStyle({ align })

  const applyNumberFormat = async (format: NumberFormat) => {
    const colKeys = getSelectedColumnKeys(selection, columns)
    if (colKeys.length === 0) {
      toast({ title: 'Select a column first' })
      return
    }
    for (const colKey of colKeys) {
      onColumnFormatApplied(colKey, { format })
      try {
        await formattingApi.updateColumnFormat(fileId, sheetId, colKey, { number_format: format })
      } catch {
        toast({ variant: 'destructive', title: `Failed to format "${colKey}"` })
      }
    }
  }

  const handleInsertColumn = async () => {
    const name = newColName.trim()
    if (!name) return
    try {
      await formattingApi.addColumn(fileId, sheetId, name)
      setNewColName('')
      setShowInsertInput(false)
      onColumnsMutated()
    } catch (err) {
      toast({ variant: 'destructive', title: apiErrorMessage(err, 'Failed to add column') })
    }
  }

  const handleDeleteColumn = async () => {
    const colKeys = getSelectedColumnKeys(selection, columns)
    if (colKeys.length !== 1) {
      toast({ title: 'Select exactly one column to delete' })
      return
    }
    const colKey = colKeys[0]
    if (!window.confirm(`Delete column "${colKey}"? This removes it from every row.`)) return
    try {
      await formattingApi.deleteColumn(fileId, sheetId, colKey)
      onColumnsMutated()
    } catch (err) {
      toast({ variant: 'destructive', title: apiErrorMessage(err, `Failed to delete "${colKey}"`) })
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-border bg-muted/30 px-3 py-1.5">
      {/* Font */}
      <div className={cn('flex items-center gap-0.5', disableCellActions && 'pointer-events-none opacity-40')}>
        <button className={btnClass} title="Bold" onClick={() => applyCellStyle({ bold: true })}>
          <Bold className="h-3.5 w-3.5" />
        </button>
        <button className={btnClass} title="Italic" onClick={() => applyCellStyle({ italic: true })}>
          <Italic className="h-3.5 w-3.5" />
        </button>
        <label className={btnClass} title="Font color">
          <Baseline className="h-3.5 w-3.5" />
          <input
            type="color"
            className="sr-only"
            onChange={(e) => applyCellStyle({ font_color: e.target.value })}
          />
        </label>
        <label className={btnClass} title="Fill color">
          <PaintBucket className="h-3.5 w-3.5" />
          <input
            type="color"
            className="sr-only"
            onChange={(e) => applyCellStyle({ bg_color: e.target.value })}
          />
        </label>
        <button
          className={btnClass}
          title="Clear formatting"
          onClick={() => applyCellStyle({ bold: null, italic: null, font_color: null, bg_color: null })}
        >
          <Eraser className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="h-4 w-px bg-border" />

      {/* Alignment */}
      <div
        className={cn('flex items-center gap-0.5', disableCellActions && 'pointer-events-none opacity-40')}
        title={disableCellActions ? 'Clear the column filter to use alignment' : undefined}
      >
        <button className={btnClass} title="Align left" onClick={() => applyAlign('left')}>
          <AlignLeft className="h-3.5 w-3.5" />
        </button>
        <button className={btnClass} title="Align center" onClick={() => applyAlign('center')}>
          <AlignCenter className="h-3.5 w-3.5" />
        </button>
        <button className={btnClass} title="Align right" onClick={() => applyAlign('right')}>
          <AlignRight className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="h-4 w-px bg-border" />

      {/* Number format — applies to the whole column(s) touched by the selection */}
      <div className="flex items-center gap-0.5">
        <button className={btnClass} title="Currency" onClick={() => applyNumberFormat('currency')}>
          <DollarSign className="h-3.5 w-3.5" />
        </button>
        <button className={btnClass} title="Percent" onClick={() => applyNumberFormat('percent')}>
          <Percent className="h-3.5 w-3.5" />
        </button>
        <button className={btnClass} title="Number" onClick={() => applyNumberFormat('number')}>
          <Hash className="h-3.5 w-3.5" />
        </button>
        <button
          className="rounded px-1.5 py-1 text-[11px] hover:bg-accent"
          title="General"
          onClick={() => applyNumberFormat('general')}
        >
          General
        </button>
      </div>

      <div className="h-4 w-px bg-border" />

      {/* Cells */}
      <div className="relative flex items-center gap-0.5">
        <button
          className="flex h-7 items-center gap-1 rounded px-1.5 text-[11px] hover:bg-accent"
          onClick={() => setShowInsertInput((v) => !v)}
        >
          <Plus className="h-3.5 w-3.5" /> Column
        </button>
        <button
          className="flex h-7 items-center gap-1 rounded px-1.5 text-[11px] text-destructive hover:bg-accent"
          onClick={handleDeleteColumn}
        >
          <Trash2 className="h-3.5 w-3.5" /> Column
        </button>

        {showInsertInput && (
          <div className="absolute left-0 top-8 z-10 flex items-center gap-1 rounded-md border border-border bg-background p-1.5 shadow-md">
            <input
              autoFocus
              value={newColName}
              onChange={(e) => setNewColName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleInsertColumn()
                if (e.key === 'Escape') setShowInsertInput(false)
              }}
              placeholder="Column name"
              className="h-7 w-32 rounded border border-border bg-background px-2 text-xs outline-none"
            />
            <Button size="sm" className="h-7 px-2 text-xs" onClick={handleInsertColumn}>
              Add
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}
