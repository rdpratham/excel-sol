// Builds the sheet collaboration WebSocket URL.
//
// In dev, VITE_API_URL is unset and Vite's dev server proxies /ws → ws://localhost:8000
// (see vite.config.ts), so a relative ws(s):// URL against the current page origin works.
// In production, VITE_API_URL points straight at the backend origin.
export function sheetSocketUrl(sheetId: string, token: string): string {
  const apiUrl = import.meta.env.VITE_API_URL as string | undefined
  const base = apiUrl
    ? apiUrl.replace(/^http/, 'ws')
    : `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`

  const params = new URLSearchParams({ token })
  return `${base}/ws/sheets/${sheetId}?${params.toString()}`
}
