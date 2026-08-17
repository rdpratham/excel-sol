// Kicks off the SheetPage chunk fetch (glide-data-grid and friends, ~340KB)
// on hover/focus, before the user actually clicks — so opening a sheet from
// Files/Dashboard feels instant instead of waiting on a fresh chunk request.
// Safe to call repeatedly: the dynamic import is cached by the browser and
// by Vite's module registry after the first call.
let started = false
export function prefetchSheetPage(): void {
  if (started) return
  started = true
  import('@/pages/SheetPage')
}
