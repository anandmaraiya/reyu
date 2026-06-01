import { ReactNode } from 'react'

type TooltipProps = {
  children: ReactNode
  content: ReactNode
  position?: 'top' | 'right' | 'bottom' | 'left'
}

export default function Tooltip({ children, content, position = 'top' }: TooltipProps) {
  return (
    <div className={`tooltip tooltip-${position}`}>
      {children}
      <div className="tooltip-content" role="tooltip">
        {content}
      </div>
    </div>
  )
}
