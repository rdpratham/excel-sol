import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  FileSpreadsheet,
  LayoutDashboard,
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

interface SheetCardProps {
  file: SpreadsheetFile
  sheet: Sheet
  isActive: boolean
  onOpen: () => void
  onDelete: () => void
}

// One icon per sheet — clicking opens that exact sheet. The subtitle shows
// the parent file name for context since multiple sheets can share one file.
function SheetCard({ file, sheet, isActive, onOpen, onDelete }: SheetCardProps) {
  const [hovering, setHovering] = useState(false)

  return (
    <div
      className={cn(
        'group relative flex flex-col items-center gap-1 rounded-lg border border-transparent p-2 text-center hover:border-border hover:bg-accent',
        isActive && 'border-border bg-accent',
      )}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <button
        className="flex w-full flex-col items-center gap-1"
        onClick={onOpen}
        title={`${file.display_name} — ${sheet.name}`}
      >
        <FileSpreadsheet className="h-11 w-11 text-emerald-500" strokeWidth={1.25} />
        <span className="line-clamp-2 w-full break-words text-xs font-medium leading-tight">
          {sheet.name}
        </span>
        <span className="line-clamp-1 w-full break-words text-[10px] text-muted-foreground">
          {file.display_name}
        </span>
      </button>

      {hovering && (
        <button
          className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded hover:bg-destructive/10 hover:text-destructive"
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          title="Delete file"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      )}
    </div>
  )
}

interface ProcessingCardProps {
  file: SpreadsheetFile
}

function ProcessingCard({ file }: ProcessingCardProps) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-lg p-2 text-center opacity-60">
      <Loader2 className="h-9 w-9 animate-spin text-muted-foreground" />
      <span className="line-clamp-2 w-full break-words text-xs font-medium leading-tight">
        {file.display_name}
      </span>
      <span className="text-[10px] text-muted-foreground">Processing…</span>
    </div>
  )
}

export function Sidebar({ activeSheetId, onSheetSelect }: SidebarProps) {
  const navigate = useNavigate()
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

  // Flatten to one entry per sheet — a file with 3 sheets gets 3 icons
  const sheetEntries = files.flatMap((file) =>
    file.sheets.map((sheet) => ({ file, sheet })),
  )
  const processingFiles = files.filter((f) => f.status !== 'ready' && f.sheets.length === 0)

  return (
    <aside className="flex h-full w-full flex-col border-r border-border bg-background">
      {/* Dashboard */}
      <div className="border-b border-border p-2">
        <button
          className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm font-medium hover:bg-accent"
          onClick={() => navigate('/')}
        >
          <LayoutDashboard className="h-4 w-4 text-muted-foreground" />
          Dashboard
        </button>
      </div>

      {/* Upload */}
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

      {/* Files — large icon grid, one icon per sheet; click opens that sheet */}
      <div className="flex min-h-0 flex-1 flex-col">
        <p className="px-3 pb-1 pt-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Files
        </p>
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : sheetEntries.length === 0 && processingFiles.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">No files yet</p>
          ) : (
            <div className="grid grid-cols-2 gap-1.5">
              {sheetEntries.map(({ file, sheet }) => (
                <SheetCard
                  key={sheet.id}
                  file={file}
                  sheet={sheet}
                  isActive={sheet.id === activeSheetId}
                  onOpen={() => onSheetSelect(file, sheet)}
                  onDelete={() => deleteMutation.mutate(file.id)}
                />
              ))}
              {processingFiles.map((file) => (
                <ProcessingCard key={file.id} file={file} />
              ))}
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}
