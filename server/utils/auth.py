# Copyright 2024 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import emails
import structlog
from emails.template import JinjaTemplate
from jose import jwt

from server.settings import app_settings

logger = structlog.get_logger(__name__)


def send_email(
    email_to: str,
    subject_template: str = "",
    html_template: str = "",
    environment: Optional[Dict[str, Any]] = None,
) -> None:
    if environment is None:
        environment = {}
    assert app_settings.SMTP_ENABLED, "no provided configuration for email variables"  # noqa: S101
    message = emails.Message(
        subject=JinjaTemplate(subject_template),
        html=JinjaTemplate(html_template),
        mail_from=(app_settings.EMAILS_FROM_NAME, app_settings.EMAILS_FROM_EMAIL),
    )
    smtp_options = {"host": app_settings.SMTP_HOST, "port": app_settings.SMTP_PORT}
    if app_settings.SMTP_TLS:
        smtp_options["tls"] = True
    if app_settings.SMTP_USER:
        smtp_options["user"] = app_settings.SMTP_USER
    if app_settings.SMTP_PASSWORD:
        smtp_options["password"] = app_settings.SMTP_PASSWORD
    message.send(to=email_to, render=environment, smtp=smtp_options)
    response = message.send(to=app_settings.EMAILS_CC, render=environment, smtp=smtp_options)
    logger.info("Sending mail", result=response)


def send_test_email(email_to: str) -> None:
    project_name = app_settings.PROJECT_NAME
    subject = f"{project_name} - Test email"
    with open(Path(app_settings.EMAIL_TEMPLATES_DIR) / "test_email.html") as f:
        template_str = f.read()
    send_email(
        email_to=email_to,
        subject_template=subject,
        html_template=template_str,
        environment={"project_name": app_settings.PROJECT_NAME, "email": email_to},
    )


def send_reset_password_email(email_to: str, email: str, token: str) -> None:
    project_name = app_settings.PROJECT_NAME
    subject = f"{project_name} - Password recovery for user {email}"
    with open(Path(app_settings.EMAIL_TEMPLATES_DIR) / "reset_password.html") as f:
        template_str = f.read()
    server_host = app_settings.GUI_URI
    link = f"{server_host}/reset-password?token={token}"
    send_email(
        email_to=email_to,
        subject_template=subject,
        html_template=template_str,
        environment={
            "project_name": app_settings.PROJECT_NAME,
            "username": email,
            "email": email_to,
            "valid_hours": app_settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS,
            "link": link,
        },
    )


def send_download_link_email(email_to: str, link: str, shop_name: str) -> None:
    subject = f"{shop_name} - Product download"
    with open(Path(app_settings.EMAIL_TEMPLATES_DIR) / "send_download.html") as f:
        template_str = f.read()
    send_email(
        email_to=email_to,
        subject_template=subject,
        html_template=template_str,
        environment={
            "shop_name": shop_name,
            "email": email_to,
            "valid_days": "14",
            "link": link,
        },
    )


def send_new_account_email(email_to: str, username: str, password: str) -> None:
    project_name = app_settings.PROJECT_NAME
    subject = f"{project_name} - New account for user {username}"
    with open(Path(app_settings.EMAIL_TEMPLATES_DIR) / "new_account.html") as f:
        template_str = f.read()
    link = app_settings.SERVER_HOST
    send_email(
        email_to=email_to,
        subject_template=subject,
        html_template=template_str,
        environment={
            "project_name": app_settings.PROJECT_NAME,
            "username": username,
            "password": password,
            "email": email_to,
            "link": link,
        },
    )


def generate_password_reset_token(email: str) -> str:
    delta = timedelta(hours=app_settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    now = datetime.utcnow()
    expires = now + delta
    exp = expires.timestamp()
    return jwt.encode(
        {"exp": exp, "nbf": now, "sub": email},
        app_settings.SESSION_SECRET,
        algorithm="HS256",
    )


def verify_password_reset_token(token: str) -> Optional[str]:
    try:
        decoded_token = jwt.decode(token, app_settings.SESSION_SECRET, algorithms=["HS256"])
        return decoded_token["sub"]
    except jwt.JWTError:
        return None
