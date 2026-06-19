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
import base64
import json
import os
from ast import literal_eval
from datetime import datetime
from http import HTTPStatus
from typing import List, Optional
from uuid import UUID

import boto3 as boto3
from fastapi import HTTPException
from more_itertools import chunked
from sqlalchemy import String, cast
from sqlalchemy.orm import Query
from sqlalchemy.sql import expression
from starlette.responses import Response
from structlog import get_logger

from server.api.error_handling import raise_status
from server.crud.crud_order import order_crud
from server.crud.crud_shop import shop_crud
from server.db import db
from server.db.database import BaseModel
from server.schemas import ShopUpdate
from server.settings import app_settings

logger = get_logger(__name__)

# Todo: decide if we need this
VALID_SORT_KEYS = {
    "id": "id",
    "name": "name",
    "created": "created_at",
    "creator": "created_by",
    "modifier": "modified_by",
    "modified": "modified_at",
}

s3 = boto3.resource(
    "s3",
    aws_access_key_id=app_settings.S3_BUCKET_IMAGES_ACCESS_KEY_ID,
    aws_secret_access_key=app_settings.S3_BUCKET_IMAGES_SECRET_ACCESS_KEY,
    region_name="eu-central-1",
)

s3_client = boto3.client(
    "s3",
    aws_access_key_id=app_settings.S3_BUCKET_IMAGES_ACCESS_KEY_ID,
    aws_secret_access_key=app_settings.S3_BUCKET_IMAGES_SECRET_ACCESS_KEY,
    region_name="eu-central-1",
)

s3_client_downloads = boto3.client(
    "s3",
    aws_access_key_id=app_settings.S3_BUCKET_DOWNLOADS_ACCESS_KEY_ID,
    aws_secret_access_key=app_settings.S3_BUCKET_DOWNLOADS_SECRET_ACCESS_KEY,
    region_name="eu-central-1",
)

s3_temporary = boto3.resource(
    "s3",
    aws_access_key_id=app_settings.S3_TEMPORARY_ACCESS_KEY_ID,
    aws_secret_access_key=app_settings.S3_TEMPORARY_ACCESS_KEY,
    region_name="eu-central-1",
)

sendMessageLambda = boto3.client(
    "lambda",
    aws_access_key_id=app_settings.LAMBDA_ACCESS_KEY_ID,
    aws_secret_access_key=app_settings.LAMBDA_SECRET_ACCESS_KEY,
    region_name="eu-central-1",
)


def get_range_from_args(args):
    if args["range"]:
        range = []
        try:
            input = args["range"][1:-1].split(",")
            for i in input:
                range.append(int(i))
            logger.info("Query parameters set to custom range", range=range)
            return range
        except:  # noqa: E722
            logger.warning(
                "Query parameters not parsable",
                args=args.get(["range"], "No range provided"),
            )
    range = [0, 19]  # Default range
    logger.info("Query parameters set to default range", range=range)
    return range


def get_sort_from_args(args, default_sort="name", default_sort_order="ASC"):
    sort = []
    if args["sort"]:
        try:
            input = args["sort"].split(",")
            sort.append(input[0][2:-1])
            sort.append(input[1][1:-2])
            logger.info("Query parameters set to custom sort", sort=sort)
            return sort
        except:  # noqa: E722
            logger.warning(
                "Query parameters not parsable",
                args=args.get(["sort"], "No sort provided"),
            )
    sort = [default_sort, default_sort_order]  # Default sort
    logger.info("Query parameters set to default sort", sort=sort)
    return sort


def get_filter_from_args(args, default_filter={}):
    if args["filter"]:
        # print(args["filter"])
        try:
            filter = literal_eval(args["filter"].replace(":true", ":True").replace(":false", ":False"))
            logger.info("Query parameters set to custom filter", filter=filter)
            return filter
        except:  # noqa: E722
            logger.warning(
                "Query parameters not parsable",
                args=args.get(["filter"], "No filter provided"),
            )
    logger.info("Query parameters set to default filter", filter=default_filter)
    return default_filter


def save(item):
    try:
        db.session.add(item)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        raise_status(HTTPStatus.BAD_REQUEST, "DB error: {}".format(str(error)))


def load(model, id, fields=None, allow_404=False):
    if fields is None:
        fields = []

    if not fields:  # query "all" fields:
        item = model.query.filter_by(id=id).first()
    else:
        item = model.query.filter_by(id=id).first()
    if not item and not allow_404:
        raise_status(HTTPStatus.NOT_FOUND, f"Record id={id} not found")
    return item


def update(item, payload):
    if payload.get("id"):
        del payload["id"]
    try:
        for column, value in payload.items():
            setattr(item, column, value)
        save(item)
    except Exception as e:
        raise_status(HTTPStatus.INTERNAL_SERVER_ERROR, f"Error: {e}")
    return item


def delete(item):
    try:
        db.session.delete(item)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        raise_status(HTTPStatus.BAD_REQUEST, "DB error: {}".format(str(error)))


def _query_with_filters(
    response: Response,
    model: BaseModel,
    query: Query,
    range: Optional[List[int]] = None,
    sort: Optional[List[str]] = None,
    filters: Optional[List[str]] = None,
) -> List:
    if filters is not None:
        for filter in chunked(filters, 2):
            if filter and len(filter) == 2:
                field = filter[0]
                value = filter[1]
                value_as_bool = value.lower() in (
                    "yes",
                    "y",
                    "ye",
                    "true",
                    "1",
                    "ja",
                    "insync",
                )
                if value is not None:
                    if field.endswith("_gt"):
                        query = query.filter(model.__dict__[field[:-3]] > value)
                    elif field.endswith("_gte"):
                        query = query.filter(model.__dict__[field[:-4]] >= value)
                    elif field.endswith("_lte"):
                        query = query.filter(model.__dict__[field[:-4]] <= value)
                    elif field.endswith("_lt"):
                        query = query.filter(model.__dict__[field[:-3]] < value)
                    elif field.endswith("_ne"):
                        query = query.filter(model.__dict__[field[:-3]] != value)
                    elif field == "tsv":
                        logger.debug("Running full-text search query.", value=value)
                        query = query.search(value)
                    elif field in model.__dict__:
                        query = query.filter(cast(model.__dict__[field], String).ilike("%" + value + "%"))

    if sort is not None and len(sort) >= 2:
        for sort in chunked(sort, 2):
            if sort and len(sort) == 2:
                if sort[1].upper() == "DESC":
                    query = query.order_by(expression.desc(model.__dict__[sort[0]]))
                else:
                    query = query.order_by(expression.asc(model.__dict__[sort[0]]))
    if range is not None and len(range) == 2:
        try:
            range_start = int(range[0])
            range_end = int(range[1])
            assert range_start < range_end
        except (ValueError, AssertionError):
            msg = "Invalid range parameters"
            logger.exception(msg)
            raise_status(HTTPStatus.BAD_REQUEST, msg)
        total = query.count()
        query = query.slice(range_start, range_end)

        response.headers["Content-Range"] = f"items {range_start}-{range_end}/{total}"

    return query.all()


def upload_file(blob, file_name):
    image_mime, image_base64 = blob.split(",")
    image = base64.b64decode(image_base64)

    # Todo: make dynamic
    s3_object = s3.Object(os.getenv("S3_BUCKET_IMAGES_NAME"), file_name)
    resp = s3_object.put(Body=image, ContentType="image/png")

    if resp["ResponseMetadata"]["HTTPStatusCode"] == 200:
        logger.info("Uploaded file to S3", file_name=file_name)

        # Make the result public
        object_acl = s3_object.Acl()
        response = object_acl.put(ACL="public-read")
        logger.info("Made public", response=response)


def name_file(column_name, record_name, image_name=""):
    _, _, image_number = column_name.rpartition("_")[0:3]
    current_name = image_name
    extension = "png"  # todo: make it dynamic e.g. get it from mime-type, extra arg for this function?
    if not current_name:
        name = "".join([c if c.isalnum() else "-" for c in record_name])
        name = f"{name}-{image_number}-1".lower()
    else:
        name, _ = current_name.split(".")
        name, _, counter = name.rpartition("-")[0:3]
        name = f"{name}-{int(counter) + 1}".lower()
    name = f"{name}.{extension}"
    logger.info("Named file", col_name=column_name, name_in=image_name, name_out=name)
    return name


def sendMessageToWebSocketServer(payload):
    try:
        sendMessageLambda.invoke(
            FunctionName="sendMessage", InvocationType="RequestResponse", Payload=json.dumps(payload)
        )
        logger.info("Sending websocket message")
    except Exception as e:
        logger.warning("Websocket exception", exception=str(e))


def invalidateShopCache(shop_id):
    item = shop_crud.get(shop_id)
    item_in = ShopUpdate(
        name=item.name,
        description=item.description,
        modified_at=datetime.utcnow(),
        # Todo: deal with the commented params below
        # last_pending_order=item.last_pending_order,
        # last_completed_order=item.last_completed_order,
        allowed_ips=item.allowed_ips,
    )
    payload = {"connectionType": "shop", "shopId": str(shop_id)}
    sendMessageToWebSocketServer(payload)
    shop_crud.update(db_obj=item, obj_in=item_in)


def invalidateCompletedOrdersCache(order_id):
    item = order_crud.get(order_id)
    shop = shop_crud.get(item.shop_id)
    shop_in = ShopUpdate(
        name=shop.name,
        description=shop.description,
        last_completed_order=str(order_id),
        modified_at=None,
        vat_standard=shop.vat_standard,
        vat_lower_1=shop.vat_lower_1,
        vat_lower_2=shop.vat_lower_2,
        vat_lower_3=shop.vat_lower_3,
        vat_special=shop.vat_special,
        vat_zero=shop.vat_zero,
    )
    payload = {"connectionType": "completed_orders", "shopId": str(shop.id)}
    sendMessageToWebSocketServer(payload)
    try:
        shop_crud.update(db_obj=shop, obj_in=shop_in)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")


def invalidatePendingOrdersCache(order_id):
    item = order_crud.get(order_id)
    shop = shop_crud.get(item.shop_id)
    shop_in = ShopUpdate(
        name=shop.name,
        description=shop.description,
        last_pending_order=str(order_id),
        modified_at=None,
        vat_standard=shop.vat_standard,
        vat_lower_1=shop.vat_lower_1,
        vat_lower_2=shop.vat_lower_2,
        vat_lower_3=shop.vat_lower_3,
        vat_special=shop.vat_special,
        vat_zero=shop.vat_zero,
    )
    payload = {"connectionType": "pending_orders", "shopId": str(shop.id)}
    sendMessageToWebSocketServer(payload)
    try:
        return shop_crud.update(db_obj=shop, obj_in=shop_in)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")


def create_presigned_url(object_name, expiration=7200):
    bucket_name = app_settings.S3_BUCKET_IMAGES_NAME
    try:
        response = s3_client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket_name, "Key": object_name}, ExpiresIn=expiration
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")

    return response


def create_download_url(object_name, expiration):
    bucket_name = app_settings.S3_BUCKET_DOWNLOADS_NAME
    try:
        response = s3_client_downloads.generate_presigned_url(
            "get_object", Params={"Bucket": bucket_name, "Key": object_name}, ExpiresIn=expiration
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")

    return response


def move_between_buckets():
    temp_bucket_name = app_settings.S3_BUCKET_TEMPORARY_NAME
    prod_bucket_name = app_settings.S3_BUCKET_IMAGES_NAME
    prefix = "upload/"

    try:
        list_objects_response = s3_client.list_objects_v2(Bucket=temp_bucket_name, Prefix=prefix, Delimiter="/")
        folder_content_info = list_objects_response.get("Contents")

        if list_objects_response.get("KeyCount") < 1:
            return {"message": "No files to move"}

        for file in folder_content_info:
            copy_source = {"Bucket": temp_bucket_name, "Key": file.get("Key")}
            new_key = file.get("Key").replace(prefix, "")
            s3.meta.client.copy(copy_source, prod_bucket_name, new_key)
            s3_temporary.Object(temp_bucket_name, file.get("Key")).delete()

        return {"message": "Moved files from temporary bucket to production bucket"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")


def delete_from_temporary_bucket():
    temp_bucket_name = app_settings.S3_BUCKET_TEMPORARY_NAME
    prefix = "upload/"

    try:
        list_objects_response = s3_client.list_objects_v2(Bucket=temp_bucket_name, Prefix=prefix, Delimiter="/")
        folder_content_info = list_objects_response.get("Contents")

        if list_objects_response.get("KeyCount") < 1:
            return {"message": "No files to delete"}

        for file in folder_content_info:
            s3_temporary.Object(temp_bucket_name, file.get("Key")).delete()

        return {"message": "Deleted files from temporary bucket"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {e}")


