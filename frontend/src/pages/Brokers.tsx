/**
 * Brokers connection page  (/brokers)
 *
 * Shows all supported brokers from the catalog, their connection status,
 * OAuth connect / disconnect actions, and basic account info for connected brokers.
 *
 * Gate: anonymous users are prompted to log in before connecting.
 */
import { useState, useEffect, useCallback } from 'react'
import { useAuth, api } from '../context/AuthContext'

// ─── Types ────────────────────────────────────────────────────────────────────

interface CatalogBroker {
  id: string
  name: string
  logo_url: string
  status: 'live' | 'beta' | 'coming_soon'
  auth_type: string
  tagline?: string
}

interface ConnectedBroker {
  broker_id: string
  status: 'connected' | 'disconnected'
  connected_at?: string
}

interface BrokerProfile {
  name: string
  email: string
  funds_available: number
  funds_used: number
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: CatalogBroker['status'] }) {
  const cfg = {
    live:         { label: 'Live',        color: '#10b981', bg: 'rgba(16,185,129,.12)' },
    beta:         { label: 'Beta',        color: '#f59e0b', bg: 'rgba(245,158,11,.12)' },
    coming_soon:  { label: 'Coming soon', color: '#94a3b8', bg: 'rgba(148,163,184,.12)' },
  }[status]
  return (
    <span style={{
      display: 'inline-block',
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: '.5px',
      textTransform: 'uppercase',
      padding: '2px 7px',
      borderRadius: 999,
      color: cfg.color,
      background: cfg.bg,
    }}>
      {cfg.label}
    </span>
  )
}

// ─── Broker logo (SVG fallback) ───────────────────────────────────────────────

function BrokerLogo({ id, name, logoUrl }: { id: string; name: string; logoUrl: string }) {
  const [err, setErr] = useState(false)
  if (err || !logoUrl) {
    // Fallback: colored initial
    const colors: Record<string, string> = {
      fyers: '#e63946', zerodha: '#387ed1', angelone: '#c0392b', groww: '#00b386',
    }
    return (
      <div style={{
        width: 48, height: 48, borderRadius: 12,
        background: colors[id] || '#6366f1',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 20, fontWeight: 700, color: '#fff',
      }}>
        {name[0]}
      </div>
    )
  }
  return (
    <img
      src={logoUrl}
      alt={name}
      onError={() => setErr(true)}
      style={{ width: 48, height: 48, objectFit: 'contain', borderRadius: 8 }}
    />
  )
}

// ─── Single broker card ───────────────────────────────────────────────────────

function BrokerCard({
  broker,
  connected,
  onConnect,
  onDisconnect,
}: {
  broker: CatalogBroker
  connected?: ConnectedBroker
  onConnect: (id: string) => void
  onDisconnect: (id: string) => void
}) {
  const isConnected = connected?.status === 'connected'
  const isComingSoon = broker.status === 'coming_soon'
  const [profile, setProfile] = useState<BrokerProfile | null>(null)
  const [loadingProfile, setLoadingProfile] = useState(false)

  useEffect(() => {
    if (!isConnected) { setProfile(null); return }
    setLoadingProfile(true)
    api.get(`/api/brokers/${broker.id}/profile`)
      .then(r => setProfile(r.data))
      .catch(() => setProfile(null))
      .finally(() => setLoadingProfile(false))
  }, [isConnected, broker.id])

  return (
    <div className={`broker-card ${isConnected ? 'broker-card-connected' : ''}`}>
      {/* Logo + name row */}
      <div className="broker-top">
        <BrokerLogo id={broker.id} name={broker.name} logoUrl={broker.logo_url} />
        <div className="broker-info">
          <div className="broker-name">{broker.name}</div>
          <div className="broker-badges">
            <StatusBadge status={broker.status} />
            {isConnected && (
              <span className="broker-connected-badge">
                <span className="broker-green-dot" />
                Connected
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Profile strip for connected brokers */}
      {isConnected && (
        <div className="broker-profile">
          {loadingProfile ? (
            <div className="broker-profile-loading">Loading account info…</div>
          ) : profile ? (
            <div className="broker-funds-row">
              <div className="broker-fund-item">
                <div className="broker-fund-label">Available</div>
                <div className="broker-fund-val">₹{profile.funds_available.toLocaleString('en-IN')}</div>
              </div>
              <div className="broker-fund-item">
                <div className="broker-fund-label">Used</div>
                <div className="broker-fund-val used">₹{profile.funds_used.toLocaleString('en-IN')}</div>
              </div>
              {profile.name && (
                <div className="broker-fund-item">
                  <div className="broker-fund-label">Account</div>
                  <div className="broker-fund-val">{profile.name}</div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* Action button */}
      <div className="broker-actions">
        {isConnected ? (
          <button className="broker-btn broker-btn-disconnect" onClick={() => onDisconnect(broker.id)}>
            Disconnect
          </button>
        ) : (
          <button
            className={`broker-btn broker-btn-connect ${isComingSoon ? 'broker-btn-disabled' : ''}`}
            disabled={isComingSoon}
            onClick={() => !isComingSoon && onConnect(broker.id)}
          >
            {isComingSoon ? 'Coming soon' : `Connect ${broker.name}`}
          </button>
        )}
      </div>

      {broker.status === 'beta' && (
        <div className="broker-beta-note">Beta — paper trading only. Orders not executed.</div>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function Brokers() {
  const { isAuthenticated, openGate } = useAuth()
  const [catalog, setCatalog] = useState<CatalogBroker[]>([])
  const [connectedMap, setConnectedMap] = useState<Record<string, ConnectedBroker>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyBroker, setBusyBroker] = useState<string | null>(null)
  const [toast, setToast] = useState<{ type: 'ok' | 'err'; msg: string } | null>(null)

  const pushToast = (type: 'ok' | 'err', msg: string) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 4000)
  }

  const loadData = useCallback(async () => {
    try {
      const [catRes, connRes] = await Promise.allSettled([
        api.get('/api/brokers/catalog'),
        isAuthenticated ? api.get('/api/brokers/connected') : Promise.resolve({ data: { brokers: [] } }),
      ])
      if (catRes.status === 'fulfilled') {
        setCatalog(catRes.value.data.brokers || [])
      }
      if (connRes.status === 'fulfilled') {
        const map: Record<string, ConnectedBroker> = {}
        for (const b of connRes.value.data.brokers || []) {
          map[b.broker_id] = b
        }
        setConnectedMap(map)
      }
    } catch (e: any) {
      setError('Failed to load broker catalog.')
    } finally {
      setLoading(false)
    }
  }, [isAuthenticated])

  useEffect(() => { loadData() }, [loadData])

  // ── Connect ──────────────────────────────────────────────────────────────

  async function handleConnect(brokerId: string) {
    if (!isAuthenticated) {
      openGate({
        mode: 'login',
        message: 'Sign in to connect your broker and get live data.',
        onSuccess: () => handleConnect(brokerId),
      })
      return
    }
    setBusyBroker(brokerId)
    try {
      const { data } = await api.get(`/api/brokers/${brokerId}/oauth-url`)
      if (data.url) {
        // Redirect to broker OAuth — they'll come back to /api/brokers/{id}/callback
        window.location.href = data.url
      }
    } catch (e: any) {
      pushToast('err', e?.response?.data?.detail || 'Could not get OAuth URL.')
      setBusyBroker(null)
    }
  }

  // ── Disconnect ────────────────────────────────────────────────────────────

  async function handleDisconnect(brokerId: string) {
    const broker = catalog.find(b => b.id === brokerId)
    if (!confirm(`Disconnect ${broker?.name ?? brokerId}? Live data and orders will stop.`)) return
    setBusyBroker(brokerId)
    try {
      await api.delete(`/api/brokers/${brokerId}`)
      pushToast('ok', `${broker?.name ?? brokerId} disconnected.`)
      await loadData()
    } catch (e: any) {
      pushToast('err', e?.response?.data?.detail || 'Disconnect failed.')
    }
    setBusyBroker(null)
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  const connectedCount = Object.values(connectedMap).filter(b => b.status === 'connected').length

  return (
    <div className="brokers-page">
      {/* Toast */}
      {toast && (
        <div className={`sub-toast ${toast.type === 'ok' ? 'sub-toast-ok' : 'sub-toast-err'}`}>
          {toast.type === 'ok' ? '✓' : '⚠'} {toast.msg}
        </div>
      )}

      {/* Page header */}
      <div className="brokers-header">
        <div>
          <h1 className="brokers-title">Broker Connections</h1>
          <p className="brokers-subtitle">
            Connect your broker to get live quotes, positions, and one-click order execution.
            All credentials are stored encrypted — Reyu.ai never sees your passwords.
          </p>
        </div>
        {connectedCount > 0 && (
          <div className="brokers-conn-badge">
            <span className="broker-green-dot" />
            {connectedCount} connected
          </div>
        )}
      </div>

      {/* Anon nudge */}
      {!isAuthenticated && (
        <div className="brokers-anon-nudge">
          <span className="brokers-anon-icon">🔗</span>
          <div>
            <strong>Sign in to connect a broker</strong>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 2 }}>
              You're browsing in demo mode. Sign in to link your Fyers or Zerodha account.
            </div>
          </div>
          <button
            className="brokers-signin-btn"
            onClick={() => openGate({ mode: 'login' })}
          >
            Sign in
          </button>
        </div>
      )}

      {/* Loading / error */}
      {loading && (
        <div className="brokers-loading">
          <div className="brokers-spinner" />
          Loading broker catalog…
        </div>
      )}
      {error && <div className="brokers-error">{error}</div>}

      {/* Broker grid */}
      {!loading && (
        <div className="brokers-grid">
          {catalog.map(broker => (
            <div key={broker.id} style={{ opacity: busyBroker === broker.id ? 0.6 : 1, transition: 'opacity .2s' }}>
              <BrokerCard
                broker={broker}
                connected={connectedMap[broker.id]}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
              />
            </div>
          ))}
          {catalog.length === 0 && !loading && (
            <div className="brokers-empty">No brokers available — check backend config.</div>
          )}
        </div>
      )}

      {/* How it works */}
      <div className="brokers-how">
        <h2 className="brokers-how-title">How it works</h2>
        <div className="brokers-how-steps">
          {[
            { n: '1', title: 'Click Connect', body: 'You\'re redirected to your broker\'s login page. We never see your credentials.' },
            { n: '2', title: 'Authorize Reyu', body: 'Grant read/trade permissions on the broker\'s official OAuth screen.' },
            { n: '3', title: 'Live data flows', body: 'Real-time quotes, option chain, OI, and IV data appear across the platform.' },
            { n: '4', title: 'Place orders', body: 'One-click hedge builder, strike selection, and paper-to-live escalation.' },
          ].map(s => (
            <div key={s.n} className="brokers-step">
              <div className="brokers-step-num">{s.n}</div>
              <div>
                <div className="brokers-step-title">{s.title}</div>
                <div className="brokers-step-body">{s.body}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <style>{`
        .brokers-page {
          max-width: 960px;
          margin: 0 auto;
          padding: 32px 20px 60px;
        }
        .brokers-header {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 16px;
          margin-bottom: 24px;
          flex-wrap: wrap;
        }
        .brokers-title { font-size: 24px; font-weight: 700; margin: 0 0 6px; }
        .brokers-subtitle { font-size: 14px; color: var(--color-text-muted); margin: 0; max-width: 620px; line-height: 1.5; }
        .brokers-conn-badge {
          display: flex; align-items: center; gap: 6px;
          background: rgba(16,185,129,.1); border: 1px solid rgba(16,185,129,.25);
          padding: 6px 12px; border-radius: 999px; font-size: 13px; font-weight: 500;
          color: var(--color-success); white-space: nowrap; flex-shrink: 0;
        }
        .broker-green-dot {
          display: inline-block; width: 7px; height: 7px;
          background: #10b981; border-radius: 50%;
          box-shadow: 0 0 0 2px rgba(16,185,129,.25);
        }

        .brokers-anon-nudge {
          display: flex; align-items: center; gap: 12px;
          background: var(--color-bg-card); border: 1px solid var(--color-border);
          border-radius: 12px; padding: 14px 18px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .brokers-anon-icon { font-size: 22px; flex-shrink: 0; }
        .brokers-anon-nudge > div { flex: 1; min-width: 200px; }
        .brokers-signin-btn {
          background: var(--color-primary); color: #fff;
          border: none; border-radius: 8px; padding: 8px 16px;
          font-size: 13px; font-weight: 600; cursor: pointer;
          flex-shrink: 0;
        }
        .brokers-signin-btn:hover { filter: brightness(1.08); }

        .brokers-loading {
          display: flex; align-items: center; gap: 10px;
          color: var(--color-text-muted); font-size: 14px; padding: 40px 0;
          justify-content: center;
        }
        .brokers-spinner {
          width: 18px; height: 18px; border: 2px solid var(--color-border);
          border-top-color: var(--color-primary); border-radius: 50%;
          animation: spin .7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        .brokers-error {
          background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.25);
          border-radius: 10px; padding: 12px 16px; color: var(--color-danger);
          margin-bottom: 20px; font-size: 14px;
        }
        .brokers-empty { color: var(--color-text-muted); text-align: center; padding: 40px 0; }

        .brokers-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
          gap: 16px;
          margin-bottom: 40px;
        }

        /* Broker card */
        .broker-card {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 14px;
          padding: 20px;
          transition: box-shadow .2s, border-color .2s;
        }
        .broker-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,.1); }
        .broker-card-connected {
          border-color: rgba(16,185,129,.35);
          box-shadow: 0 0 0 1px rgba(16,185,129,.15);
        }
        .broker-top {
          display: flex; align-items: center; gap: 12px; margin-bottom: 14px;
        }
        .broker-info { flex: 1; min-width: 0; }
        .broker-name { font-size: 16px; font-weight: 600; margin-bottom: 5px; }
        .broker-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .broker-connected-badge {
          display: flex; align-items: center; gap: 4px;
          font-size: 11px; font-weight: 600; color: var(--color-success);
        }

        .broker-profile {
          background: var(--color-bg-base);
          border: 1px solid var(--color-border);
          border-radius: 8px; padding: 10px 12px; margin-bottom: 14px;
        }
        .broker-profile-loading { font-size: 12px; color: var(--color-text-muted); }
        .broker-funds-row { display: flex; gap: 16px; flex-wrap: wrap; }
        .broker-fund-item { flex: 1; min-width: 80px; }
        .broker-fund-label { font-size: 10px; color: var(--color-text-muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 2px; }
        .broker-fund-val { font-size: 14px; font-weight: 600; }
        .broker-fund-val.used { color: var(--color-danger); }

        .broker-actions { margin-bottom: 6px; }
        .broker-btn {
          width: 100%; padding: 9px; border-radius: 8px;
          font-size: 13px; font-weight: 600; cursor: pointer;
          border: none; transition: all .15s;
        }
        .broker-btn-connect {
          background: var(--color-primary); color: #fff;
          box-shadow: 0 2px 8px rgba(16,185,129,.25);
        }
        .broker-btn-connect:hover:not(.broker-btn-disabled) { filter: brightness(1.08); }
        .broker-btn-disconnect {
          background: none; border: 1px solid var(--color-border);
          color: var(--color-text-muted);
        }
        .broker-btn-disconnect:hover { border-color: var(--color-danger); color: var(--color-danger); }
        .broker-btn-disabled { background: var(--color-bg-base); color: var(--color-text-muted); cursor: default; border: 1px solid var(--color-border); box-shadow: none; }

        .broker-beta-note {
          font-size: 11px; color: rgba(245,158,11,.8);
          margin-top: 8px; text-align: center;
        }

        /* How it works */
        .brokers-how {
          background: var(--color-bg-card);
          border: 1px solid var(--color-border);
          border-radius: 14px; padding: 24px 28px;
        }
        .brokers-how-title { font-size: 16px; font-weight: 600; margin: 0 0 18px; }
        .brokers-how-steps { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
        .brokers-step { display: flex; gap: 12px; align-items: flex-start; }
        .brokers-step-num {
          width: 28px; height: 28px; border-radius: 50%;
          background: var(--color-primary); color: #fff;
          display: flex; align-items: center; justify-content: center;
          font-size: 12px; font-weight: 700; flex-shrink: 0;
        }
        .brokers-step-title { font-size: 13px; font-weight: 600; margin-bottom: 3px; }
        .brokers-step-body { font-size: 12px; color: var(--color-text-muted); line-height: 1.5; }

        /* Reuse sub-toast from Subscription */
        .sub-toast {
          position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
          z-index: 9999; padding: 10px 20px; border-radius: 8px;
          font-size: 14px; font-weight: 500;
          animation: toastIn .2s ease;
        }
        .sub-toast-ok { background: var(--color-success); color: #fff; }
        .sub-toast-err { background: var(--color-danger); color: #fff; }
        @keyframes toastIn { from { opacity:0; transform: translateX(-50%) translateY(-8px); } to { opacity:1; transform: translateX(-50%) translateY(0); } }

        @media (max-width: 600px) {
          .brokers-grid { grid-template-columns: 1fr; }
          .brokers-how-steps { grid-template-columns: 1fr; }
        }
      `}</style>
    </div>
  )
}
