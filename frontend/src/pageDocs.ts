/**
 * pageDocs — content for the help drawer on each page.
 *
 * Add a new page: add a key here, wire `<PageHelp pageId="..." />`
 * at the top of that page. Content stays grep-able + version-controlled.
 *
 * Keep the tone practical: what a first-time user needs to know to
 * get value out of this page in under a minute.
 */

export type PageDoc = {
  title: string
  subtitle: string
  what: string
  actions?: { name: string; detail: string }[]
  tips?: string[]
  blocked?: string[]
}

export const pageDocs = {
  chat: {
    title: 'Reyu AI',
    subtitle: 'Your options-trading copilot',
    what: `Ask Reyu about the current market, a specific chain, a strategy you're considering, or general options concepts. Reyu reads live data (option chain, bias, regime) and turns it into plain English.`,
    actions: [
      { name: 'Ask', detail: 'Type any question. Try "What's the mood on NIFTY today?" or "Explain iron condor to me".' },
      { name: 'Nudges', detail: 'The chips above the input suggest what to ask next based on today's data.' },
      { name: 'Build', detail: 'Ask Reyu to draft a strategy — it creates a DRAFT you can review in /strategies.' },
    ],
    tips: [
      'Anonymous users get 5 messages/day. Sign in for 25/day (Free) or 500/day (Pro).',
      'Reyu never places live orders from chat — every action needs your explicit confirmation on the trading page.',
    ],
  },

  charts: {
    title: 'Charts',
    subtitle: 'Intelligent option-chain terminal',
    what: `Live option chain for any NSE F&O symbol with AI-driven bias, PCR + max-pain interpretation, and today's suggested regime. The top intelligence bar tells you what the platform would do right now; the chain below is the raw data behind it.`,
    actions: [
      { name: 'Switch symbol', detail: 'Click any ticker chip (NIFTY, BANKNIFTY, RELIANCE, etc.) at the top toolbar.' },
      { name: 'Regime pill', detail: 'Top of page — persistent hint on TREND UP / TREND DOWN / SIDEWAYS / FLAT based on today's PCR + momentum.' },
      { name: 'AI Bias tile', detail: 'The BULL/BEAR/RANGE reading with the top data signal explaining why.' },
      { name: 'Insights', detail: 'Three auto-generated cards: largest OI shift, max-pain distance, unusual writing.' },
      { name: 'Quick actions', detail: '"Ask Reyu about this chain" prefills a query; "Build a strategy" jumps to the builder with the current symbol.' },
      { name: 'Chain drill', detail: 'Scroll down: OI heatmap, IV smile, PCR time-series, and the full strike-by-strike chain.' },
    ],
    tips: [
      'Data updates every 60 seconds during market hours (9:15 AM to 3:30 PM IST).',
      'Outside market hours, you see the last snapshot from the day.',
      'The regime pill matches the paper-live "Regime Router" strategy — same rules, same code.',
    ],
  },

  journal: {
    title: 'Journal',
    subtitle: 'Your P&L across all trades',
    what: `Aggregated P&L view for every trade you've placed (or the platform placed on your behalf) — paper and live. Weekly, monthly, and per-trade drilldown. This is your "how am I doing?" dashboard.`,
    actions: [
      { name: 'Range', detail: '30d / 90d / 1y — changes the aggregation window for KPIs, chart, and monthly buckets.' },
      { name: 'Mode filter', detail: 'All / Paper / Live — toggle between the two trading modes.' },
      { name: 'KPI tiles', detail: 'Total P&L, Win Rate, Trades (with W/L split + open count), Avg P&L per trade, Best day, Worst day.' },
      { name: 'Daily chart', detail: 'Bar chart of the last 30 days — green = profitable day, red = losing day. Hover for details.' },
      { name: 'Monthly', detail: 'Table with per-month P&L + W/L breakdown for the last 12 months.' },
      { name: 'Export CSV', detail: 'Download every trade in the current range. Useful for tax filing or external analysis.' },
    ],
    tips: [
      'A win/loss is measured on net P&L (gross minus fees). Open trades don\'t count toward WR until they close.',
      'The platform-shared Regime Router paper trades are included by default — filter to your own strategies via the Saved page.',
    ],
    blocked: [
      'You can\'t delete a closed-trade record — the journal is append-only for audit purposes.',
    ],
  },

  positions: {
    title: 'Positions',
    subtitle: 'Open trades with live P&L',
    what: `Every open leg from your strategies + broker positions, grouped by underlying. Live LTP + unrealised P&L via Fyers quotes, updated every 15 seconds. This is where you exit.`,
    actions: [
      { name: 'Exit leg', detail: 'Close a single position. Dry-run first to validate; LIVE mode places a market order.' },
      { name: 'Exit group', detail: 'Close every leg under one underlying (e.g. all NIFTY positions).' },
      { name: 'Flatten all', detail: 'Nuclear option — exits every open position. Requires typed "FLATTEN-ALL" confirmation.' },
      { name: 'Payoff chart', detail: 'Each group shows a live payoff diagram at expiry so you can see where P&L flips.' },
    ],
    tips: [
      'Dry-run is default — always. You have to explicitly uncheck it to send LIVE orders.',
      'LIVE exits are irreversible once fills come back from the broker. Every LIVE exit shows preflight checks (margin, lot size, auth) before firing.',
      'Unrealised P&L is a snapshot — it moves as prices tick. Realised P&L only lands when the position closes.',
    ],
    blocked: [
      'You can\'t modify a position\'s size in place — instead, exit some legs and open new ones.',
      'Manual overrides to auto-managed strategy positions are logged and audited.',
    ],
  },

  strategies: {
    title: 'Saved Strategies',
    subtitle: 'Your strategy library',
    what: `Every strategy you've created, copied from the catalog, or built via chat. Backtest, tweak, promote to paper-live (Pro+) or live (Algo). Each edit creates a new version — old runs stay linked to their version so lineage is preserved.`,
    actions: [
      { name: 'Create', detail: 'From scratch: fill in the spec form. Or copy from Catalog / build via Chat.' },
      { name: 'Backtest', detail: 'Run against historical data. Both quick (last 90 days) and deep (multi-year Bhavcopy) modes.' },
      { name: 'Publish', detail: 'Make your strategy public — appears in Catalog. Others can copy it. Un-publish anytime.' },
      { name: 'Promote', detail: 'DRAFT → PAPER_LIVE lets the platform paper-trade it. PAPER_LIVE → LIVE (Algo only) sends real orders.' },
      { name: 'Halt', detail: 'Stop a paper/live run mid-flight. Open positions remain — close them from Positions.' },
      { name: 'Duplicate', detail: 'Copy your own strategy to iterate without breaking existing runs.' },
    ],
    tips: [
      'Publishing shares only the spec — not your P&L, trade history, or personal info.',
      'PAPER_LIVE promotion needs Pro tier. LIVE promotion needs Algo tier + Fyers connected + margin validator PASS.',
    ],
  },

  catalog: {
    title: 'Strategy Catalog',
    subtitle: 'Community-published strategies',
    what: `Browse strategies published by other Reyu users. Copy one to your account to backtest, tweak, and promote at your own pace. The copy is fully yours — subsequent edits by the original author don't touch your version.`,
    actions: [
      { name: 'Sort', detail: 'Recent (newest first) or Most Copied (leaderboard).' },
      { name: 'Copy', detail: 'Duplicates the strategy into your Saved list as DRAFT. Auth required — anon users get a login prompt.' },
      { name: 'Preview', detail: 'Each card shows kind, underlying, TP/SL brackets so you know the shape before copying.' },
    ],
    tips: [
      'Copies are frozen at the source\'s current version. Publish updates don\'t change your copy.',
      'Higher copies_count doesn\'t mean higher returns — it means people find the strategy interesting enough to look at.',
      'Test any copied strategy in the backtest before promoting to paper or live.',
    ],
  },

  onboarding: {
    title: 'Onboarding',
    subtitle: 'First-run setup',
    what: `Four quick steps to get you productive: pick your trader type, connect your broker, see the platform's canonical strategy, and open the dashboard. The whole flow takes about 3 minutes and only shows once per account.`,
    actions: [
      { name: 'Retail / HNI', detail: 'Pick the tier that matches how you trade. This tailors the UI + default limits.' },
      { name: 'Connect Fyers', detail: 'OAuth flow — you sign in on Fyers\' page and get redirected back automatically.' },
      { name: 'Backtest preview', detail: 'See the regime router\'s 6-year performance so you know what the platform runs.' },
      { name: 'Finish', detail: 'Marks you onboarded — you won\'t see this flow again on subsequent logins.' },
    ],
    tips: [
      'You can skip broker connect and still browse — the platform falls back to a demo view without live data.',
      'Progress is saved after each step, so a mid-flow refresh resumes where you left off.',
    ],
  },

  brokers: {
    title: 'Brokers',
    subtitle: 'Broker connections',
    what: `Manage which broker accounts are linked to Reyu. Currently supports Fyers (via OAuth). Zerodha + Upstox coming Phase 2.`,
    actions: [
      { name: 'Connect', detail: 'Kicks off broker\'s OAuth flow. You sign in there, get redirected back with a token stored securely.' },
      { name: 'Reconnect', detail: 'Fyers tokens expire daily (24h TTL). Re-auth each morning before the market opens.' },
      { name: 'Disconnect', detail: 'Removes the token. Requires typed broker-name confirmation to prevent accidents.' },
    ],
    tips: [
      'Disconnecting immediately halts any live or paper-live strategies from opening new trades.',
      'Open positions remain in your broker account after disconnect — you\'ll just lose real-time P&L until you reconnect.',
    ],
    blocked: [
      'You can\'t connect multiple accounts of the same broker (yet).',
    ],
  },

  settings: {
    title: 'Settings',
    subtitle: 'Account + preferences',
    what: `Change password, toggle theme, re-authenticate Fyers, manage API keys for B2B use, configure webhook notifications.`,
    actions: [
      { name: 'Change password', detail: 'Requires your current password. Invalidates all other sessions.' },
      { name: 'Re-auth Fyers', detail: 'Same as the Brokers page — kicks off the OAuth flow.' },
      { name: 'API keys', detail: 'Create keys for programmatic access. Rate-limited by tier (Free 5rps, Pro 20rps, Algo 100rps).' },
      { name: 'Webhooks', detail: 'Register a URL to receive trade + P&L events as JSON POSTs.' },
      { name: 'Theme', detail: 'Light or dark. Persisted per-browser.' },
    ],
    tips: [
      'API keys are shown once at creation — copy them immediately. We hash and can\'t recover them.',
      'Webhook payloads are signed with HMAC-SHA256 using your API key\'s shared secret.',
    ],
  },

  rl: {
    title: 'RL Engine',
    subtitle: 'Reinforcement-learning trading',
    what: `Inspect the platform's RL contextual bandit — its current policy weights, historical trades, and today's top recommendations. Requires Algo tier to view.`,
    actions: [
      { name: 'Policy', detail: 'See the learned weights per feature. Interpretable — larger = more influence on the action.' },
      { name: 'Trades', detail: 'Every trade the bandit has taken, with entry features + reward for training feedback.' },
      { name: 'Recommendations', detail: 'Live top-conviction plays across the F&O universe. Refreshes every 60s (cached).' },
      { name: 'Toggle', detail: 'Enable/disable the bandit. Disabled = no new trades, existing ones still get managed to close.' },
    ],
    tips: [
      'The RL bandit is superseded by the Regime Router paper-live for NIFTY — but the RL engine still runs for cross-symbol scanning.',
      'Recommendations don\'t auto-execute. Click one to open a strategy draft with the recommended legs.',
    ],
  },

  'admin-data': {
    title: 'Data Capture — Superadmin',
    subtitle: 'Pipeline ops + dataset dashboard',
    what: `Superadmin-only view of the data-capture pipeline: daily fill counts per table, scheduled job status, manual triggers, pipeline test, regime-router paper trades, and the audit log.`,
    actions: [
      { name: 'Pipeline test', detail: 'End-to-end probe: Fyers auth → history call → enumerate → tiny backfill → row delta. Use anytime you suspect data isn\'t landing.' },
      { name: 'Run job', detail: 'Fire any scheduled job on-demand. Skips the wait for the next cron.' },
      { name: 'Daily fills', detail: 'Rowcount per day per table (option_contract_1m, option_strike_snapshot, tick_1m, option_eod).' },
      { name: 'Regime router', detail: 'Live paper-trade card for the platform\'s canonical strategy. Force morning decision or EOD close.' },
      { name: 'Audit trail', detail: '30-day rolling log of money-path events. Export full year as CSV.' },
      { name: 'Scheduler', detail: '13 registered jobs + next firing time. Confirms cron is healthy.' },
    ],
    tips: [
      'This page auto-refreshes every 30-60s. No need to reload.',
      'Every superadmin action is itself audited — check the Audit card after clicking a manual trigger.',
    ],
  },
} as const

export type PageId = keyof typeof pageDocs
