import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DataEditor, {
  type CellClickedEventArgs,
  type EditableGridCell,
  type GridCell,
  type GridColumn,
  type Theme,
  GridCellKind,
  type Item,
  CompactSelection,
  type GridSelection,
} from '@glideapps/glide-data-grid'
import '@glideapps/glide-data-grid/dist/index.css'
import { cellStyleKey, effectiveAlign, formatDisplayValue } from '@/lib/cellFormat'
import type { CellStyle, SheetColumn } from '@/types'

export interface GridRow {
  [key: string]: unknown
}

interface SpreadsheetGridProps {
  columns: SheetColumn[]
  rows: GridRow[]
  totalRows: number
  cellStyles?: Record<string, CellStyle>
  onCellEdited: (rowIndex: number, colKey: string, value: unknown) => void
  onSelectionChange?: (selectedRows: number[]) => void
  onFullSelectionChange?: (selection: GridSelection) => void
  isLoading?: boolean
}

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
}: SpreadsheetGridProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const [selection, setSelection] = useState<GridSelection>({
    columns: CompactSelection.empty(),
    rows: CompactSelection.empty(),
    current: undefined,
  })

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

  // Notify parent of row selection
  useEffect(() => {
    if (!onSelectionChange) return
    const selected: number[] = []
    selection.rows.toArray().forEach((i) => selected.push(i))
    onSelectionChange(selected)
  }, [selection, onSelectionChange])

  // Notify parent of the full selection (used by the formatting ribbon)
  useEffect(() => {
    onFullSelectionChange?.(selection)
  }, [selection, onFullSelectionChange])

  const gridColumns: GridColumn[] = useMemo(
    () =>
      columns.map((col) => ({
        title: col.name,
        id: col.name,
        width: col.width ?? 150,
        grow: col.index === columns.length - 1 ? 1 : undefined,
      })),
    [columns],
  )

  const getCellContent = useCallback(
    ([col, row]: Item): GridCell => {
      const column = columns[col]
      const colName = column?.name
      const rowData = rows[row]
      const val = rowData?.[colName] ?? ''
      const strVal = val == null ? '' : String(val)

      const style = cellStyles[cellStyleKey(row, colName)]
      const displayData = formatDisplayValue(val, column?.format)
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
    [columns, rows, cellStyles],
  )

  const onCellEditedHandler = useCallback(
    ([col, row]: Item, newVal: EditableGridCell) => {
      const colName = columns[col]?.name
      if (!colName) return
      const value = newVal.kind === GridCellKind.Text ? newVal.data : String((newVal as { data: unknown }).data)
      onCellEdited(row, colName, value)
    },
    [columns, onCellEdited],
  )

  // Ctrl/Cmd+click a cell containing a URL to open it in a new tab, Excel-hyperlink-style
  const onCellClicked = useCallback(
    ([col, row]: Item, event: CellClickedEventArgs) => {
      if (!event.ctrlKey && !event.metaKey) return
      const colName = columns[col]?.name
      const val = rows[row]?.[colName]
      const str = val == null ? '' : String(val).trim()
      if (/^https?:\/\/\S+$/i.test(str)) {
        event.preventDefault()
        window.open(str, '_blank', 'noopener,noreferrer')
      }
    },
    [columns, rows],
  )

  if (columns.length === 0) return null

  return (
    <div ref={containerRef} className="h-full w-full overflow-hidden">
      <DataEditor
        width={dimensions.width}
        height={dimensions.height}
        columns={gridColumns}
        rows={rows.length}
        getCellContent={getCellContent}
        onCellEdited={onCellEditedHandler}
        onCellClicked={onCellClicked}
        rowMarkers="number"
        smoothScrollX
        smoothScrollY
        keybindings={{ search: true }}
        gridSelection={selection}
        onGridSelectionChange={setSelection}
        theme={isDark ? DARK_THEME : LIGHT_THEME}
        rowHeight={32}
        headerHeight={36}
        getCellsForSelection
        copyHeaders
      />
    </div>
  )
}
