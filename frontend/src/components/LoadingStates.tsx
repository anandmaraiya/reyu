import { ReactNode } from 'react'

export function LoadingSkeleton({ className }: { className?: string }) {
  return <div className={`loading-skeleton ${className ?? ''}`} />
}

export function TableSkeleton() {
  return (
    <div className="table-skeleton">
      {Array.from({ length: 6 }).map((_, idx) => (
        <div className="table-row-skeleton" key={idx}>
          <div className="row-cell-skeleton" />
          <div className="row-cell-skeleton" />
          <div className="row-cell-skeleton" />
          <div className="row-cell-skeleton" />
          <div className="row-cell-skeleton" />
        </div>
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-hero">⚡</div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  )
}
