import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Loader2 } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { filesApi } from '@/lib/api'
import type { SpreadsheetFile, Sheet } from '@/types'

const PAGE_SIZE = 100

export function SheetPage() {
  const { fileId, sheetId } = useParams<{ fileId: string; sheetId: string }>()
  const navigate = useNavigate()
  const [page, setPage] = useState(1)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['rows', fileId, sheetId, page],
    queryFn: () => filesApi.getRows(fileId!, sheetId!, page, PAGE_SIZE).then((r) => r.data),
    enabled: !!fileId && !!sheetId,
  })

  const { data: file } = useQuery({
    queryKey: ['file', fileId],
    queryFn: () => filesApi.get(fileId!).then((r) => r.data),
    enabled: !!fileId,
  })

  const sheet = file?.sheets.find((s) => s.id === sheetId)

  const handleSheetSelect = (f: SpreadsheetFile, s: Sheet) => {
    navigate(`/files/${f.id}/sheets/${s.id}`)
  }

  return (
    <AppShell activeSheetId={sheetId} onSheetSelect={handleSheetSelect}>
      <div className="flex h-full flex-col">
        {/* Sheet header */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-muted-foreground">{file?.display_name}</p>
            <h2 className="truncate text-sm font-semibold">{sheet?.name ?? '…'}</h2>
          </div>
          {data && (
            <p className="shrink-0 text-xs text-muted-foreground">
              {data.total.toLocaleString()} rows · {data.columns.length} columns
            </p>
          )}
        </div>

        {/* Table */}
        <div className="min-h-0 flex-1 overflow-auto">
          {isLoading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : isError ? (
            <div className="flex h-full items-center justify-center text-sm text-destructive">
              Failed to load rows
            </div>
          ) : !data || data.columns.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              This sheet is empty
            </div>
          ) : (
            <table className="w-full border-collapse text-xs">
              <thead className="sticky top-0 z-10 bg-background">
                <tr className="border-b border-border">
                  {/* Row number column */}
                  <th className="w-10 border-r border-border px-2 py-1.5 text-right font-mono text-muted-foreground">
                    #
                  </th>
                  {data.columns.map((col) => (
                    <th
                      key={col.name}
                      className="border-r border-border px-3 py-1.5 text-left font-medium last:border-r-0"
                      style={{ minWidth: col.width ?? 120, maxWidth: 300 }}
                    >
                      <div className="truncate" title={col.name}>
                        {col.name}
                      </div>
                      <div className="mt-0.5 text-muted-foreground/60 font-normal">{col.dtype}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50">
                {data.rows.map((row, i) => {
                  const globalRowNum = (page - 1) * PAGE_SIZE + i + 1
                  return (
                    <tr key={i} className="hover:bg-accent/30">
                      <td className="border-r border-border px-2 py-1 text-right font-mono text-muted-foreground">
                        {globalRowNum}
                      </td>
                      {data.columns.map((col) => {
                        const val = row[col.name]
                        return (
                          <td
                            key={col.name}
                            className="border-r border-border px-3 py-1 last:border-r-0"
                            style={{ maxWidth: 300 }}
                          >
                            <div className="truncate" title={val != null ? String(val) : ''}>
                              {val == null ? (
                                <span className="text-muted-foreground/40">—</span>
                              ) : (
                                String(val)
                              )}
                            </div>
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="flex items-center justify-between border-t border-border px-4 py-2">
            <p className="text-xs text-muted-foreground">
              Page {data.page} of {data.total_pages} · {data.total.toLocaleString()} total rows
            </p>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                className="h-7 w-7 p-0"
                disabled={page === 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-7 w-7 p-0"
                disabled={page >= data.total_pages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
