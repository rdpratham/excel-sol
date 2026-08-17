import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Loader2, Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { filesApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { toast } from '@/hooks/useToast'
import type { SpreadsheetFile } from '@/types'

interface SheetTileProps {
  file: SpreadsheetFile
  sheet: SpreadsheetFile['sheets'][number]
  onOpen: () => void
  onDelete: () => void
}

function SheetTile({ file, sheet, onOpen, onDelete }: SheetTileProps) {
  const [hovering, setHovering] = useState(false)

  return (
    <div
      className="group relative flex flex-col items-center gap-1.5 rounded-lg border border-transparent p-3 text-center hover:border-border hover:bg-accent"
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <button
        className="flex w-full flex-col items-center gap-1.5"
        onClick={onOpen}
        title={`${file.display_name} — ${sheet.name}`}
      >
        <FileSpreadsheet className="h-16 w-16 text-emerald-500" strokeWidth={1.1} />
        <span className="line-clamp-2 w-full break-words text-sm font-medium leading-tight">
          {sheet.name}
        </span>
        <span className="line-clamp-1 w-full break-words text-xs text-muted-foreground">
          {file.display_name}
        </span>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          {sheet.row_count.toLocaleString()} rows
        </span>
      </button>

      {hovering && (
        <button
          className="absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded hover:bg-destructive/10 hover:text-destructive"
          onClick={(e) => { e.stopPropagation(); onDelete() }}
          title="Delete file"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

function ProcessingTile({ file }: { file: SpreadsheetFile }) {
  return (
    <div className="flex flex-col items-center gap-1.5 rounded-lg p-3 text-center opacity-60">
      <Loader2 className="h-12 w-12 animate-spin text-muted-foreground" />
      <span className="line-clamp-2 w-full break-words text-sm font-medium leading-tight">
        {file.display_name}
      </span>
      <span className="text-xs text-muted-foreground">
        {file.status === 'failed' ? 'Failed to process' : 'Processing…'}
      </span>
    </div>
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

  const sheetEntries = files.flatMap((file) => file.sheets.map((sheet) => ({ file, sheet })))
  const processingFiles = files.filter((f) => f.status !== 'ready' && f.sheets.length === 0)

  return (
    <AppShell>
      <div className="p-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h2 className={cn('text-xl font-semibold')}>Files</h2>
            <p className="mt-0.5 text-sm text-muted-foreground">
              All your sheets, across every uploaded file.
            </p>
          </div>
          <button
            className="rounded-md border border-border px-3 py-1.5 text-sm font-medium hover:bg-accent"
            onClick={() => navigate('/upload')}
          >
            Upload a file
          </button>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : sheetEntries.length === 0 && processingFiles.length === 0 ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <FileSpreadsheet className="h-12 w-12 text-muted-foreground/40" />
            <p className="text-sm text-muted-foreground">No files yet.</p>
            <button
              className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              onClick={() => navigate('/upload')}
            >
              Upload your first file
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
            {sheetEntries.map(({ file, sheet }) => (
              <SheetTile
                key={sheet.id}
                file={file}
                sheet={sheet}
                onOpen={() => navigate(`/files/${file.id}/sheets/${sheet.id}`)}
                onDelete={() => deleteMutation.mutate(file.id)}
              />
            ))}
            {processingFiles.map((file) => (
              <ProcessingTile key={file.id} file={file} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  )
}
