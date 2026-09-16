from celery import Celery
import os

celery_app = Celery("fb_connector")
celery_app.conf.update(
    broker_url=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1"),
    task_serializer="json",
    accept_content=["json"],
    include=["fb_connector.tasks"],
)
