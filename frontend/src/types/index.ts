// ── Domain types (mirror backend schemas) ─────────────────────────────────────

export type UserRole = 'admin' | 'editor' | 'viewer'

export interface User {
  id: string
  email: string
  full_name: string
  role: UserRole
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

export interface TokenResponse {
  access_token: string
  token_type: string
  user: User
}

export type FileStatus = 'uploading' | 'processing' | 'ready' | 'failed'

export type NumberFormat = 'general' | 'number' | 'currency' | 'percent'
export type CellAlign = 'left' | 'center' | 'right'

export interface SheetColumn {
  name: string
  dtype: string
  index: number
  width: number
  format?: NumberFormat
  align?: CellAlign
}

export interface CellStyle {
  bold?: boolean
  italic?: boolean
  font_color?: string
  bg_color?: string
  align?: CellAlign
}

// A PATCH payload: `null` on a field explicitly clears that override (vs.
// `undefined`, which leaves it untouched) — mirrors the backend's
// exclude_unset semantics for merging into the sparse cell_styles map.
export interface CellStylePatch {
  bold?: boolean | null
  italic?: boolean | null
  font_color?: string | null
  bg_color?: string | null
  align?: CellAlign | null
}

export interface Sheet {
  id: string
  file_id: string
  name: string
  sheet_index: number
  row_count: number
  col_count: number
  columns: SheetColumn[]
  cell_styles: Record<string, CellStyle>
  created_at: string
}

export interface SpreadsheetFile {
  id: string
  owner_id: string
  original_filename: string
  display_name: string
  size_bytes: number
  mime_type: string
  status: FileStatus
  error_message: string | null
  sheet_count: number
  total_rows: number
  created_at: string
  updated_at: string
  sheets: Sheet[]
}

// ── API error shape ───────────────────────────────────────────────────────────

export interface ApiError {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
}

// ── Sheet rows ────────────────────────────────────────────────────────────────

export interface RowsResponse {
  columns: SheetColumn[]
  rows: Record<string, unknown>[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export interface DashboardStats {
  total_files: number
  total_sheets: number
  total_rows: number
  storage_bytes: number
  ai_queries_this_month: number
  recent_files: SpreadsheetFile[]
}

// ── AI query panel ────────────────────────────────────────────────────────────

export interface QueryResult {
  message: string
  sql: string | null
  columns: string[]
  rows: Record<string, unknown>[]
}

export interface QueryHistoryEntry {
  id: string
  role: 'user' | 'assistant'
  content: string
  sql_executed: string | null
  result_preview: { columns: string[]; rows: Record<string, unknown>[] } | null
  created_at: string
}
