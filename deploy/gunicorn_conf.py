"""Gunicorn config for StoreBoost.

Binds to localhost ONLY — the app is never exposed to the internet directly;
Nginx is the only thing that talks to it. Workers and recycling are tuned to
keep memory flat so the app can never grow into the rest of the VPS.
"""

# Reachable only from the same machine (Nginx proxies to this). Change the port
# if 8500 is taken on your box (see DEPLOY.md port check).
bind = "127.0.0.1:8500"

# Keep it small — this is an early-stage app sharing a box with other services.
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"

# The audit endpoint makes outbound calls (store fetch + PageSpeed), so allow
# a generous request timeout but recycle workers regularly to release memory.
timeout = 60
graceful_timeout = 30
max_requests = 500
max_requests_jitter = 50

loglevel = "info"
accesslog = "-"
errorlog = "-"
