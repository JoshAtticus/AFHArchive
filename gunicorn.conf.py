"""
Simple Gunicorn configuration file for AFHArchive
This version uses only environment variables and doesn't require python-decouple
"""

import os
import multiprocessing

# Server socket
bind = f"{os.getenv('GUNICORN_HOST', '0.0.0.0')}:{os.getenv('GUNICORN_PORT', '8000')}"

# Worker processes
# Use 1 worker to support Socket.IO without Redis/RabbitMQ
workers = 1
worker_class = os.getenv('GUNICORN_WORKER_CLASS', 'geventwebsocket.gunicorn.workers.GeventWebSocketWorker')
worker_connections = int(os.getenv('GUNICORN_WORKER_CONNECTIONS', '1000'))

# Performance tuning
max_requests = int(os.getenv('GUNICORN_MAX_REQUESTS', '1000'))
max_requests_jitter = int(os.getenv('GUNICORN_MAX_REQUESTS_JITTER', '50'))
preload_app = os.getenv('GUNICORN_PRELOAD_APP', 'True').lower() in ('true', '1', 'yes')

# Timeouts
timeout = int(os.getenv('GUNICORN_TIMEOUT', '300'))  # Increased for large file downloads
keepalive = int(os.getenv('GUNICORN_KEEPALIVE', '30'))

# Logging
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'debug')
accesslog = os.getenv('GUNICORN_ACCESS_LOG', '-')  # stdout
errorlog = os.getenv('GUNICORN_ERROR_LOG', '-')   # stderr
capture_output = True # Capture stdout/stderr from the app

# Process naming
proc_name = 'afharchive'

# Basic security limits
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Daemon mode (usually False for modern deployments)
daemon = False
pidfile = os.getenv('GUNICORN_PIDFILE', '/tmp/afharchive.pid')

# User and group (set these if running as root)
user = os.getenv('GUNICORN_USER')
group = os.getenv('GUNICORN_GROUP')

def when_ready(server):
    """Called just after the server is started."""
    server.log.info("AFHArchive server is ready. Accepting connections.")

def worker_int(worker):
    """Called when worker receives INT or QUIT signal."""
    worker.log.info("Worker received INT or QUIT signal")

def pre_fork(server, worker):
    """Called just before a worker is forked."""
    server.log.info("Worker spawned (pid: %s)", worker.pid)

def post_worker_init(worker):
    """Called just after a worker has initialized the application."""
    worker.log.info("Worker initialized")
