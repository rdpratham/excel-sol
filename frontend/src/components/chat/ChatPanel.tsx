import { useEffect, useRef, useState } from 'react'
import { Loader2, Send, Sparkles, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { queryApi } from '@/lib/api'
import type { QueryResult } from '@/types'

interface ChatPanelProps {
  fileId: string
  sheetId: string
  onClose: () => void
}

interface ChatEntry {
  id: string
  role: 'user' | 'assistant'
  content: string
  result?: QueryResult
}

const EXAMPLE_PROMPTS = [
  'average price by category',
  'show rows where status is Active',
  'top 5 by revenue',
  'sort by date descending',
]

export function ChatPanel({ fileId, sheetId, onClose }: ChatPanelProps) {
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)

  const { data: history } = useQuery({
    queryKey: ['query-history', fileId, sheetId],
    queryFn: () => queryApi.history(fileId, sheetId).then((r) => r.data),
  })

  useEffect(() => {
    if (!history) return
    setEntries(
      history.map((h) => ({
        id: h.id,
        role: h.role,
        content: h.content,
        result: h.result_preview
          ? { message: h.content, sql: h.sql_executed, columns: h.result_preview.columns, rows: h.result_preview.rows }
          : undefined,
      })),
    )
  }, [history])

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight })
  }, [entries, isSending])

  const send = async () => {
    const q = input.trim()
    if (!q || isSending) return
    setInput('')
    setEntries((prev) => [...prev, { id: crypto.randomUUID(), role: 'user', content: q }])
    setIsSending(true)
    try {
      const { data } = await queryApi.ask(fileId, sheetId, q)
      setEntries((prev) => [...prev, { id: crypto.randomUUID(), role: 'assistant', content: data.message, result: data }])
    } catch {
      setEntries((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'assistant', content: 'Something went wrong running that query. Please try again.' },
      ])
    } finally {
      setIsSending(false)
    }
  }

  return (
    <div className="flex h-full w-80 shrink-0 flex-col border-l border-border">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          <p className="font-display text-sm font-semibold tracking-tight">AI Assistant</p>
        </div>
        <button onClick={onClose} className="text-muted-foreground hover:text-foreground" aria-label="Close AI assistant">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div ref={listRef} className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
        {entries.length === 0 && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Ask a question about this sheet in plain English. Try:
            </p>
            {EXAMPLE_PROMPTS.map((ex) => (
              <button
                key={ex}
                onClick={() => setInput(ex)}
                className="block w-full rounded-md border border-border px-2 py-1.5 text-left text-xs hover:bg-accent"
              >
                {ex}
              </button>
            ))}
          </div>
        )}

        {entries.map((e) => (
          <div key={e.id} className={e.role === 'user' ? 'text-right' : ''}>
            <div
              className={
                e.role === 'user'
                  ? 'inline-block rounded-lg bg-primary px-3 py-1.5 text-xs text-primary-foreground'
                  : 'inline-block rounded-lg bg-muted px-3 py-1.5 text-xs'
              }
            >
              {e.content}
            </div>
            {e.result && e.result.rows.length > 0 && (
              <div className="mt-1.5 overflow-x-auto rounded-md border border-border">
                <table className="w-full text-[11px]">
                  <thead className="bg-muted/50">
                    <tr>
                      {e.result.columns.map((c) => (
                        <th key={c} className="whitespace-nowrap px-2 py-1 text-left font-medium">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {e.result.rows.slice(0, 25).map((r, i) => (
                      <tr key={i} className="border-t border-border">
                        {e.result!.columns.map((c) => (
                          <td key={c} className="whitespace-nowrap px-2 py-1">{String(r[c] ?? '')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {e.result.rows.length > 25 && (
                  <p className="px-2 py-1 text-[10px] text-muted-foreground">
                    +{e.result.rows.length - 25} more rows
                  </p>
                )}
              </div>
            )}
          </div>
        ))}

        {isSending && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> Thinking…
          </div>
        )}
      </div>

      <div className="flex items-center gap-1.5 border-t border-border p-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') send() }}
          placeholder="Ask about this sheet…"
          disabled={isSending}
          className="h-8 flex-1 rounded-md border border-border bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
        />
        <Button size="sm" className="h-8 w-8 shrink-0 p-0" onClick={send} disabled={isSending || !input.trim()}>
          <Send className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
