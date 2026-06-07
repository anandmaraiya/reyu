# NSE F&O Historical Options Data Sources

## Overview

This document catalogs all known sources for historical F&O options data
for Indian markets (NSE/BSE), with instructions for ingesting into the
`option_intraday` hypertable.

## Data Sources

### FREE Sources

#### 1. TradingTuitions (NIFTY + BANKNIFTY only)
- **URL**: https://tradingtuitions.com/historical-options-data-free-download-intraday-1-minute/
- **Coverage**: Jan 2021 to ~present (updates paused due to SEBI regulations)
- **Granularity**: 1-minute OHLCV + OI
- **Symbols**: NIFTY (weekly + monthly), BANKNIFTY (weekly + monthly)
- **Format**: CSV files, one per strike per expiry per day
- **Columns**: Date, Time, Open, High, Low, Close, Volume, OI
- **How to get**: Enter email on the page → receive Google Drive link
- **Google Drive folder**: https://drive.google.com/drive/folders/10pmUnHbT01rORkofkTzl1hB1eNtPZrOR
- **Ingest command**:
  ```bash
  # Download
  python scripts/gdown_folder.py --folder-id 10pmUnHbT01rORkofkTzl1hB1eNtPZrOR --output /data/tt_options
  # Ingest
  curl -X POST "http://localhost:8000/api/data/intraday/ingest-folder?path=/data/tt_options&source=tradingtuitions"
  ```

#### 2. Google Drive — debaonline4u/NSE-Data (Stocks + Indices)
- **URL**: https://github.com/debaonline4u/NSE-Data
- **Google Drive**: https://drive.google.com/drive/folders/1zThEsziq0f4QpbdPyB3Z8F1pcKifmT3x
- **Coverage**: Varies by symbol (2015-2024 for indices)
- **Granularity**: 1min, 3min, 5min, 10min, 15min, 30min, 60min, Daily
- **Symbols**: NIFTY 50, BANKNIFTY, Nifty Next 50 stocks (100+ symbols)
- **Format**: CSV with OHLCV
- **Note**: This is primarily spot/index data, NOT options chain data
- **Use case**: Spot price history for backtesting (complements options data)

#### 3. NSE Bhavcopy (EOD — already integrated)
- **URL**: https://archives.nseindia.com/content/historical/DERIVATIVES/
- **Coverage**: 2011+ (NIFTY), 2016+ (BANKNIFTY weeklies)
- **Granularity**: Daily OHLC + OI + Volume per strike
- **Ingester**: `backend/app/data/bhavcopy.py` (already running)
- **Table**: `option_eod`

#### 4. StocksRin (Free option chain history)
- **URL**: https://stocksrin.com/
- **Coverage**: 2021+
- **Granularity**: Daily option chain snapshots
- **Symbols**: NIFTY, BANKNIFTY, F&O stocks
- **Format**: Web UI with CSV export
- **Note**: Manual download per day; no bulk API

### PAID / API Sources

#### 5. ICICI Breeze API (Recommended for all F&O)
- **PyPI**: `pip install breeze-connect breeze-historical-options`
- **GitHub**: https://github.com/madmay247/breeze-historical-options
- **Coverage**: All F&O stocks + indices, 1-second to daily
- **Cost**: Free (requires ICICI Direct account)
- **Setup**:
  1. Open free ICICI Direct account: https://secure.icicidirect.com/
  2. Get API key from ICICI Direct developer portal
  3. Create `cred.yml` in `backend/`:
     ```yaml
     api_key: "your_api_key"
     api_secret: "your_api_secret"
     username: "your_client_id"
     totp_key: "your_totp_secret"
     ```
  4. Fetch data:
     ```bash
     curl -X POST "http://localhost:8000/api/data/intraday/breeze/fetch?scrip=NIFTY&expiry=2024-12-25&trade_date=2024-12-20"
     ```
- **Scrip codes**: NIFTY, CNXBAN (BankNifty), NIFFIN (FinNifty), NIFMID (MidcapNifty)
- **For stocks**: Use NSE symbol name (e.g., RELIANCE, HDFCBANK)

#### 6. Zerodha Kite Connect
- **URL**: https://kite.trade/
- **Cost**: ~₹2,000/month
- **Coverage**: 1-min historical for all instruments
- **Limitation**: Need instrument tokens; options data only ~2 years back
- **Note**: Good for spot/futures; options historical is limited

#### 7. Stolo (Paid, minute-level)
- **URL**: https://stolo.in/solutions/nse-spots-futures-options-historical-data/
- **Coverage**: Full NSE F&O segment, minute-by-minute
- **Cost**: Paid (contact for pricing)
- **Format**: API + bulk download

### Kaggle Datasets

#### 8. NSE Future and Options Dataset 3M
- **URL**: https://www.kaggle.com/datasets/sunnysai12345/nse-future-and-options-dataset-3m
- **Coverage**: 3 months of NSE F&O data
- **Format**: CSV (~150k rows)
- **Use case**: Quick backtesting experiments

#### 9. Nifty 50 Index Minute Data (2015-2024)
- **URL**: https://www.kaggle.com/datasets/debashis74017/nifty-50-minute-data
- **Coverage**: Jan 2015 to Aug 2024
- **Granularity**: 1-minute OHLC
- **Note**: Index spot data only, not options

## Database Schema

### `option_intraday` hypertable
| Column | Type | Description |
|--------|------|-------------|
| ts | TIMESTAMP | Minute timestamp (PK) |
| underlying | VARCHAR | e.g. NSE:NIFTY50-INDEX (PK) |
| expiry | TIMESTAMP | Option expiry (PK) |
| strike | FLOAT | Strike price (PK) |
| option_type | VARCHAR | CE or PE (PK) |
| open | FLOAT | Open price |
| high | FLOAT | High price |
| low | FLOAT | Low price |
| close | FLOAT | Close price |
| volume | BIGINT | Traded volume |
| oi | BIGINT | Open interest |
| oi_change | BIGINT | OI change |
| source | VARCHAR | Data source tag |

**Hypertable chunk interval**: 7 days
**Retention recommendation**: 90 days for raw intraday (aggregate to EOD for long-term)

## Recommended Ingestion Strategy

### Phase 1: Backfill indices (this week)
1. Download TradingTuitions Google Drive folder → ingest all NIFTY/BANKNIFTY CSVs
2. Set up Breeze API credentials → backfill NIFTY + BANKNIFTY for 2024
3. Cross-validate: compare Breeze vs TradingTuitions for overlapping dates

### Phase 2: Backfill F&O stocks (next week)
1. Use Breeze API to backfill top-30 F&O stocks (RELIANCE, HDFCBANK, etc.)
2. Focus on nearest expiry contracts (weekly + monthly)
3. Strike range: ATM ± 20 strikes

### Phase 3: Ongoing
1. Live `option_strike_snapshot` (already running since Jun 6) accumulates real intraday data
2. After 30+ days, switch RL backfill to real premiums (NU-2)
3. Daily Bhavcopy EOD pull continues for long-term EOD history

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/data/intraday/status` | GET | Coverage summary |
| `/api/data/intraday/ingest-csv` | POST | Ingest single CSV file |
| `/api/data/intraday/ingest-folder` | POST | Ingest all CSVs from folder |
| `/api/data/intraday/breeze/fetch` | POST | Fetch one day via Breeze |
| `/api/data/intraday/breeze/backfill` | POST | Multi-day Breeze backfill |

## Helper Scripts

| Script | Description |
|--------|-------------|
| `scripts/gdown_folder.py` | Download Google Drive folders |
