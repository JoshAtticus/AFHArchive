"""
Gunicorn configuration file for AFHArchive production deployment
"""

import os
import multiprocessing
from decouple import config

# Server socket
bind = f"{config('GUNICORN_HOST', default='0.0.0.0')}:{config('GUNICORN_PORT', default='8000')}"
backlog = 2048

# Worker processes
workers = config('GUNICORN_WORKERS', default=multiprocessing.cpu_count() * 2 + 1, cast=int)
worker_class = config('GUNICORN_WORKER_CLASS', default='sync')
worker_connections = config('GUNICORN_WORKER_CONNECTIONS', default=1000, cast=int)
max_requests = config('GUNICORN_MAX_REQUESTS', default=1000, cast=int)
max_requests_jitter = config('GUNICORN_MAX_REQUESTS_JITTER', default=50, cast=int)
preload_app = config('GUNICORN_PRELOAD_APP', default=True, cast=bool)

# Timeouts
timeout = config('GUNICORN_TIMEOUT', default=30, cast=int)
keepalive = config('GUNICORN_KEEPALIVE', default=5, cast=int)

# Security
limit_request_line = config('GUNICORN_LIMIT_REQUEST_LINE', default=4094, cast=int)
limit_request_fields = config('GUNICORN_LIMIT_REQUEST_FIELDS', default=100, cast=int)
limit_request_field_size = config('GUNICORN_LIMIT_REQUEST_FIELD_SIZE', default=8190, cast=int)

# Logging
loglevel = config('GUNICORN_LOG_LEVEL', default='info')
accesslog = config('GUNICORN_ACCESS_LOG', default='-')  # stdout
errorlog = config('GUNICORN_ERROR_LOG', default='-')   # stderr
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = 'afharchive'

# Server mechanics
daemon = config('GUNICORN_DAEMON', default=False, cast=bool)
pidfile = config('GUNICORN_PIDFILE', default='/tmp/afharchive.pid')
user = config('GUNICORN_USER', default=None)
group = config('GUNICORN_GROUP', default=None)
tmp_upload_dir = None

# SSL (uncomment and configure if using HTTPS)
# keyfile = config('SSL_KEYFILE', default=None)
# certfile = config('SSL_CERTFILE', default=None)
# ssl_version = ssl.PROTOCOL_TLS
# ciphers = 'ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20:!aNULL:!MD5:!DSS'

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("AFHArchive server is ready. Accepting connections.")

def worker_int(worker):
    """Called just after a worker has been restarted (after receiving a SIGINT signal)."""
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    worker.log.info("Worker initialized")

def worker_abort(worker):
    """Called when a worker received the SIGABRT signal."""
    worker.log.info("Worker received SIGABRT signal")
