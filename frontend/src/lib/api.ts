import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { useAuthStore } from '@/stores/authStore'
import type {
  CellAlign,
  CellStylePatch,
  DashboardStats,
  NumberFormat,
  QueryHistoryEntry,
  QueryResult,
  RowsResponse,
  SpreadsheetFile,
  TokenResponse,
} from '@/types'

// In dev the Vite proxy handles /api → localhost:8000, so we use relative paths.
// In production VITE_API_URL points to the backend service.
const BASE_URL = import.meta.env.VITE_API_URL
  ? `${import.meta.env.VITE_API_URL}/api/v1`
  : '/api/v1'

export const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// Attach access token to every request
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = useAuthStore.getState().accessToken
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Token refresh queue
let isRefreshing = false
let refreshQueue: Array<(token: string) => void> = []

api.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    if (error.response?.status !== 401 || original._retry) {
      return Promise.reject(error)
    }

    // Don't try to refresh if we're on the auth endpoints themselves
    if (original.url?.includes('/auth/')) {
      useAuthStore.getState().clearAuth()
      return Promise.reject(error)
    }

    if (isRefreshing) {
      return new Promise<string>((resolve) => {
        refreshQueue.push(resolve)
      }).then((token) => {
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      })
    }

    original._retry = true
    isRefreshing = true

    try {
      const { data } = await axios.post<TokenResponse>(
        `${BASE_URL}/auth/refresh`,
        {},
        { withCredentials: true },
      )
      const newToken = data.access_token
      useAuthStore.getState().setAuth(data.user, newToken)
      refreshQueue.forEach((cb) => cb(newToken))
      refreshQueue = []
      original.headers.Authorization = `Bearer ${newToken}`
      return api(original)
    } catch {
      useAuthStore.getState().clearAuth()
      refreshQueue = []
      window.location.href = '/login'
      return Promise.reject(error)
    } finally {
      isRefreshing = false
    }
  },
)

// ── Auth ──────────────────────────────────────────────────────────────────────

export const authApi = {
  login: (email: string, password: string) =>
    api.post<TokenResponse>('/auth/login', { email, password }),

  refresh: () => api.post<TokenResponse>('/auth/refresh'),

  logout: () => api.post('/auth/logout'),

  me: () => api.get<TokenResponse['user']>('/auth/me'),
}

// ── Files ─────────────────────────────────────────────────────────────────────

export const filesApi = {
  upload: (file: File, onProgress?: (pct: number) => void) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<SpreadsheetFile>('/files/upload', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
      },
    })
  },

  list: () => api.get<SpreadsheetFile[]>('/files'),

  get: (fileId: string) => api.get<SpreadsheetFile>(`/files/${fileId}`),

  delete: (fileId: string) => api.delete(`/files/${fileId}`),

  getRows: (fileId: string, sheetId: string, page = 1, pageSize = 100) =>
    api.get<RowsResponse>(`/files/${fileId}/sheets/${sheetId}/rows`, {
      params: { page, page_size: pageSize },
    }),
}

// ── Row editing ───────────────────────────────────────────────────────────────

export const rowsApi = {
  patch: (fileId: string, sheetId: string, rowIndex: number, cells: { col_key: string; value: unknown }[]) =>
    api.patch(`/files/${fileId}/sheets/${sheetId}/rows/${rowIndex}`, { cells }),

  append: (fileId: string, sheetId: string, data: Record<string, unknown> = {}) =>
    api.post(`/files/${fileId}/sheets/${sheetId}/rows`, { data }),

  deleteRows: (fileId: string, sheetId: string, rowIndexes: number[]) =>
    api.delete(`/files/${fileId}/sheets/${sheetId}/rows`, { data: { row_indexes: rowIndexes } }),

  // Materializes blank rows up to targetRowCount in one call — backs editing
  // a blank cell far below the current data, Excel-style.
  ensureRows: (fileId: string, sheetId: string, targetRowCount: number) =>
    api.post<{ row_count: number }>(`/files/${fileId}/sheets/${sheetId}/rows/ensure`, {
      target_row_count: targetRowCount,
    }),

  exportUrl: (fileId: string, sheetId: string) =>
    `${api.defaults.baseURL}/files/${fileId}/sheets/${sheetId}/export`,
}

// ── Formatting — number format/align, per-cell style, column insert/delete ────

export const formattingApi = {
  updateColumnFormat: (
    fileId: string,
    sheetId: string,
    colKey: string,
    body: { number_format?: NumberFormat; align?: CellAlign },
  ) => api.patch(`/files/${fileId}/sheets/${sheetId}/columns/${encodeURIComponent(colKey)}/format`, body),

  updateCellStyle: (
    fileId: string,
    sheetId: string,
    cells: { row_index: number; col_key: string }[],
    style: CellStylePatch,
  ) => api.patch(`/files/${fileId}/sheets/${sheetId}/cell-style`, { cells, style }),

  addColumn: (fileId: string, sheetId: string, name: string, dtype = 'text', position?: number) =>
    api.post(`/files/${fileId}/sheets/${sheetId}/columns`, { name, dtype, position }),

  deleteColumn: (fileId: string, sheetId: string, colKey: string) =>
    api.delete(`/files/${fileId}/sheets/${sheetId}/columns/${encodeURIComponent(colKey)}`),
}

// ── Stats ─────────────────────────────────────────────────────────────────────

export const statsApi = {
  get: () => api.get<DashboardStats>('/stats'),
}

// ── AI query panel ────────────────────────────────────────────────────────────

export const queryApi = {
  ask: (fileId: string, sheetId: string, query: string) =>
    api.post<QueryResult>(`/files/${fileId}/sheets/${sheetId}/query`, { query }),

  history: (fileId: string, sheetId: string) =>
    api.get<QueryHistoryEntry[]>(`/files/${fileId}/sheets/${sheetId}/query/history`),
}
