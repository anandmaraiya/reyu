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
      <div className="toast-root">
        {items.map(t => (
          <div key={t.id} className={`toast-card toast-${t.kind}`}>
            <div className="toast-body">
              <span className="toast-icon">{t.kind === 'success' ? '✔' : t.kind === 'error' ? '✖' : 'ℹ'}</span>
              <div className="toast-message">{t.msg}</div>
            </div>
            <div className="toast-progress" />
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}
