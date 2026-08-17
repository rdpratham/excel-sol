import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FileSpreadsheet, Loader2, Trash2, Upload } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { filesApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { toast } from '@/hooks/useToast'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function UploadPage() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const queryClient = useQueryClient()

  const { data: files = [] } = useQuery({
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
    <AppShell>
      <div className="mx-auto max-w-3xl p-6">
        <div className="mb-6">
          <h2 className="text-xl font-semibold">Upload</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Add an Excel or CSV file to start working with your data.
          </p>
        </div>

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
            'flex cursor-pointer flex-col items-center gap-3 rounded-lg border-2 border-dashed p-12 text-center transition-colors',
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
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-sm font-medium">Processing…</p>
            </>
          ) : (
            <>
              <Upload className="h-8 w-8 text-muted-foreground" />
              <p className="text-sm font-medium">Drag & drop a file here, or click to browse</p>
              <p className="text-xs text-muted-foreground">.xlsx, .xlsm, .csv</p>
            </>
          )}
        </div>

        {files.length > 0 && (
          <div className="mt-8">
            <h3 className="mb-2 text-sm font-semibold text-muted-foreground">Uploaded files</h3>
            <div className="divide-y divide-border rounded-lg border border-border">
              {files.map((file) => (
                <div key={file.id} className="flex items-center gap-3 px-4 py-3">
                  {file.status === 'ready' ? (
                    <FileSpreadsheet className="h-5 w-5 shrink-0 text-emerald-500" />
                  ) : (
                    <Loader2 className="h-5 w-5 shrink-0 animate-spin text-muted-foreground" />
                  )}
                  <button
                    className="min-w-0 flex-1 text-left"
                    onClick={() => file.sheets[0] && navigate(`/files/${file.id}/sheets/${file.sheets[0].id}`)}
                    disabled={file.status !== 'ready'}
                  >
                    <p className="truncate text-sm font-medium">{file.display_name}</p>
                    <p className="text-xs text-muted-foreground">
                      {file.status === 'ready'
                        ? `${formatBytes(file.size_bytes)} · ${file.sheet_count} sheet${file.sheet_count !== 1 ? 's' : ''} · ${file.total_rows.toLocaleString()} rows`
                        : file.status === 'failed' ? 'Failed to process' : 'Processing…'}
                    </p>
                  </button>
                  <button
                    className="shrink-0 rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => deleteMutation.mutate(file.id)}
                    title="Delete file"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
