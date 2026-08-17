import { useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  Loader2,
  Trash2,
  Upload,
} from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { filesApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { toast } from '@/hooks/useToast'
import type { SpreadsheetFile, Sheet } from '@/types'

interface SidebarProps {
  activeSheetId?: string
  onSheetSelect: (file: SpreadsheetFile, sheet: Sheet) => void
}

interface FileNodeProps {
  file: SpreadsheetFile
  activeSheetId?: string
  onSheetSelect: (file: SpreadsheetFile, sheet: Sheet) => void
  onDelete: (fileId: string) => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function FileNode({ file, activeSheetId, onSheetSelect, onDelete }: FileNodeProps) {
  const [expanded, setExpanded] = useState(false)
  const [hovering, setHovering] = useState(false)
  const isReady = file.status === 'ready'

  return (
    <div>
      <div
        className="group relative flex items-center"
        onMouseEnter={() => setHovering(true)}
        onMouseLeave={() => setHovering(false)}
      >
        <button
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded px-2 py-1.5 text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
          onClick={() => isReady && setExpanded((v) => !v)}
          disabled={!isReady}
          aria-expanded={expanded}
        >
          {!isReady ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-foreground" />
          ) : expanded ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          )}
          <FileSpreadsheet className="h-3.5 w-3.5 shrink-0 text-emerald-500" />
          <span className="min-w-0 flex-1 truncate text-left">{file.display_name}</span>
          {isReady && (
            <span className="ml-1 shrink-0 text-xs text-muted-foreground">
              {formatBytes(file.size_bytes)}
            </span>
          )}
        </button>

        {hovering && (
          <button
            className="absolute right-1 flex h-5 w-5 items-center justify-center rounded hover:bg-destructive/10 hover:text-destructive"
            onClick={(e) => { e.stopPropagation(); onDelete(file.id) }}
            title="Delete file"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>

      {expanded && isReady && (
        <div className="ml-5 border-l border-border pl-2">
          {file.sheets.length === 0 ? (
            <p className="py-1 text-xs text-muted-foreground">No sheets</p>
          ) : (
            file.sheets.map((sheet) => (
              <button
                key={sheet.id}
                className={cn(
                  'flex w-full items-center justify-between rounded px-2 py-1 text-xs hover:bg-accent',
                  activeSheetId === sheet.id && 'bg-accent font-medium text-accent-foreground',
                )}
                onClick={() => onSheetSelect(file, sheet)}
              >
                <span className="truncate">{sheet.name}</span>
                <span className="ml-2 shrink-0 tabular-nums text-muted-foreground">
                  {sheet.row_count.toLocaleString()}
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}

export function Sidebar({ activeSheetId, onSheetSelect }: SidebarProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const queryClient = useQueryClient()

  const { data: files = [], isLoading } = useQuery({
    queryKey: ['files'],
    queryFn: () => filesApi.list().then((r) => r.data),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => filesApi.upload(file).then((r) => r.data),
    onSuccess: (uploaded) => {
      queryClient.invalidateQueries({ queryKey: ['files'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      toast({ title: `"${uploaded.display_name}" uploaded`, description: `${uploaded.total_rows.toLocaleString()} rows` })
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: { message?: string } } } })
        ?.response?.data?.detail?.message ?? 'Upload failed'
      toast({ variant: 'destructive', title: 'Upload failed', description: msg })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (fileId: string) => filesApi.delete(fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: () => toast({ variant: 'destructive', title: 'Delete failed' }),
  })

  const handleFiles = (fileList: FileList | null) => {
    if (!fileList) return
    Array.from(fileList).forEach((f) => uploadMutation.mutate(f))
  }

  return (
    <aside className="flex h-full w-full flex-col border-r border-border bg-background">
      {/* Upload zone */}
      <div className="border-b border-border p-3">
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx,.xlsm,.csv"
          multiple
          className="sr-only"
          onChange={(e) => handleFiles(e.target.files)}
        />
        <div
          className={cn(
            'flex cursor-pointer flex-col items-center gap-1.5 rounded-md border-2 border-dashed p-4 text-center transition-colors',
            dragging
              ? 'border-primary bg-primary/5'
              : 'border-border hover:border-primary/50 hover:bg-accent/50',
            uploadMutation.isPending && 'pointer-events-none opacity-60',
          )}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragging(false)
            handleFiles(e.dataTransfer.files)
          }}
        >
          {uploadMutation.isPending ? (
            <>
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              <p className="text-xs font-medium">Processing…</p>
            </>
          ) : (
            <>
              <Upload className="h-5 w-5 text-muted-foreground" />
              <p className="text-xs font-medium">Upload file</p>
              <p className="text-xs text-muted-foreground">.xlsx, .xlsm, .csv</p>
            </>
          )}
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
              onDelete={(id) => deleteMutation.mutate(id)}
            />
          ))
        )}
      </div>
    </aside>
  )
}
