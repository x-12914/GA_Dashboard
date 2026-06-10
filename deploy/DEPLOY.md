# Deploying StoreBoost to your VPS (safely, alongside existing sites)

This deploys the app so it **cannot crash or interfere** with what's already
running:

- The app listens on **127.0.0.1 only** → not reachable from the internet
  directly; only Nginx talks to it.
- A **separate** Nginx file → your existing sites are never edited.
- **systemd memory/CPU caps** → if the app ever misbehaves, only the app is
  killed & restarted; your other services are untouched.
- Runs as a dedicated **non-root user**.

Run everything below over SSH on the VPS.

---

## Step 0 — Port (already confirmed)

Port **8500** is free on this VPS (in-use: 8000, 8050, 8060, 8080, 5432).
No changes needed — gunicorn binds to `127.0.0.1:8500`. To re-check anytime:

```bash
sudo ss -ltnp | grep ':8500' && echo "TAKEN - pick another" || echo "8500 free"
```

If you ever need to change it, edit it in **both**:
- `deploy/gunicorn_conf.py`  → `bind = "127.0.0.1:<port>"`
- `deploy/nginx-storeboost.conf` → `proxy_pass http://127.0.0.1:<port>;`

---

## Step 1 — Create a dedicated user and app directory

```bash
sudo useradd --system --create-home --home-dir /opt/storeboost --shell /usr/sbin/nologin storeboost
```

## Step 2 — Clone the repo onto the VPS

```bash
sudo apt install -y git
sudo git clone YOUR_REPO_URL /opt/storeboost
sudo chown -R storeboost:storeboost /opt/storeboost
```

> Private repo? Use an HTTPS URL with a personal access token, or add a deploy
> key. Public repo? The plain HTTPS clone URL works as-is.

## Step 3 — Python env + dependencies

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip
sudo -u storeboost python3 -m venv /opt/storeboost/.venv
sudo -u storeboost /opt/storeboost/.venv/bin/pip install --upgrade pip
sudo -u storeboost /opt/storeboost/.venv/bin/pip install -r /opt/storeboost/requirements.txt -r /opt/storeboost/requirements-prod.txt
```

## Step 4 — Configure `.env`

```bash
sudo -u storeboost cp /opt/storeboost/.env.example /opt/storeboost/.env
sudo -u storeboost nano /opt/storeboost/.env
```

Set at least:
```
USE_MOCK=true                 # keep true until your GA4 is connected
OPENAI_API_KEY=sk-...         # your OpenAI key (makes audits + emails smarter)
OPENAI_MODEL=gpt-4o-mini
PAGESPEED_API_KEY=            # optional: real mobile speed scores in audits
```

## Step 5 — Install & start the systemd service

```bash
sudo cp /opt/storeboost/deploy/storeboost.service /etc/systemd/system/storeboost.service
sudo systemctl daemon-reload
sudo systemctl enable --now storeboost
sudo systemctl status storeboost --no-pager
```

Verify it's answering locally (should print JSON):
```bash
curl -s http://127.0.0.1:8500/api/status
```

## Step 6 — Hook up Nginx (separate, non-destructive)

Pick your `server_name` and edit `deploy/nginx-storeboost.conf`:
- **DuckDNS** (you have this): point `storeboost.duckdns.org` to your VPS IP in
  the DuckDNS dashboard, then set `server_name storeboost.duckdns.org;`
- **nip.io** (zero setup): set `server_name YOUR_VPS_IP.nip.io;`
- **IP only**: set `server_name _;` and reach it at `http://YOUR_VPS_IP/`
  (only if no other site already uses the default server on port 80).

```bash
sudo cp /opt/storeboost/deploy/nginx-storeboost.conf /etc/nginx/sites-available/storeboost
sudo ln -s /etc/nginx/sites-available/storeboost /etc/nginx/sites-enabled/storeboost
sudo nginx -t          # MUST say "syntax is ok" — this checks ALL sites, so it
                       # also confirms we didn't break existing ones
sudo systemctl reload nginx
```

`nginx -t` failing means stop and fix before reloading — a reload only applies
if the test passed, so your existing sites stay up either way.

## Step 7 — HTTPS with certbot (recommended, you have it)

Only works with a real hostname (DuckDNS or nip.io), not a bare IP:

```bash
sudo certbot --nginx -d storeboost.duckdns.org
```

Certbot edits only our server block to add port 443 + auto-renewal.

---

## Updating later

```bash
cd /opt/storeboost
sudo -u storeboost git pull
sudo -u storeboost /opt/storeboost/.venv/bin/pip install -r requirements.txt -r requirements-prod.txt
sudo systemctl restart storeboost
```

## Handy commands

```bash
sudo systemctl status storeboost      # is it running?
sudo journalctl -u storeboost -f      # live logs
sudo systemctl restart storeboost     # restart
systemctl show storeboost -p MemoryCurrent   # current memory use vs the 768M cap
```

## Why this can't take down your box (recap)

| Risk | Mitigation |
|------|------------|
| App eats all RAM | `MemoryMax=768M` → only the app is killed & auto-restarted |
| App pegs the CPU | `CPUQuota=80%` leaves headroom for other services |
| App crashes | `Restart=always` brings it back in 5s |
| Exposed to attackers | binds to `127.0.0.1`; only Nginx is public |
| Breaks other sites | separate Nginx file; `nginx -t` gates every reload |
| Runs as root | dedicated `storeboost` system user, no shell |
