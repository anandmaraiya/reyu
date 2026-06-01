import { ReactNode } from 'react'

type FilterOption = { label: string; active?: boolean; onClick: () => void }

type FilterBarProps = {
  title?: string
  searchValue?: string
  onSearch?: (value: string) => void
  onSearchFocus?: () => void
  onClearAll?: () => void
  filters?: FilterOption[]
  suggestions?: string[]
  onSuggestionClick?: (value: string) => void
  rightContent?: ReactNode
}

export default function FilterBar({
  title,
  searchValue,
  onSearch,
  onSearchFocus,
  onClearAll,
  filters,
  suggestions,
  onSuggestionClick,
  rightContent,
}: FilterBarProps) {
  return (
    <div className="filter-bar">
      <div className="filter-bar-left">
        {title && <div className="filter-bar-title">{title}</div>}
        <div className="filter-bar-search">
          <span className="filter-bar-icon">🔍</span>
          <input
            value={searchValue ?? ''}
            onChange={e => onSearch?.(e.target.value)}
            onFocus={() => onSearchFocus?.()}
            placeholder="Search symbols, strategies, tags..."
            autoComplete="off"
          />
        </div>
      </div>
      <div className="filter-bar-right">
        {filters?.map(filter => (
          <button
            key={filter.label}
            type="button"
            className={`filter-pill ${filter.active ? 'active' : ''}`}
            onClick={filter.onClick}
          >
            {filter.label}
          </button>
        ))}
        {suggestions?.length ? (
          <div className="filter-bar-suggestions">
            {suggestions.map(item => (
              <button key={item} type="button" className="filter-suggestion-pill" onClick={() => onSuggestionClick?.(item)}>
                {item}
              </button>
            ))}
          </div>
        ) : null}
        {onClearAll && (
          <button type="button" className="filter-clear" onClick={onClearAll}>
            Clear all
          </button>
        )}
        {rightContent}
      </div>
    </div>
  )
}
