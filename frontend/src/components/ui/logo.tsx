import { cn } from '@/lib/utils'

interface LogoProps {
  size?: 'sm' | 'md' | 'lg'
  showText?: boolean
  className?: string
}

const sizeMap = {
  sm: { mark: 'h-6 w-6', text: 'text-base' },
  md: { mark: 'h-8 w-8', text: 'text-lg' },
  lg: { mark: 'h-12 w-12', text: 'text-3xl' },
}

export function Logo({ size = 'md', showText = true, className }: LogoProps) {
  const s = sizeMap[size]
  return (
    <div className={cn('flex items-center gap-2.5', className)}>
      {/* Logo mark: 2×2 grid with gradient */}
      <svg
        viewBox="0 0 32 32"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className={cn('shrink-0', s.mark)}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="ms-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#3B82F6" />
            <stop offset="50%" stopColor="#10B981" />
            <stop offset="100%" stopColor="#EF4444" />
          </linearGradient>
        </defs>
        <rect width="32" height="32" rx="7" fill="url(#ms-grad)" />
        {/* top-left cell */}
        <rect x="6" y="6" width="9" height="8" rx="1.5" fill="white" fillOpacity="0.92" />
        {/* top-right cell */}
        <rect x="17" y="6" width="9" height="8" rx="1.5" fill="white" fillOpacity="0.75" />
        {/* bottom-left cell */}
        <rect x="6" y="16" width="9" height="10" rx="1.5" fill="white" fillOpacity="0.75" />
        {/* bottom-right cell */}
        <rect x="17" y="16" width="9" height="10" rx="1.5" fill="white" fillOpacity="0.55" />
        {/* Neural spark at intersection */}
        <circle cx="15.5" cy="15" r="2.5" fill="white" />
      </svg>

      {showText && (
        <span className={cn('font-bold tracking-tight', s.text)}>
          <span className="brand-gradient-text">Mind</span>
          <span className="text-foreground">Spread</span>
        </span>
      )}
    </div>
  )
}
