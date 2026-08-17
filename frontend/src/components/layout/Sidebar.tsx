import { useState } from 'react'
import { Upload, FileSpreadsheet, ChevronRight, ChevronDown, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SpreadsheetFile, Sheet } from '@/types'

interface SidebarProps {
  files: SpreadsheetFile[]
  isLoading: boolean
  activeSheetId?: string
  onSheetSelect: (file: SpreadsheetFile, sheet: Sheet) => void
}

interface FileNodeProps {
  file: SpreadsheetFile
  activeSheetId?: string
  onSheetSelect: (file: SpreadsheetFile, sheet: Sheet) => void
}

function FileNode({ file, activeSheetId, onSheetSelect }: FileNodeProps) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div>
      <button
        className="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-sm hover:bg-accent"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        )}
        <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate text-left">{file.display_name}</span>
      </button>

      {expanded && (
        <div className="ml-5 border-l border-border pl-2">
          {file.sheets.length === 0 && (
            <p className="py-1 text-xs text-muted-foreground">No sheets</p>
          )}
          {file.sheets.map((sheet) => (
            <button
              key={sheet.id}
              className={cn(
                'flex w-full items-center justify-between rounded px-2 py-1 text-xs hover:bg-accent',
                activeSheetId === sheet.id && 'bg-accent font-medium text-accent-foreground',
              )}
              onClick={() => onSheetSelect(file, sheet)}
            >
              <span className="truncate">{sheet.name}</span>
              <span className="ml-2 shrink-0 text-muted-foreground">
                {sheet.row_count.toLocaleString()}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function Sidebar({ files, isLoading, activeSheetId, onSheetSelect }: SidebarProps) {
  return (
    <aside className="flex h-full w-full flex-col border-r border-border bg-background">
      {/* Upload zone — Phase 2 will make this functional */}
      <div className="border-b border-border p-3">
        <div className="flex cursor-pointer flex-col items-center gap-1.5 rounded-md border-2 border-dashed border-border p-4 text-center transition-colors hover:border-primary/50 hover:bg-accent/50">
          <Upload className="h-5 w-5 text-muted-foreground" />
          <p className="text-xs font-medium">Upload file</p>
          <p className="text-xs text-muted-foreground">.xlsx, .xlsm, .csv</p>
        </div>
      </div>

      {/* File tree */}
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        ) : files.length === 0 ? (
          <p className="py-6 text-center text-xs text-muted-foreground">No files yet</p>
        ) : (
          files.map((file) => (
            <FileNode
              key={file.id}
              file={file}
              activeSheetId={activeSheetId}
              onSheetSelect={onSheetSelect}
            />
          ))
        )}
      </div>
    </aside>
  )
}
