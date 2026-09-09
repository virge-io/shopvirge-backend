import structlog
from fastapi import APIRouter

from server.api.helpers import create_presigned_url, delete_from_temporary_bucket, move_between_buckets

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/signed-url/{image_name}")
def get_signed_url(image_name: str):
    return create_presigned_url(image_name)


@router.post("/move")
def move_images():
    return move_between_buckets()


@router.post("/delete-temp")
def delete_temporary_images():
    return delete_from_temporary_bucket()
