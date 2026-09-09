from uuid import UUID

import boto3
import structlog
from botocore.exceptions import ClientError
from fastapi import APIRouter

from server.settings import app_settings

logger = structlog.get_logger(__name__)

router = APIRouter()


def create_presigned_post_url(shop_id: UUID, object_name, fields=None, conditions=None, expiration=1800):
    """Generate a presigned URL S3 POST request to upload a file.

    :param object_name: string
    :param fields: Dictionary of prefilled form fields
    :param conditions: List of conditions to include in the policy
    :param expiration: Time in seconds for the presigned URL to remain valid
    :return: Dictionary with the following keys:
        url: URL to post to
        fields: Dictionary of form fields and values to submit with the POST
    :return: None if error.
    """
    bucket_name = app_settings.S3_BUCKET_UPLOAD_IMAGES_NAME
    s3_name = f"{shop_id}/{object_name}"

    # Generate a presigned S3 POST URL
    s3_client = boto3.client(
        "s3",
        aws_access_key_id=app_settings.S3_BUCKET_UPLOAD_ACCESS_KEY_ID,
        aws_secret_access_key=app_settings.S3_BUCKET_UPLOAD_SECRET_ACCESS_KEY,
        region_name="eu-central-1",
    )

    # Todo: do an extra check, to determine if the name already exists!
    #   The endpoint/GUI already know the last name, so they should increase the counter
    #   An extra check is needed here to avoid race conditions with an outdated name

    try:
        response = s3_client.generate_presigned_post(
            bucket_name, s3_name, Fields=fields, Conditions=conditions, ExpiresIn=expiration
        )
    except ClientError as error:
        logger.error("Error whilst signing", object_name=object_name, shop_id=shop_id, error=error)
        return None

    # test the upload:
    # with open(object_name, 'rb') as f:
    #     files = {'file': (object_name, f)}
    #     http_response = requests.post(response['url'], data=response['fields'], files=files)

    return response


@router.get("/signed-url/{image_name}")
def get_signed_upload_url(shop_id: UUID, image_name: str):
    # use image_name with "shop_id" prefix to get a signed upload URL
    return create_presigned_post_url(shop_id, image_name)
