import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Loader2, Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { filesApi } from '@/lib/api'
import { prefetchSheetPage } from '@/lib/prefetch'
import { toast } from '@/hooks/useToast'
import type { SpreadsheetFile } from '@/types'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface SheetTileProps {
  sheet: SpreadsheetFile['sheets'][number]
  onOpen: () => void
}

function SheetTile({ sheet, onOpen }: SheetTileProps) {
  return (
    <button
      className="hover-lift flex flex-col items-center gap-1.5 rounded-xl border border-transparent p-3 text-center hover:border-border hover:bg-accent"
      onClick={onOpen}
      onMouseEnter={prefetchSheetPage}
      title={sheet.name}
    >
      <FileSpreadsheet className="h-14 w-14 text-emerald-500" strokeWidth={1.1} />
      <span className="line-clamp-2 w-full break-words text-sm font-medium leading-tight">
        {sheet.name}
      </span>
      <span className="text-[11px] tabular-nums text-muted-foreground">
        {sheet.row_count.toLocaleString()} rows · {sheet.col_count} cols
      </span>
    </button>
  )
}

interface FileSectionProps {
  file: SpreadsheetFile
  onOpenSheet: (sheet: SpreadsheetFile['sheets'][number]) => void
  onDelete: () => void
}

// One heading per uploaded Excel/CSV file, with that file's own sheets
// (x, y, z…) laid out underneath — so it's clear which sheet came from
// which spreadsheet, instead of a flat grid mixing everything together.
function FileSection({ file, onOpenSheet, onDelete }: FileSectionProps) {
  const [hovering, setHovering] = useState(false)
  const isReady = file.status === 'ready'

  return (
    <section
      className="animate-fade-in-up"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <div className="mb-3 flex items-center gap-2.5">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
          <FileSpreadsheet className="h-4 w-4 text-emerald-500" />
        </div>
        <h3 className="truncate text-base font-semibold">{file.display_name}</h3>
        <span className="shrink-0 text-xs text-muted-foreground">
          {isReady
            ? `${file.sheet_count} sheet${file.sheet_count !== 1 ? 's' : ''} · ${formatBytes(file.size_bytes)}`
            : file.status === 'failed' ? 'Failed to process' : 'Processing…'}
        </span>
        {hovering && (
          <button
            className="ml-auto shrink-0 rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
            onClick={onDelete}
            title="Delete file"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {isReady ? (
        <div className="grid grid-cols-3 gap-1 rounded-xl border border-border bg-card p-2 shadow-soft sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
          {file.sheets.map((sheet) => (
            <SheetTile key={sheet.id} sheet={sheet} onOpen={() => onOpenSheet(sheet)} />
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          {file.status === 'failed' ? 'This file failed to process.' : 'Processing this file…'}
        </div>
      )}
    </section>
  )
}

export function FilesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: files = [], isLoading } = useQuery({
    queryKey: ['files'],
    queryFn: () => filesApi.list().then((r) => r.data),
  })

  const deleteMutation = useMutation({
    mutationFn: (fileId: string) => filesApi.delete(fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
    onError: () => toast({ variant: 'destructive', title: 'Delete failed' }),
  })

  return (
    <AppShell>
      <div className="p-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Files</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Every uploaded file, with its own sheets grouped underneath.
            </p>
          </div>
          <button
            className="hover-lift rounded-lg border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent"
            onClick={() => navigate('/upload')}
          >
            Upload a file
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : files.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <FileSpreadsheet className="h-12 w-12 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No files yet.</p>
            <button
              className="rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={() => navigate('/upload')}
            >
              Upload your first file
            </button>
          </div>
        ) : (
          <div className="space-y-8">
            {files.map((file) => (
              <FileSection
                key={file.id}
                file={file}
                onOpenSheet={(sheet) => navigate(`/files/${file.id}/sheets/${sheet.id}`)}
                onDelete={() => deleteMutation.mutate(file.id)}
              />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  )
}
