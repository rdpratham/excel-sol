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

export interface SheetColumn {
  name: string
  dtype: string
  index: number
  width: number
}

export interface Sheet {
  id: string
  file_id: string
  name: string
  sheet_index: number
  row_count: number
  col_count: number
  columns: SheetColumn[]
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

// ── Dashboard ─────────────────────────────────────────────────────────────────

export interface DashboardStats {
  total_files: number
  total_sheets: number
  total_rows: number
  storage_bytes: number
  ai_queries_this_month: number
  recent_files: SpreadsheetFile[]
}
