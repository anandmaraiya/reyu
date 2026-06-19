# Fyers Headless Authentication (Linux VM)

Fyers requires a browser OAuth flow. On a headless Linux VM, do this once daily:

## One-time setup

1. Set `REYU_TOKEN_SECRET` in your `.env`:
   ```
   REYU_TOKEN_SECRET=some-strong-random-string
   ```

2. Register your VM's IP as an allowed redirect URI in the Fyers developer console:
   `http://<VM_IP>:8000/api/auth/callback`

## Daily token refresh (two options)

### Option A — Browser on any machine
1. Open `http://<VM_IP>:8000/api/auth/login` in a browser
2. Log in to Fyers normally
3. You'll be redirected back — token is auto-saved in Redis ✓

### Option B — Fully automated (cron + Selenium on a CI machine)
```bash
# Run on a machine WITH a browser (not the VM):
python3 deploy/fyers_renew_token.py --host http://<VM_IP>:8000 --secret <REYU_TOKEN_SECRET>
```

### Option C — Manual token paste
1. Get a token by completing OAuth on any browser
2. POST it to the VM:
   ```bash
   curl -X POST http://<VM_IP>:8000/api/auth/set-token \
        -H 'Content-Type: application/json' \
        -d '{"access_token":"<token>","secret":"<REYU_TOKEN_SECRET>"}'
   ```

## Cron job for daily auto-refresh (Option A flow via headless Chrome)

Add to crontab (`crontab -e`):
```
# Refresh Fyers token every day at 8:45 AM IST (3:15 UTC)
15 3 * * 1-5 /opt/reyu/deploy/refresh_token.sh >> /var/log/reyu-token.log 2>&1
```

`deploy/refresh_token.sh`:
```bash
#!/usr/bin/env bash
# Requires: google-chrome-stable + chromedriver or playwright
# Install: pip install playwright && playwright install chromium
cd /opt/reyu
python3 deploy/fyers_renew_token.py \
    --host http://localhost:8000 \
    --secret "$REYU_TOKEN_SECRET" \
    --fyers-user "$FYERS_USER" \
    --fyers-pass "$FYERS_PASS" \
    --fyers-pin  "$FYERS_PIN"
```

## Verify token is live

```bash
curl http://<VM_IP>:8000/api/auth/status
# {"authenticated": true}

curl http://<VM_IP>:8000/api/market/ticks
# {"ticks": [...], "demo": false}
```
