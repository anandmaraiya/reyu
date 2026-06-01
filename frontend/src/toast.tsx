import { createContext, useCallback, useContext, useState, ReactNode } from 'react'

type Toast = { id: number; kind: 'success' | 'error' | 'info'; msg: string }
type Ctx = { push: (kind: Toast['kind'], msg: string) => void }
const ToastCtx = createContext<Ctx>({ push: () => {} })

export const useToast = () => useContext(ToastCtx)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((kind: Toast['kind'], msg: string) => {
    const id = Date.now() + Math.random()
    setItems(prev => [...prev, { id, kind, msg }])
    setTimeout(() => setItems(prev => prev.filter(t => t.id !== id)), 4500)
  }, [])
  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div style={{ position: 'fixed', top: 12, right: 12, zIndex: 200, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {items.map(t => (
          <div key={t.id} className="card" style={{
            minWidth: 220, padding: '8px 12px', fontSize: 13,
            borderLeft: `3px solid ${t.kind === 'error' ? 'var(--red)' : t.kind === 'success' ? 'var(--green)' : 'var(--accent)'}`,
          }}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
