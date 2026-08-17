import type { GridSelection } from '@glideapps/glide-data-grid'
import type { CellAlign, CellStyle, CellStylePatch, NumberFormat, SheetColumn } from '@/types'

export function formatDisplayValue(raw: unknown, format: NumberFormat | undefined): string {
  if (raw == null || raw === '') return ''
  if (!format || format === 'general') return String(raw)

  const num = typeof raw === 'number' ? raw : Number(raw)
  if (Number.isNaN(num)) return String(raw)

  switch (format) {
    case 'currency':
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(num)
    case 'percent':
      return `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(num)}%`
    case 'number':
      return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(num)
    default:
      return String(raw)
  }
}

export function effectiveAlign(cellStyle: CellStyle | undefined, column: SheetColumn | undefined): CellAlign | undefined {
  return cellStyle?.align ?? column?.align
}

export function cellStyleKey(rowIndex: number, colKey: string): string {
  return `${rowIndex}:${colKey}`
}

/** Columns touched by the current selection — whole-column selection or a range spanning columns. */
export function getSelectedColumnKeys(selection: GridSelection, columns: SheetColumn[]): string[] {
  const keys = new Set<string>()
  selection.columns.toArray().forEach((ci) => {
    const name = columns[ci]?.name
    if (name) keys.add(name)
  })
  if (keys.size === 0 && selection.current) {
    const { x, width } = selection.current.range
    for (let ci = x; ci < x + width; ci++) {
      const name = columns[ci]?.name
      if (name) keys.add(name)
    }
  }
  return Array.from(keys)
}

/** (row, col) pairs touched by the current selection, for per-cell style updates. */
export function getSelectedCellRefs(
  selection: GridSelection,
  columns: SheetColumn[],
  rowCount: number,
): { row_index: number; col_key: string }[] {
  const refs: { row_index: number; col_key: string }[] = []
  const selectedColumns = selection.columns.toArray()

  if (selectedColumns.length > 0) {
    selectedColumns.forEach((ci) => {
      const name = columns[ci]?.name
      if (!name) return
      for (let r = 0; r < rowCount; r++) refs.push({ row_index: r, col_key: name })
    })
    return refs
  }

  if (selection.current) {
    const { x, y, width, height } = selection.current.range
    for (let r = y; r < y + height; r++) {
      for (let ci = x; ci < x + width; ci++) {
        const name = columns[ci]?.name
        if (name) refs.push({ row_index: r, col_key: name })
      }
    }
  }
  return refs
}

/**
 * Merges a style patch into the sparse cell_styles map — `null`/`undefined`
 * on a field clears that override, any other value sets it. Mirrors the
 * backend's merge in formatting.py so local optimistic updates and incoming
 * WebSocket broadcasts (which carry the same patch shape) land identically.
 */
export function mergeCellStylePatch(
  styles: Record<string, CellStyle>,
  cells: { row_index: number; col_key: string }[],
  patch: CellStylePatch | Record<string, unknown>,
): Record<string, CellStyle> {
  const next = { ...styles }
  for (const { row_index, col_key } of cells) {
    const key = cellStyleKey(row_index, col_key)
    const merged: Record<string, unknown> = { ...next[key] }
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === undefined) {
        delete merged[k]
      } else {
        merged[k] = v
      }
    }
    if (Object.keys(merged).length > 0) {
      next[key] = merged as CellStyle
    } else {
      delete next[key]
    }
  }
  return next
}
