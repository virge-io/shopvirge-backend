import structlog
from fastapi import APIRouter

from server.api.helpers import create_download_url
from server.utils.auth import send_download_link_email

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/{file_name}")
def get_signed_download_link(file_name: str):
    return create_download_url(file_name, 7200)


@router.post("/send")
def send_download_link_via_email(file_name: str, email: str, shop_name: str):
    link = create_download_url(file_name, 1209600)
    send_download_link_email(email, link, shop_name)
