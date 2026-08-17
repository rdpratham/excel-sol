import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DataEditor, {
  type CellClickedEventArgs,
  type EditableGridCell,
  type GridCell,
  type GridColumn,
  type Rectangle,
  type Theme,
  GridCellKind,
  type Item,
  CompactSelection,
  type GridSelection,
} from '@glideapps/glide-data-grid'
import '@glideapps/glide-data-grid/dist/index.css'
import { cellStyleKey, colIndexToLetters, effectiveAlign, formatDisplayValue } from '@/lib/cellFormat'
import { ColumnFilterPopover } from './ColumnFilterPopover'
import type { CellStyle, SheetColumn } from '@/types'

export interface GridRow {
  [key: string]: unknown
}

interface SpreadsheetGridProps {
  columns: SheetColumn[]
  rows: GridRow[]
  totalRows: number
  cellStyles?: Record<string, CellStyle>
  // isNewColumn=true means colKey is a generated letter name (e.g. "C") for
  // a column that doesn't exist yet — the caller must create it first.
  onCellEdited: (rowIndex: number, colKey: string, value: unknown, isNewColumn?: boolean) => void
  onSelectionChange?: (selectedRows: number[]) => void
  onFullSelectionChange?: (selection: GridSelection) => void
  // Fires whenever a column filter is applied/cleared, so the parent can
  // disable per-cell formatting actions — a filtered display can be
  // non-contiguous in real row indices, and range-based cell styling
  // assumes display position === row index.
  onFilterActiveChange?: (active: boolean) => void
  isLoading?: boolean
}

// Blank trailing rows/columns rendered beyond the real data, Excel-style —
// grown further as the user scrolls near the edge (see onVisibleRegionChanged).
const INITIAL_ROW_BUFFER = 60
const INITIAL_COL_BUFFER = 10
const BUFFER_GROWTH = 60
const GROWTH_THRESHOLD = 15

const DARK_THEME = {
  accentColor: '#3b82f6',
  accentFg: '#ffffff',
  accentLight: 'rgba(59,130,246,0.12)',
  textDark: '#f1f5f9',
  textMedium: '#94a3b8',
  textLight: '#64748b',
  textBubble: '#f1f5f9',
  bgIconHeader: '#1e293b',
  fgIconHeader: '#94a3b8',
  textHeader: '#cbd5e1',
  textGroupHeader: '#94a3b8',
  bgCell: '#0f172a',
  bgCellMedium: '#1e293b',
  bgHeader: '#1e293b',
  bgHeaderHasFocus: '#334155',
  bgHeaderHovered: '#334155',
  bgBubble: '#334155',
  bgBubbleSelected: '#3b82f6',
  bgSearchResult: 'rgba(59,130,246,0.25)',
  borderColor: 'rgba(148,163,184,0.15)',
  drilldownBorder: 'rgba(148,163,184,0.4)',
  linkColor: '#60a5fa',
  headerFontStyle: '500 12px',
  baseFontStyle: '13px',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  editorFontSize: '13px',
  lineHeight: 1.5,
  cellHorizontalPadding: 8,
  cellVerticalPadding: 3,
  headerIconSize: 16,
  markerFontStyle: '10px',
}

const LIGHT_THEME = {
  accentColor: '#3b82f6',
  accentFg: '#ffffff',
  accentLight: 'rgba(59,130,246,0.1)',
  textDark: '#0f172a',
  textMedium: '#475569',
  textLight: '#94a3b8',
  bgCell: '#ffffff',
  bgCellMedium: '#f8fafc',
  bgHeader: '#f1f5f9',
  bgHeaderHasFocus: '#e2e8f0',
  bgHeaderHovered: '#e2e8f0',
  borderColor: 'rgba(226,232,240,1)',
  textHeader: '#334155',
  headerFontStyle: '500 12px',
  baseFontStyle: '13px',
  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  editorFontSize: '13px',
  lineHeight: 1.5,
  cellHorizontalPadding: 8,
  cellVerticalPadding: 3,
  headerIconSize: 16,
  markerFontStyle: '10px',
}

export function SpreadsheetGrid({
  columns,
  rows,
  cellStyles = {},
  onCellEdited,
  onSelectionChange,
  onFullSelectionChange,
  onFilterActiveChange,
}: SpreadsheetGridProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const [selection, setSelection] = useState<GridSelection>({
    columns: CompactSelection.empty(),
    rows: CompactSelection.empty(),
    current: undefined,
  })
  const [rowBuffer, setRowBuffer] = useState(INITIAL_ROW_BUFFER)
  const [colBuffer, setColBuffer] = useState(INITIAL_COL_BUFFER)
  const [columnWidths, setColumnWidths] = useState<Record<string, number>>({})

  // Column filter (Autofilter) — colKey -> allowed values. Absent entry, or
  // an entry covering every value, means "no filter" for that column.
  const [columnFilters, setColumnFilters] = useState<Record<string, Set<string>>>({})
  const [filterPopover, setFilterPopover] = useState<{ colKey: string; x: number; y: number } | null>(null)

  const hasActiveFilter = Object.keys(columnFilters).length > 0
  useEffect(() => { onFilterActiveChange?.(hasActiveFilter) }, [hasActiveFilter, onFilterActiveChange])

  // Real row indices that pass every active filter, in order — the display
  // list is this array's positions; toRealRow() below maps back.
  const visibleRowIndices = useMemo(() => {
    if (!hasActiveFilter) return null
    const active = Object.entries(columnFilters)
    const indices: number[] = []
    rows.forEach((r, i) => {
      const passes = active.every(([colKey, allowed]) => {
        const v = r?.[colKey]
        return allowed.has(v == null ? '' : String(v))
      })
      if (passes) indices.push(i)
    })
    return indices
  }, [rows, columnFilters, hasActiveFilter])

  // Translate a display-row position (what glide-data-grid gives every
  // callback) to the real row index (what onCellEdited/selection callbacks
  // must report). Phantom rows beyond the filtered set still map to real
  // trailing indices past the sheet's true row count.
  const toRealRow = useCallback(
    (displayRow: number): number => {
      if (!visibleRowIndices) return displayRow
      if (displayRow < visibleRowIndices.length) return visibleRowIndices[displayRow]
      return rows.length + (displayRow - visibleRowIndices.length)
    },
    [visibleRowIndices, rows.length],
  )

  const displayRowCount = visibleRowIndices ? visibleRowIndices.length : rows.length

  const uniqueValuesFor = useCallback(
    (colKey: string) => {
      const set = new Set<string>()
      rows.forEach((r) => { const v = r?.[colKey]; set.add(v == null ? '' : String(v)) })
      return Array.from(set).sort()
    },
    [rows],
  )

  const onHeaderMenuClick = useCallback(
    (col: number, bounds: Rectangle) => {
      const column = columns[col]
      if (!column) return
      setFilterPopover({ colKey: column.name, x: bounds.x, y: bounds.y + bounds.height })
    },
    [columns],
  )

  // Column resize (drag the header border, Excel-style) — glide-data-grid
  // supports the drag itself out of the box, but won't persist the new
  // width anywhere unless the caller stores it and feeds it back in.
  const onColumnResize = useCallback((column: GridColumn, newSize: number) => {
    if (!column.id) return
    setColumnWidths((prev) => ({ ...prev, [column.id as string]: newSize }))
  }, [])

  // Grow the blank buffer as the user scrolls toward its edge, so it feels
  // like an unbounded canvas rather than a fixed-size padded table.
  const onVisibleRegionChanged = useCallback(
    (range: Rectangle) => {
      if (range.y + range.height >= displayRowCount + rowBuffer - GROWTH_THRESHOLD) {
        setRowBuffer((n) => n + BUFFER_GROWTH)
      }
      if (range.x + range.width >= columns.length + colBuffer - GROWTH_THRESHOLD) {
        setColBuffer((n) => n + BUFFER_GROWTH)
      }
    },
    [displayRowCount, columns.length, rowBuffer, colBuffer],
  )

  // Detect dark mode
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark' ||
    (!document.documentElement.getAttribute('data-theme') &&
      window.matchMedia('(prefers-color-scheme: dark)').matches)

  // Measure container
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setDimensions({ width: Math.max(width, 200), height: Math.max(height, 200) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Notify parent of row selection (translated to real row indices)
  useEffect(() => {
    if (!onSelectionChange) return
    const selected: number[] = []
    selection.rows.toArray().forEach((i) => selected.push(toRealRow(i)))
    onSelectionChange(selected)
  }, [selection, onSelectionChange, toRealRow])

  // Notify parent of the full selection (used by the formatting ribbon)
  useEffect(() => {
    onFullSelectionChange?.(selection)
  }, [selection, onFullSelectionChange])

  const gridColumns: GridColumn[] = useMemo(() => {
    const real = columns.map((col) => ({
      title: columnFilters[col.name] ? `${col.name} ▾` : col.name,
      id: col.name,
      width: columnWidths[col.name] ?? col.width ?? 150,
      hasMenu: true,
    }))
    const phantomCount = Math.max(colBuffer, 1)
    const phantom = Array.from({ length: phantomCount }, (_, i) => {
      const absoluteIndex = columns.length + i
      const id = `__phantom_col_${absoluteIndex}`
      return {
        title: colIndexToLetters(absoluteIndex),
        id,
        width: columnWidths[id] ?? 120,
        grow: i === phantomCount - 1 ? 1 : undefined,
      }
    })
    return [...real, ...phantom]
  }, [columns, colBuffer, columnWidths])

  const getCellContent = useCallback(
    ([col, displayRow]: Item): GridCell => {
      const column = columns[col]

      if (!column) {
        // Blank trailing column beyond the real data
        return {
          kind: GridCellKind.Text,
          data: '',
          displayData: '',
          allowOverlay: true,
          readonly: false,
        }
      }

      const row = toRealRow(displayRow)
      const colName = column.name
      const rowData = rows[row]
      const val = rowData?.[colName] ?? ''
      const strVal = val == null ? '' : String(val)

      const style = cellStyles[cellStyleKey(row, colName)]
      const displayData = formatDisplayValue(val, column.format)
      const align = effectiveAlign(style, column)

      const themeOverride: Partial<Theme> | undefined =
        style?.bold || style?.italic || style?.font_color || style?.bg_color
          ? {
              ...(style.font_color ? { textDark: style.font_color } : {}),
              ...(style.bg_color ? { bgCell: style.bg_color } : {}),
              ...(style.bold || style.italic
                ? { baseFontStyle: `${style.italic ? 'italic ' : ''}${style.bold ? 'bold ' : ''}13px`.trim() }
                : {}),
            }
          : undefined

      return {
        kind: GridCellKind.Text,
        data: strVal,
        displayData,
        allowOverlay: true,
        readonly: false,
        contentAlign: align,
        themeOverride,
      }
    },
    [columns, rows, cellStyles, toRealRow],
  )

  const onCellEditedHandler = useCallback(
    ([col, displayRow]: Item, newVal: EditableGridCell) => {
      const row = toRealRow(displayRow)
      const value = newVal.kind === GridCellKind.Text ? newVal.data : String((newVal as { data: unknown }).data)
      const column = columns[col]
      if (column) {
        onCellEdited(row, column.name, value)
      } else {
        // Blank column beyond the real data — materialize it with its
        // spreadsheet-letter name, matching what the header already shows.
        onCellEdited(row, colIndexToLetters(col), value, true)
      }
    },
    [columns, onCellEdited, toRealRow],
  )

  // Ctrl/Cmd+click a cell containing a URL to open it in a new tab, Excel-hyperlink-style
  const onCellClicked = useCallback(
    ([col, displayRow]: Item, event: CellClickedEventArgs) => {
      if (!event.ctrlKey && !event.metaKey) return
      const row = toRealRow(displayRow)
      const colName = columns[col]?.name
      const val = rows[row]?.[colName]
      const str = val == null ? '' : String(val).trim()
      if (/^https?:\/\/\S+$/i.test(str)) {
        event.preventDefault()
        window.open(str, '_blank', 'noopener,noreferrer')
      }
    },
    [columns, rows, toRealRow],
  )

  const applyColumnFilter = useCallback((colKey: string, allowed: Set<string> | null) => {
    setColumnFilters((prev) => {
      const next = { ...prev }
      if (allowed === null) delete next[colKey]
      else next[colKey] = allowed
      return next
    })
  }, [])

  return (
    <div ref={containerRef} className="h-full w-full overflow-hidden">
      <DataEditor
        width={dimensions.width}
        height={dimensions.height}
        columns={gridColumns}
        rows={displayRowCount + rowBuffer}
        getCellContent={getCellContent}
        onCellEdited={onCellEditedHandler}
        onCellClicked={onCellClicked}
        onVisibleRegionChanged={onVisibleRegionChanged}
        onColumnResize={onColumnResize}
        onHeaderMenuClick={onHeaderMenuClick}
        rowMarkers="number"
        smoothScrollX
        smoothScrollY
        keybindings={{ search: true }}
        editOnType
        cellActivationBehavior="double-click"
        gridSelection={selection}
        onGridSelectionChange={setSelection}
        theme={isDark ? DARK_THEME : LIGHT_THEME}
        rowHeight={32}
        headerHeight={36}
        getCellsForSelection
        copyHeaders
      />

      {filterPopover && (
        <ColumnFilterPopover
          colKey={filterPopover.colKey}
          values={uniqueValuesFor(filterPopover.colKey)}
          selected={columnFilters[filterPopover.colKey] ?? null}
          x={filterPopover.x}
          y={filterPopover.y}
          onApply={(allowed) => applyColumnFilter(filterPopover.colKey, allowed)}
          onClose={() => setFilterPopover(null)}
        />
      )}
    </div>
  )
}
