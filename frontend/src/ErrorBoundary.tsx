import { Component, ErrorInfo, ReactNode } from 'react'

type State = { error: Error | null }

export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error('Reyu error boundary caught:', error, info.componentStack)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="page-shell" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '80vh' }}>
        <div className="card" style={{ maxWidth: 520, textAlign: 'center' }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>⚠️</div>
          <h3 style={{ margin: '0 0 8px' }}>Something went wrong</h3>
          <p style={{ color: 'var(--muted)', fontSize: 13 }}>
            The page crashed while rendering. Your data is safe — try refreshing this view.
          </p>
          <pre style={{
            background: 'var(--panel-hover, var(--panel))', padding: 8, borderRadius: 6,
            fontSize: 11, color: 'var(--bear, var(--red))', textAlign: 'left', maxHeight: 160, overflow: 'auto',
            marginTop: 10,
          }}>{String(this.state.error?.stack || this.state.error?.message)}</pre>
          <div className="row" style={{ justifyContent: 'center', gap: 8, marginTop: 12 }}>
            <button className="primary" onClick={this.reset}>Retry</button>
            <button className="ghost" onClick={() => window.location.assign('/dashboard')}>Go home</button>
          </div>
        </div>
      </div>
    )
  }
}
