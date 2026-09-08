import os
import time
from http import HTTPStatus

import httpx
import structlog
from fastapi import APIRouter
from sentry_sdk import capture_exception

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/", status_code=HTTPStatus.OK, response_model=None)
def trigger_error(type: str):
    logger.info(f"Triggering {type} error for Sentry test")

    if type == "attribute":
        trigger_attribute_error()
    elif type == "type":
        trigger_type_error()
    elif type == "file":
        trigger_file_not_found_error()
    elif type == "permission":
        trigger_permission_error()
    elif type == "http":
        trigger_http_error()
    elif type == "timeout":
        trigger_timeout_error()
    elif type == "custom":
        trigger_custom_error()
    elif type == "zero":
        1 / 0  # noqa: B018 -- deliberate ZeroDivisionError for the Sentry smoke test
    elif type == "handled":
        trigger_handled_error()
    else:
        raise ValueError("Unknown error type")


def trigger_attribute_error():
    none_obj = None
    none_obj.do_something()


def trigger_type_error():
    sum("string", 5)


def trigger_file_not_found_error():
    with open("non_existent_file.txt", "r") as f:
        f.read()


def trigger_permission_error():
    os.chmod("readonly.txt", 0o400)  # make it read-only
    with open("readonly.txt", "w") as f:
        f.write("This should fail")


def trigger_http_error():
    response = httpx.get("https://httpbin.org/status/500")
    response.raise_for_status()


def trigger_timeout_error():
    time.sleep(10)  # can use async sleep in real-world async context
    raise TimeoutError("Custom timeout simulation")


class CustomBackendError(Exception):
    pass


def trigger_custom_error():
    raise CustomBackendError("This is a manually triggered custom error.")


def trigger_handled_error():
    try:
        open("some_missing_file.txt", "r")
    except Exception as e:
        logger.warning("Handled FileNotFoundError triggered", exc_info=e)
        capture_exception(e)
