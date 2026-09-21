import celery_app


def test_critical_tasks_are_registered_and_scheduled_by_registered_name():
    registered = celery_app.celery_app.tasks
    assert "meta.sync_custom_audiences" in registered
    assert "credentials.check_expiring" in registered
    assert celery_app.celery_app.conf.beat_schedule["credential-expiry-check"]["task"] == "credentials.check_expiring"
