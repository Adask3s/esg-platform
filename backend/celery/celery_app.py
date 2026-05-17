from __future__ import annotations
import os
import ssl
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TIMEZONE = os.getenv("CELERY_TIMEZONE", "Europe/Warsaw")

# TLS dla zarzadzanych Redisow (Upstash, AWS ElastiCache TLS) -- rediss://
_use_tls = REDIS_URL.startswith("rediss://") or CELERY_RESULT_BACKEND.startswith("rediss://")
_ssl_opts = {"ssl_cert_reqs": ssl.CERT_NONE} if _use_tls else None

celery_app = Celery(
    "etl_backend",
    broker=REDIS_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "backend.celery.tasks",
        "backend.celery.embedding_tasks",
        "backend.celery.report_tasks",
    ],
)

if _ssl_opts is not None:
    celery_app.conf.broker_use_ssl = _ssl_opts
    celery_app.conf.redis_backend_use_ssl = _ssl_opts

celery_app.conf.update(
    # Serializacja
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=CELERY_TIMEZONE,
    enable_utc=True,

    # Śledzenie stanu
    task_track_started=True,
    worker_send_task_events=True,
    task_send_sent_event=True,

    # Wyniki / broker
    result_expires=86400,                      # TTL wyników w Redis (24 h)
    result_extended=True,                      # zapisuj też name/args w meta AsyncResult
    broker_connection_retry_on_startup=True,

    # Niezawodność wykonywania
    task_acks_late=True,                       # ack dopiero po ukończeniu -> re-queue gdy worker umrze
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,              # długie taski: 1 na raz per slot

    # Domyślne limity czasu (mogą być nadpisywane per-task)
    task_soft_time_limit=600,                  # 10 min soft
    task_time_limit=900,                       # 15 min hard

    # Routing -> dedykowane kolejki
    task_default_queue="default",
    task_routes={
        "backend.parse_and_store":                  {"queue": "parsing"},
        "backend.parse_and_store_to_knowledge":     {"queue": "parsing"},
        "backend.process_user_document":            {"queue": "parsing"},
        "backend.process_knowledge_document_full":  {"queue": "parsing"},
        "backend.ingest_chunk_file":                {"queue": "parsing"},
        "backend.ingest_chunk_url":                 {"queue": "parsing"},
        "backend.generate_embeddings_for_document": {"queue": "embeddings"},
        "backend.generate_embeddings_for_tag":      {"queue": "embeddings"},
        "backend.generate_embeddings_for_all":      {"queue": "embeddings_bulk"},
        "backend.generate_report":                  {"queue": "llm"},
    },
)

__all__ = ["celery_app"]
