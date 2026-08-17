import { useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { Search } from 'lucide-react'

interface ColumnFilterPopoverProps {
  colKey: string
  values: string[]
  selected: Set<string> | null // null = no filter (everything shown)
  x: number
  y: number
  onApply: (allowed: Set<string> | null) => void
  onClose: () => void
}

export function ColumnFilterPopover({ colKey, values, selected, x, y, onApply, onClose }: ColumnFilterPopoverProps) {
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState<Set<string>>(new Set(selected ?? values))

  const filteredValues = useMemo(
    () => values.filter((v) => v.toLowerCase().includes(search.toLowerCase())),
    [values, search],
  )

  const toggle = (v: string) => {
    setDraft((prev) => {
      const next = new Set(prev)
      if (next.has(v)) next.delete(v)
      else next.add(v)
      return next
    })
  }

  const selectAll = () => setDraft(new Set(values))
  const clearAll = () => setDraft(new Set())

  const apply = () => {
    onApply(draft.size === values.length ? null : new Set(draft))
    onClose()
  }

  return createPortal(
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        className="fixed z-50 w-64 rounded-md border border-border bg-background shadow-lg"
        style={{ left: x, top: y }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-border p-2">
          <p className="mb-1.5 truncate text-xs font-semibold">Filter: {colKey}</p>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search values…"
              className="h-7 w-full rounded border border-border bg-background pl-7 pr-2 text-xs outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        <div className="flex items-center gap-2 border-b border-border px-2 py-1.5 text-xs">
          <button className="text-primary hover:underline" onClick={selectAll}>Select all</button>
          <span className="text-muted-foreground">·</span>
          <button className="text-primary hover:underline" onClick={clearAll}>Clear</button>
        </div>

        <div className="max-h-56 overflow-y-auto p-1.5">
          {filteredValues.length === 0 ? (
            <p className="px-2 py-2 text-xs text-muted-foreground">No matching values</p>
          ) : (
            filteredValues.map((v) => (
              <label
                key={v}
                className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-xs hover:bg-accent"
              >
                <input
                  type="checkbox"
                  checked={draft.has(v)}
                  onChange={() => toggle(v)}
                  className="h-3.5 w-3.5"
                />
                <span className="truncate">{v === '' ? '(blank)' : v}</span>
              </label>
            ))
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-border p-2">
          <button className="rounded px-2 py-1 text-xs hover:bg-accent" onClick={onClose}>
            Cancel
          </button>
          <button
            className="rounded bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
            onClick={apply}
          >
            Apply
          </button>
        </div>
      </div>
    </>,
    document.body,
  )
}
