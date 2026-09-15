from datetime import datetime, timezone
from http import HTTPStatus
from types import SimpleNamespace
from typing import Optional
from uuid import uuid4

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr

from server.mail import send_order_confirmation_emails
from server.settings import mail_settings

logger = structlog.get_logger(__name__)

router = APIRouter()


class MailTestRequest(BaseModel):
    to: EmailStr = "customer@example.com"
    shop_name: str = "ShopVirge Dev"
    owner_email: Optional[EmailStr] = None


class MailTestResponse(BaseModel):
    sent_to_customer: EmailStr
    sent_to_owner: Optional[EmailStr]
    customer_order_id: int


@router.post("/send-order-confirmation", response_model=MailTestResponse, status_code=HTTPStatus.OK)
def send_test_order_confirmation(payload: MailTestRequest = MailTestRequest()) -> MailTestResponse:
    """Send a synthetic order confirmation mail through the configured SMTP.

    Intended for local testing against Mailpit. Gated by settings.MAIL_TEST_ENDPOINT_ENABLED.
    """
    customer_order_id = 9000 + int(datetime.now(timezone.utc).timestamp()) % 1000

    shop = SimpleNamespace(
        id=uuid4(),
        name=payload.shop_name,
        vat_standard=21,
        vat_lower_1=15,
        vat_lower_2=10,
        vat_lower_3=5,
        vat_special=2,
        vat_zero=0,
        config={
            "contact": {
                "company": payload.shop_name,
                "address": "Teststraat 1",
                "zip_code": "1000 AA",
                "city": "Amsterdam",
                "phone": "+31 6 12345678",
                "email": payload.owner_email or "",
            },
            "legal": {"kvk_number": "12345678", "btw_number": "NL123456789B01"},
            "languages": {"main": {"language_name": "nl"}},
        },
    )

    order = SimpleNamespace(
        id=uuid4(),
        customer_order_id=customer_order_id,
        completed_at=datetime.now(timezone.utc),
        order_info=[
            {
                "description": "Smoke-test line",
                "product_name": "Test Product",
                "price": 12.50,
                "quantity": 2,
                "product_id": str(uuid4()),
            },
        ],
    )

    account = SimpleNamespace(name=str(payload.to), details=None)

    try:
        send_order_confirmation_emails(order=order, shop=shop, account=account)
    except Exception as exc:
        logger.error("Mail test endpoint failed", error=str(exc))
        raise HTTPException(status_code=HTTPStatus.INTERNAL_SERVER_ERROR, detail=f"Mail send failed: {exc}") from exc

    logger.info(
        "Mail test endpoint sent order confirmation",
        mail_server=mail_settings.MAIL_SERVER,
        mail_port=mail_settings.MAIL_PORT,
        customer=payload.to,
    )

    return MailTestResponse(
        sent_to_customer=payload.to,
        sent_to_owner=payload.owner_email,
        customer_order_id=customer_order_id,
    )
