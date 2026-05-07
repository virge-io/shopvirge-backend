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

import secrets
import string
from typing import Any, Dict, List, Optional

import jinja2
from pydantic import ValidationInfo, field_validator
from pydantic.networks import EmailStr, PostgresDsn
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    """
    Deal with global app settings.

    The goal is to provide some sensible default for developers here. All constants can be
    overloaded via ENV vars. The validators are used to ensure that you get readable error
    messages when an ENV var isn't correctly formated; for example when you provide an incorrect
    formatted DATABASE_URI.

    ".env" loading is also supported. FastAPI will autoload and ".env" file if one can be found

    In production you need to provide a lot stuff via the ENV. At least DATABASE_URI, SESSION_SECRET,
    TESTING, LOGLEVEL and EMAILS_ENABLED + mail server settings if needed.
    """

    PROJECT_NAME: str = "Prijslijst backend"
    TESTING: bool = True
    EMAILS_ENABLED: bool = False
    MCP_ENABLED: bool = False
    # SESSION_SECRET: str = "".join(secrets.choice(string.ascii_letters) for i in range(16))  # noqa: S311
    SESSION_SECRET: str = "CHANGEME"

    # COGNITO SETTING
    AWS_COGNITO_USERPOOL_ID: str = "AWS_COGNITO_USERPOOL_ID"
    AWS_COGNITO_CLIENT_ID: str = "AWS_COGNITO_CLIENT_ID"
    AWS_COGNITO_M2M_CLIENT_ID: str = "AWS_COGNITO_M2M_CLIENT_ID"
    AWS_COGNITO_M2M_CLIENT_SECRET: str = "AWS_COGNITO_M2M_CLIENT_SECRET"
    # Pre-registered Cognito app client used by MCP clients (Claude Code etc.)
    # that can't do dynamic client registration. The /oauth/register shim
    # returns this id verbatim.
    AWS_COGNITO_MCP_CLIENT_ID: str = ""
    AWS_COGNITO_REGION: str = "eu-central-1"

    # Public base URL of the backend, used to build absolute URLs in the OAuth
    # discovery documents (issuer-style fields, registration_endpoint, etc.).
    # Must be set in production; local dev defaults to the dev server URL.
    PUBLIC_BASE_URL: str = "http://localhost:8080"

    # Sentry settings
    SENTRY_DSN: Optional[str] = None
    SENTRY_SAMPLE_RATE: float = 1.0  # change to 0.1 for production

    # OAUTH settings
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    JWT_ALGORITHM: str = "HS256"
    # CORS settings
    CORS_ORIGINS: str = "*"
    CORS_ALLOW_METHODS: List[str] = [
        "GET",
        "PUT",
        "PATCH",
        "POST",
        "DELETE",
        "OPTIONS",
        "HEAD",
    ]
    # Todo: find correct header settings for upload of file with:
    #  No 'Access-Control-Allow-Origin' header is present on the requested resource.
    CORS_ALLOW_HEADERS: List[str] = [
        "If-None-Match",
        "Authorization",
        "If-Match",
        "Content-Type",
        "Access-Control-Allow-Origin",
    ]
    # CORS_ALLOW_HEADERS: List[str] = ["*"]

    CORS_EXPOSE_HEADERS: List[str] = [
        "Cache-Control",
        "Content-Language",
        "Content-Length",
        "Content-Type",
        "Expires",
        "Last-Modified",
        "Pragma",
        "Content-Range",
        "ETag",
    ]
    SWAGGER_PORT: int = 8080
    ENVIRONMENT: str = "local"
    SWAGGER_HOST: str = "localhost"
    GUI_URI: str = "http://localhost:3000"
    # DB (probably only postgres for now; we use UUID postgres dialect for the ID's)
    DATABASE_URI: str = "postgresql://shop:shop@localhost/shop"

    # @field_validator("DATABASE_URI", mode='before')
    # def assemble_db_connection(cls, v: Optional[str], values: Dict[str, Any]) -> Any:
    #     if isinstance(v, str):
    #         return v
    #     return PostgresDsn.build(
    #         scheme="postgresql",
    #         user=values.get("POSTGRES_USER"),
    #         password=values.get("POSTGRES_PASSWORD"),
    #         host=values.get("POSTGRES_SERVER"),
    #         path=f"/{values.get('POSTGRES_DB') or ''}",
    #     )

    MAX_WORKERS: int = 5
    CACHE_HOST: str = "127.0.0.1"
    CACHE_PORT: int = 6379
    POST_MORTEM_DEBUGGER: str = ""
    SERVICE_NAME: str = "Prijslijst backend"
    LOGGING_HOST: str = "localhost"
    LOG_LEVEL: str = "DEBUG"

    # Mail settings
    SMTP_TLS: bool = True
    SMTP_ENABLED: bool = False
    SMTP_PORT: Optional[int] = 587
    SMTP_HOST: Optional[str] = None
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    EMAILS_FROM_EMAIL: Optional[EmailStr] = "no-reply@prijslijst.info"
    EMAILS_FROM_NAME: Optional[str] = "Prijslijst Backend"
    EMAILS_CC: Optional[str] = "no-reply@prijslijst.info"

    FIRST_SUPERUSER: str = "NAME"
    FIRST_SUPERUSER_PASSWORD: str = "JePass"
    FIRST_SUPERUSER_ROLE: str = "admin"
    FIRST_SUPERUSER_ROLE_DESCRIPTION: str = "God Mode!"

    @field_validator("EMAILS_FROM_NAME")
    def get_project_name(cls, v: Optional[str], info: ValidationInfo) -> str:
        if not v:
            return info.data["PROJECT_NAME"]
        return v

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48
    # Todo: check path. The original had one extra folder "app"
    EMAIL_TEMPLATES_DIR: str = "server/email-templates/build"

    @field_validator("EMAILS_ENABLED", mode="before")
    def get_emails_enabled(cls, v: bool, info: ValidationInfo) -> bool:
        return bool(info.data.get("SMTP_HOST") and info.data.get("SMTP_PORT") and info.data.get("EMAILS_FROM_EMAIL"))

    EMAIL_TEST_USER: EmailStr = "test@example.com"  # type: ignore

    # AWS Lambda settings
    LAMBDA_ACCESS_KEY_ID: str = "CHANGEME"
    LAMBDA_SECRET_ACCESS_KEY: str = "CHANGEME"

    # TODO: think of better naming convention
    # Production S3 bucket
    S3_BUCKET_IMAGES_ACCESS_KEY_ID: str = "CHANGEME"
    S3_BUCKET_IMAGES_SECRET_ACCESS_KEY: str = "CHANGEME"
    S3_BUCKET_IMAGES_NAME: str = "CHANGE_THIS_FOR_UPLOAD"  # used to store images and to generate signed URI's

    S3_BUCKET_DOWNLOADS_NAME: str = "CHANGE_THIS_FOR_UPLOAD"
    S3_BUCKET_DOWNLOADS_ACCESS_KEY_ID: str = "CHANGEME"
    S3_BUCKET_DOWNLOADS_SECRET_ACCESS_KEY: str = "CHANGEME"

    # Temporary S3 where images go before they are moved to the production bucket
    S3_BUCKET_TEMPORARY_NAME: str = "CHANGEME"
    S3_TEMPORARY_ACCESS_KEY_ID: str = "CHANGEME"
    S3_TEMPORARY_ACCESS_KEY: str = "CHANGEME"

    S3_BUCKET_UPLOAD_ACCESS_KEY_ID: str = "CHANGEME"
    S3_BUCKET_UPLOAD_SECRET_ACCESS_KEY: str = "CHANGEME"
    S3_BUCKET_UPLOAD_IMAGES_NAME: str = "CHANGE_THIS_FOR_IMAGE_UPLOAD"  # used to store images
    S3_BUCKET_UPLOAD_DOWNLOADS_NAME: str = "CHANGE_THIS_FOR_ASSET_UPLOAD"  # used to store downloads

    class Config:
        env_file = ".env"


app_settings = AppSettings()


class AuthSetting(BaseSettings):
    # COGNITO SETTING
    check_expiration: bool = True
    jwt_header_prefix: str = "Bearer"
    jwt_header_name: str = "Authorization"
    userpools: dict[str, dict[str, Any]] = {
        "eu": {
            "region": app_settings.AWS_COGNITO_REGION,
            "userpool_id": app_settings.AWS_COGNITO_USERPOOL_ID,
            "app_client_id": [
                app_settings.AWS_COGNITO_CLIENT_ID,
                app_settings.AWS_COGNITO_M2M_CLIENT_ID,
                app_settings.AWS_COGNITO_MCP_CLIENT_ID,
            ],
        },
    }


class MailSettings(BaseSettings):
    MAIL_ENABLED: bool = True

    MAIL_BCC: str = "support@pricelist.info"
    MAIL_FROM: str = "support@pricelist.info"

    # These shadow/override Orchestrator Core settings: added for readability
    MAIL_SERVER: str = "localhost"
    MAIL_PORT: int = 1025  # default to Mailhog, see Readme for setup instructions
    MAIL_STARTTLS: bool = False
    MAIL_SMTP_USERNAME: str = ""
    MAIL_SMTP_PASSWORD: str = ""

    SHOP_MAIL_ENABLED: bool = False

    # Opens an unauthenticated /mail-test endpoint that sends a fake order confirmation
    # through the configured SMTP (i.e. Mailpit) for local smoke testing. Never enable
    # in production — anyone who can reach the backend can trigger outbound mail.
    MAIL_TEST_ENDPOINT_ENABLED: bool = False
    MAIL_TEST_SEND_ENABLED: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"


def template_environment(loader: jinja2.BaseLoader) -> jinja2.Environment:
    """Return a safe jinja2 environment to render a template.

    Args:
        loader: A loader.

    Return:
    --
        Jinja2 Environment

    """
    return jinja2.Environment(
        loader=loader, autoescape=True, lstrip_blocks=True, trim_blocks=True, undefined=jinja2.StrictUndefined
    )


auth_settings = AuthSetting()
mail_settings = MailSettings()
