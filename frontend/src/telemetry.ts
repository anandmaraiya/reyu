/**
 * PostHog telemetry — thin wrapper.
 *
 * All event names live here as a const enum so grep-ability is high and
 * mistyped names are caught by TS. Matches the schema in
 * docs/PRODUCT_SPEC.md §3 (Telemetry Events column).
 *
 * Silent when VITE_POSTHOG_KEY is unset — safe for local dev / preview
 * builds without polluting the prod project with test events.
 */
import posthog from 'posthog-js'

let initialised = false

export function initTelemetry() {
  if (initialised) return
  const key = import.meta.env.VITE_POSTHOG_KEY
  const host = import.meta.env.VITE_POSTHOG_HOST || 'https://us.i.posthog.com'
  if (!key) {
    console.info('[telemetry] disabled — VITE_POSTHOG_KEY not set')
    return
  }
  posthog.init(key, {
    api_host: host,
    person_profiles: 'identified_only',
    capture_pageview: true,
    capture_pageleave: true,
    autocapture: false,   // we fire explicit events; avoids noise
  })
  initialised = true
}

export function identifyUser(u: { id: string; email: string; tier: string }) {
  if (!initialised) return
  posthog.identify(u.id, {
    email: u.email,
    tier: u.tier,
  })
}

export function resetTelemetry() {
  if (!initialised) return
  posthog.reset()
}

/** Event names — keep in sync with docs/PRODUCT_SPEC.md §3. */
export const Events = {
  // P-01 Chat
  ChatMsgSent:              'chat_msg_sent',
  ChatNudgeClick:           'chat_nudge_click',
  StrategyCreatedFromChat:  'strategy_created_from_chat',

  // P-02 Dashboard
  ChainViewed:              'chain_viewed',
  ChainExported:            'chain_exported',
  SymbolSwitched:           'symbol_switched',

  // P-03 / P-04 Strategies
  StrategyCreated:          'strategy_created',
  StrategyPromoted:         'strategy_promoted',
  StrategyHalted:           'strategy_halted',
  StrategyDeleted:          'strategy_deleted',
  StrategyViewed:           'strategy_viewed',
  RunKilled:                'run_killed',
  SpecVersioned:            'spec_versioned',

  // P-05 Compare
  StrategiesCompared:       'strategies_compared',
  CompareExported:          'compare_exported',

  // P-06 Backtest
  BacktestStarted:          'backtest_started',
  BacktestCompleted:        'backtest_completed',
  BacktestFailed:           'backtest_failed',

  // P-07 Positions
  PositionViewed:           'position_viewed',
  PositionExited:           'position_exited',
  PositionHedged:           'position_hedged',

  // P-08 Portfolios
  PortfolioCreated:         'portfolio_created',
  PortfolioEdited:          'portfolio_edited',
  PortfolioDeleted:         'portfolio_deleted',

  // P-09 Scalping
  SignalViewed:             'signal_viewed',
  SignalToStrategy:         'signal_to_strategy',

  // P-10 Orders
  OrderViewed:              'order_viewed',
  OrderExported:            'order_exported',

  // P-11 Brokers
  BrokerConnected:          'broker_connected',
  BrokerDisconnected:       'broker_disconnected',

  // P-12 RL
  RlRecViewed:              'rl_rec_viewed',
  RlTradeOpenedFromRec:     'rl_trade_opened_from_rec',

  // P-13 Settings
  SettingsVisited:          'settings_visited',
  PasswordChanged:          'password_changed',
  ApiKeyCreated:            'apikey_created',
  ForgotPasswordRequested:  'forgot_password_requested',
  PasswordReset:            'password_reset',

  // P-14 Subscription
  PlanViewed:               'plan_viewed',
  PlanUpgraded:             'plan_upgraded',
  PlanCancelled:            'plan_cancelled',

  // P-15 Compare (cross-symbol)
  CompareSymbolAdded:       'compare_symbol_added',

  // P-16 Admin
  AdminTestRun:             'admin_test_run',
  AdminJobRun:              'admin_job_run',
  AdminRegimeForced:        'admin_regime_forced',

  // P-17 Onboarding
  OnboardStarted:           'onboard_started',
  OnboardStepCompleted:     'onboard_step_completed',
  OnboardCompleted:         'onboard_completed',

  // P-18 Journal
  JournalViewed:            'journal_viewed',
  JournalExported:          'journal_exported',

  // P-19 Catalog
  CatalogViewed:            'catalog_viewed',
  StrategyCopied:           'strategy_copied',

  // Auth
  LoginSucceeded:           'login_succeeded',
  LoginFailed:              'login_failed',
  Registered:               'registered',
} as const

export type EventName = typeof Events[keyof typeof Events]

/** Fire a telemetry event. No-ops when telemetry isn't initialised. */
export function track(event: EventName, properties?: Record<string, any>) {
  if (!initialised) return
  posthog.capture(event, properties)
}
