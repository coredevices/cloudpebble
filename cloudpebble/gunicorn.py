import multiprocessing
import os

worker_class = 'gevent'
workers = int(os.environ.get('WEB_CONCURRENCY', multiprocessing.cpu_count() * 2 + 1))
# Cap concurrent greenlets per worker. Long-lived SSE streams (ide.api.sse) each
# hold a greenlet for the life of the connection, so make the ceiling explicit
# and tunable rather than relying on gevent's default of 1000.
worker_connections = int(os.environ.get('WORKER_CONNECTIONS', 1000))
timeout = 120


def post_fork(server, worker):
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()
