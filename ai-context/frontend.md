# Frontend Layer Deep-Dive

## Pages (11 routes)

| Path | Component | Primary Purpose |
|------|-----------|----------------|
| `/dashboard` | Dashboard.tsx | Option chain analysis with live data |
| `/strategy` | Strategy.tsx | Multi-leg strategy builder with payoff visualization |
| `/compare` | Compare.tsx | Side-by-side strategy comparison |
| `/positions` | Positions.tsx | Active positions monitoring |
| `/scalping` | Scalping.tsx | High-frequency trading interface |
| `/watchlists` | Watchlists.tsx | Symbol tracking and alerts |
| `/portfolios` | Portfolios.tsx | Portfolio management and P&L |
| `/saved` | Saved.tsx | Saved strategy templates |
| `/audit` | Audit.tsx | Order execution history |
| `/login` | Login.tsx | Fyers broker authentication |
| `/settings` | Settings.tsx | Application configuration |

## Core Components

### App.tsx
**Props**: None (root component)
**State**: `theme: 'dark'|'light'`, navigation state
**API Calls**: 
- `GET /api/system/status` → Status polling every 10s
**Features**: Theme toggling, navigation sidebar, system status monitoring

### CommandPalette.tsx  
**Props**: `{ toggleTheme: () => void }`
**State**: `open: boolean`, `q: string` (search query)
**Keyboard shortcuts**: 
- `Cmd+K` → Toggle palette
- `g d` → Navigate to dashboard
- `g s` → Navigate to strategy
- `Shift+T` → Toggle theme

## Analytical Components

### OptionChainTable.tsx
**Props**: `{ chain: Chain }`
**Features**: Strike-wise option data, OI/volume heatmaps, Greeks display
**Interactions**: Strike selection, order placement modals

### PayoffChart.tsx
**Props**: `{ legs: Leg[], spots: number[] }`
**Renders**: P&L curves using Recharts LineChart
**Calculations**: Profit/loss at expiry across spot price range

### GreeksHeatmap.tsx
**Props**: `{ chain: Chain }`
**Display**: Delta/Gamma/Theta/Vega in color-coded grid
**Scope**: ±5 strikes around ATM for readability
**Color mapping**: Green/red gradient for positive/negative values

### IVSmile.tsx
**Props**: `{ chain: Chain }`
**Visualization**: IV vs Strike using Recharts
**Data**: Both CE/PE implied volatility curves

### OIChart.tsx
**Props**: `{ chain: Chain }`
**Chart types**: Bar chart for OI, line for OI changes
**Metrics**: Total CE/PE open interest distribution

### PCRTimeSeries.tsx
**Props**: `{ symbol: string, days: number }`
**API**: `GET /api/analytics/pcr-history/{symbol}?days={days}`
**Display**: Put-Call ratio trend over time

### HedgeBuilder.tsx
**Props**: `{ underlying: string, chain: Chain }`
**API**: `POST /api/analytics/hedge` → Delta-neutral hedge suggestions
**Input**: Primary option, action (BUY/SELL), quantity
**Output**: Recommended hedge positions with Greeks

### OrderModal.tsx
**Props**: `{ symbol: string, onClose: () => void }`
**API**: 
- `POST /api/orders/place` → Execute order
- `GET /api/orders/margin` → Margin requirements
**Fields**: Order type, quantity, price, stop-loss

### SummaryStrip.tsx
**Props**: `{ chain: Chain }`
**Metrics**: PCR, Max Pain, ATM IV, OI changes
**Layout**: Horizontal strip with key market indicators

## API Integration

### Core API Client (api.ts)
```typescript
baseURL: process.env.VITE_API_BASE || 'http://localhost:8000'
timeout: 30000ms
```

### Type Definitions
```typescript
Strike = { strike: number, ce?: LegData, pe?: LegData }
LegData = { ltp: number, oi: number, oi_change: number, volume: number, iv: number, delta?: number, gamma?: number, theta?: number, vega?: number, symbol?: string }
ChainSummary = { pcr_oi: number, pcr_volume: number, max_pain: number, total_ce_oi: number, total_pe_oi: number, ce_oi_change: number, pe_oi_change: number, atm_strike: number, atm_iv: number }
Chain = { underlying: string, ltp: number, expiry: any, expiries?: { date: string, expiry: number }[], strikes: Strike[], summary: ChainSummary, bias: { bias: string, score: number, signals: string[] } }
```

## State Management

### Query Integration (@tanstack/react-query)
**System status**: `['system-status']` → 10s refetch interval
**Chain data**: `['chain', symbol, expiry]` → Real-time option data
**Positions**: `['positions']` → Portfolio tracking
**Strategies**: `['strategies']` → Saved strategy list

### Theme Management
**Storage**: localStorage persistence
**Values**: 'dark' | 'light'
**CSS**: data-theme attribute on documentElement

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| react | ^18.3.1 | Core framework |
| react-router-dom | ^6.27.0 | Client-side routing |
| @tanstack/react-query | ^5.59.16 | Server state management |
| axios | ^1.7.7 | HTTP client |
| recharts | ^2.13.0 | Chart visualizations |
| zustand | ^5.0.0 | Local state management |
| vite | ^5.4.10 | Build tool |
| typescript | ^5.6.3 | Type safety |

## Build Configuration
**Entry**: main.tsx → React.StrictMode + QueryClient + BrowserRouter
**Environment**: Vite with React plugin
**TypeScript**: Strict mode enabled
**Dev server**: HMR with fast refresh