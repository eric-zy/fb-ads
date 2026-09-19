from celery import Celery
import os

celery_app = Celery("fb_connector")
celery_app.conf.update(
    broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    task_serializer="json",
    accept_content=["json"],
    task_default_queue="connector_general",
    task_routes={
        "fb_connector.upload_media": {"queue": "connector_media"},
        "fb_connector.fetch_insights": {"queue": "connector_insights"},
        "fb_connector.create_campaign": {"queue": "connector_campaign"},
        "fb_connector.recover_stale_media_tasks": {"queue": "connector_maintenance"},
        "fb_connector.recover_stale_delivery_tasks": {"queue": "connector_maintenance"},
    },
    worker_prefetch_multiplier=1,
    task_track_started=True,
    include=["fb_connector.tasks"],
    beat_schedule={
        "recover-stale-media-tasks": {
            "task": "fb_connector.recover_stale_media_tasks",
            "schedule": 300,
        },
        "recover-stale-delivery-tasks": {
            "task": "fb_connector.recover_stale_delivery_tasks",
            "schedule": 300,
        },
    },
)
