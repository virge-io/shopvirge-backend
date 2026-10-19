"""Product image uploads for agents: fetch or decode an image server-side, store it in S3, set the slot.

The admin UI uploads straight to S3 with a presigned POST, which an LLM cannot do. These routes give
MCP clients the same end result: the object lands in ``S3_BUCKET_UPLOAD_IMAGES_NAME`` under
``{shop_id}/...`` and that key is stored in ``image_{slot}``, exactly as the admin stores it.
"""

import base64
import binascii
import ipaddress
import socket
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Optional
from urllib.parse import urljoin, urlparse
from uuid import UUID, uuid4

import boto3
import httpx
import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel, Field, model_validator

from server.agent_tags import AgentTag
from server.api.error_handling import raise_status
from server.crud.crud_product import product_crud
from server.db import db
from server.security import Principal, current_principal
from server.services.revisions import ensure_baseline_product_revision, record_product_revision
from server.settings import app_settings

logger = structlog.get_logger(__name__)

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
PREVIEW_URL_EXPIRATION = 3600

# (magic prefix, extension, content type); webp is checked separately (RIFF....WEBP)
_SIGNATURES = [
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
]


class ProductImageUpload(BaseModel):
    image_url: Optional[str] = Field(
        None, description="Public http(s) URL of the image. The server downloads it. Max 10 MB."
    )
    image_base64: Optional[str] = Field(
        None,
        description="Image bytes as base64, raw or as a data URL (`data:image/png;base64,...`). Max 10 MB decoded.",
    )

    @model_validator(mode="after")
    def exactly_one_source(self) -> "ProductImageUpload":
        if bool(self.image_url) == bool(self.image_base64):
            raise ValueError("Provide exactly one of `image_url` or `image_base64`")
        return self


def _sniff_image(data: bytes) -> tuple[str, str]:
    """Return ``(extension, content_type)`` for a supported image, or 400."""
    for magic, extension, content_type in _SIGNATURES:
        if data.startswith(magic):
            return extension, content_type
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise HTTPException(HTTPStatus.BAD_REQUEST, "Not a supported image; expected PNG, JPEG, GIF or WebP")


def _decode_base64(value: str) -> bytes:
    payload = value.split(",", 1)[1] if value.startswith("data:") else value
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise_status(HTTPStatus.BAD_REQUEST, "`image_base64` is not valid base64")
    if len(data) > MAX_IMAGE_BYTES:
        raise_status(HTTPStatus.BAD_REQUEST, "Image exceeds the 10 MB limit")
    return data


def _assert_public_host(url: str) -> None:
    """Refuse non-http(s) URLs and hosts resolving to private, loopback, link-local or reserved addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise_status(HTTPStatus.BAD_REQUEST, "`image_url` must be an http(s) URL")
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise_status(HTTPStatus.BAD_REQUEST, f"Could not resolve host {parsed.hostname}")
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise_status(HTTPStatus.BAD_REQUEST, "`image_url` must point to a public host")


def _fetch_image(url: str) -> bytes:
    """Download ``url`` with a size cap, re-validating the host on every redirect hop."""
    with httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _assert_public_host(url)
            try:
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code != HTTPStatus.OK:
                        raise_status(
                            HTTPStatus.BAD_REQUEST, f"Fetching `image_url` failed with HTTP {response.status_code}"
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE_BYTES:
                            raise_status(HTTPStatus.BAD_REQUEST, "Image exceeds the 10 MB limit")
                    return bytes(data)
            except httpx.HTTPError as error:
                logger.warning("Fetching image failed", url=url, error=str(error))
                raise_status(HTTPStatus.BAD_REQUEST, "Could not download `image_url`")
    raise HTTPException(HTTPStatus.BAD_REQUEST, "Too many redirects fetching `image_url`")


def _upload_s3_client() -> Any:
    return boto3.client(
        "s3",
        aws_access_key_id=app_settings.S3_BUCKET_UPLOAD_ACCESS_KEY_ID,
        aws_secret_access_key=app_settings.S3_BUCKET_UPLOAD_SECRET_ACCESS_KEY,
        region_name="eu-central-1",
    )


def _get_product(shop_id: UUID, product_id: UUID) -> Any:
    product = product_crud.get_id_by_shop_id(shop_id, product_id, for_update=True)
    if not product:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Product not found")
    return product


def _set_slot(product: Any, slot: int, value: Optional[str], principal: Principal) -> None:
    ensure_baseline_product_revision(product)
    setattr(product, f"image_{slot}", value)
    product.modified_at = datetime.now(timezone.utc)
    db.session.flush()
    record_product_revision(product, action="update", created_by=principal.label, source=principal.via)
    db.session.commit()


@router.post(
    "/{product_id}/images/{slot}",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="upload_product_image",
    summary="Upload product image",
    description=(
        "Upload a picture and attach it to a product image slot (1-6; slot 1 is the main image). Give "
        "EITHER `image_url` (a public http(s) URL the server downloads) OR `image_base64` (raw base64 or a "
        "data URL), never both. PNG, JPEG, GIF and WebP up to 10 MB are accepted. Replaces whatever image "
        "is in that slot; the previous image stays restorable through the product's revisions. Returns the "
        "stored S3 key and a temporary `preview_url` to check the result."
    ),
)
def upload_image(
    shop_id: UUID,
    product_id: UUID,
    slot: int = Path(..., ge=1, le=6, description="Image slot 1-6"),
    data: ProductImageUpload = Body(...),
    principal: Principal = Depends(current_principal),
) -> dict:
    product = _get_product(shop_id, product_id)

    image = _fetch_image(data.image_url) if data.image_url else _decode_base64(data.image_base64 or "")
    extension, content_type = _sniff_image(image)

    # A fresh key per upload: overwriting an existing object would break restoring older revisions
    key = f"{shop_id}/{product_id}-{slot}-{uuid4().hex[:12]}.{extension}"
    s3_client = _upload_s3_client()
    try:
        s3_client.put_object(
            Bucket=app_settings.S3_BUCKET_UPLOAD_IMAGES_NAME, Key=key, Body=image, ContentType=content_type
        )
    except Exception as error:
        logger.error("Uploading product image failed", key=key, error=str(error))
        raise_status(HTTPStatus.BAD_GATEWAY, "Storing the image failed")

    _set_slot(product, slot, key, principal)
    logger.info("Product image uploaded", product_id=str(product_id), shop_id=str(shop_id), slot=slot, key=key)

    preview_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": app_settings.S3_BUCKET_UPLOAD_IMAGES_NAME, "Key": key},
        ExpiresIn=PREVIEW_URL_EXPIRATION,
    )
    return {"product_id": str(product_id), "slot": slot, f"image_{slot}": key, "preview_url": preview_url}


@router.delete(
    "/{product_id}/images/{slot}",
    response_model=None,
    status_code=HTTPStatus.OK,
    tags=[AgentTag.EXPOSED],
    operation_id="delete_product_image",
    summary="Remove product image",
    description=(
        "Clear one product image slot (1-6). Only the product's reference is removed; the file is kept so "
        "the image can be brought back by restoring an earlier product revision."
    ),
)
def delete_image(
    shop_id: UUID,
    product_id: UUID,
    slot: int = Path(..., ge=1, le=6, description="Image slot 1-6"),
    principal: Principal = Depends(current_principal),
) -> dict:
    product = _get_product(shop_id, product_id)
    if not getattr(product, f"image_{slot}"):
        raise_status(HTTPStatus.NOT_FOUND, f"Product has no image in slot {slot}")

    _set_slot(product, slot, None, principal)
    logger.info("Product image removed", product_id=str(product_id), shop_id=str(shop_id), slot=slot)
    return {"product_id": str(product_id), "slot": slot, f"image_{slot}": None}
