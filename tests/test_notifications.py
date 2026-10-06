from unittest.mock import MagicMock
from config.settings import settings
from services.notifications import NotificationService


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "NOTIFY_EMAIL", "receiver@example.test")
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_USER", "sender@example.test")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "test-only-password")
    monkeypatch.setattr(settings, "SMTP_SSL", False)
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)


def test_email_is_sent_only_after_smtp_accepts(monkeypatch):
    _configure(monkeypatch)
    server = MagicMock()
    server.send_message.return_value = {}
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value = server
    monkeypatch.setattr("services.notifications.smtplib.SMTP", smtp)
    assert NotificationService().notify_all("Alert", "Body", channels=["email"]) == {"email": "success"}
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("sender@example.test", "test-only-password")
    assert server.send_message.call_args.args[0]["To"] == "receiver@example.test"


def test_unconfigured_email_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert NotificationService().notify_all("Alert", "Body", channels=["email"]) == {"email": "disabled"}


def test_email_rejection_remains_failed(monkeypatch):
    _configure(monkeypatch)
    server = MagicMock()
    server.send_message.return_value = {"receiver@example.test": (550, b"Rejected")}
    smtp = MagicMock()
    smtp.return_value.__enter__.return_value = server
    monkeypatch.setattr("services.notifications.smtplib.SMTP", smtp)
    assert NotificationService().notify_all("Alert", "Body", channels=["email"])["email"].startswith("failed:")
