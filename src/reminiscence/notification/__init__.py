"""Guardian email notification support."""

from reminiscence.notification.config import (
    NotificationConfig,
    NotificationConfigError,
    load_notification_config,
)
from reminiscence.notification.email_sender import (
    GuardianEmailError,
    SmtpGuardianEmailSender,
)

__all__ = [
    "GuardianEmailError",
    "NotificationConfig",
    "NotificationConfigError",
    "SmtpGuardianEmailSender",
    "load_notification_config",
]
