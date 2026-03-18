from __future__ import annotations

import logging
import random
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import certifi

from app.config import (
    ADMIN_EMAIL,
    SMTP_FROM_EMAIL,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_TLS,
)

logger = logging.getLogger(__name__)


@dataclass
class OTPRecord:
    code: str
    expires_at: datetime


class AdminOTPService:
    def __init__(self) -> None:
        self._records: dict[str, OTPRecord] = {}

    def issue_code(self, email: str) -> None:
        normalized_email = email.strip().lower()
        if ADMIN_EMAIL and normalized_email != ADMIN_EMAIL.strip().lower():
            raise ValueError("That email is not authorized for admin access.")
        if not SMTP_HOST or not SMTP_FROM_EMAIL:
            raise ValueError("SMTP settings are incomplete. Set SMTP_HOST and SMTP_FROM_EMAIL first.")

        code = f"{random.randint(0, 999999):06d}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        self._records[normalized_email] = OTPRecord(code=code, expires_at=expires_at)
        self._send_email(normalized_email, code)
        logger.info("Issued OTP for %s", normalized_email)

    def verify_code(self, email: str, code: str) -> bool:
        normalized_email = email.strip().lower()
        record = self._records.get(normalized_email)
        if not record:
            return False
        if datetime.now(timezone.utc) > record.expires_at:
            self._records.pop(normalized_email, None)
            return False
        if record.code != code.strip():
            return False
        self._records.pop(normalized_email, None)
        return True

    def _send_email(self, email: str, code: str) -> None:
        message = EmailMessage()
        message["Subject"] = "Job Search Agent admin OTP"
        message["From"] = SMTP_FROM_EMAIL
        message["To"] = email
        message.set_content(
            "Your Job Search Agent admin login code is "
            f"{code}. It expires in 10 minutes."
        )

        context = ssl.create_default_context(cafile=certifi.where())
        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
                server.starttls(context=context)
                if SMTP_USERNAME:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(message)
            return

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20, context=context) as server:
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)


otp_service = AdminOTPService()
