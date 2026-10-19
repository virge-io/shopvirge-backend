"""Signed S3 uploads for product images, for agents.

The caller POSTs the file straight to S3 with the returned form, then stores the returned ``key`` in
``image_{slot}`` via ``update_product``. The server picks the key, so a re-upload never overwrites an
object an older product revision still points to.
"""

from http import HTTPStatus
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from server.agent_tags import AgentTag
from server.api.endpoints.images.shop import create_presigned_post_url
from server.crud.crud_product import product_crud

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024
UPLOAD_EXPIRATION_SECONDS = 600

_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}


class ProductImageUploadRequest(BaseModel):
    content_type: Literal["image/png", "image/jpeg", "image/gif", "image/webp"] = Field(
        ..., description="MIME type of the file you are going to upload."
    )


@router.post(
    "/{product_id}/images/{slot}/upload-url",
    response_model=None,
    status_code=HTTPStatus.CREATED,
    tags=[AgentTag.EXPOSED],
    operation_id="create_product_image_upload",
    summary="Get a signed product image upload",
    description=(
        "Step 1 of adding a product picture (slot 1-6; slot 1 is the main image). Returns `url`, `fields` and "
        "the S3 object `key`. Then (2) send the file with `POST url` as multipart/form-data: every entry of "
        "`fields` first, the file last in a field named `file`; the `Content-Type` field is already in "
        "`fields`, so the file must really be that type. Max 10 MB, valid for 10 minutes. Then (3) call "
        "`update_product` with `image_{slot}` set to `key`. Nothing is attached to the product until step 3."
    ),
)
def create_upload(
    shop_id: UUID,
    product_id: UUID,
    data: ProductImageUploadRequest,
    slot: int = Path(..., ge=1, le=6, description="Image slot 1-6"),
) -> dict:
    if not product_crud.get_id_by_shop_id(shop_id, product_id):
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Product not found")

    # A fresh name per upload: overwriting an object would break restoring older revisions
    object_name = f"{product_id}-{slot}-{uuid4().hex[:12]}.{_EXTENSIONS[data.content_type]}"
    post = create_presigned_post_url(
        shop_id,
        object_name,
        fields={"Content-Type": data.content_type},
        conditions=[{"Content-Type": data.content_type}, ["content-length-range", 1, MAX_IMAGE_BYTES]],
        expiration=UPLOAD_EXPIRATION_SECONDS,
    )
    if post is None:
        raise HTTPException(status_code=HTTPStatus.BAD_GATEWAY, detail="Could not sign the upload")

    return {
        "product_id": str(product_id),
        "slot": slot,
        "key": f"{shop_id}/{object_name}",
        "url": post["url"],
        "fields": post["fields"],
    }
