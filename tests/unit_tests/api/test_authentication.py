import re
import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient

EXCLUDED_ENDPOINTS = [
    {"path": "/health/", "name": "get_health", "method": "GET"},
    {"path": "/products/", "name": "get_multi", "method": "GET"},
    {"path": "/products/{id}/", "name": "get_id", "method": "GET"},
    {"path": "/shops/{shop_id}/prices/", "name": "get_products", "method": "GET"},
    {"path": "/shops/{shop_id}/prices/", "name": "get_cart_products", "method": "POST"},
    {"path": "/orders/", "name": "create", "method": "POST"},
    {"path": "/shops/{shop_id}/stripe/", "name": "create_payment_intent", "method": "POST"},
    {"path": "/shops/{shop_id}/stripe/subscription", "name": "create_subscription_intent", "method": "POST"},
    {"path": "/info-request/", "name": "create_info_request", "method": "POST"},
    {"path": "/sentry/", "name": "trigger_error", "method": "GET"},
    {"path": "/test-forms/", "name": "form", "method": "POST"},
    {"path": "/faq/", "name": "get_multi", "method": "GET"},
    {"path": "/faq/{id}", "name": "get_by_id", "method": "GET"},
    {"path": "/shops/", "name": "get_multi", "method": "GET"},
    {"path": "/shops/", "name": "create", "method": "POST"},
    # Temporary exclusion to avoid the greedy-params bug
    # TODO fix this endpoint so it no longer needs the shop_id or fix this bug by fixing the UT below
    {"path": "/shops/{shop_id}/attributes/{attribute_id}/options/", "name": "list_options", "method": "GET"},
]


def get_endpoints(fastapi_app):
    url_list = []
    for route in fastapi_app.routes:
        if hasattr(route, "methods"):
            if str(route.path).endswith("/"):
                url_list.append({"path": route.path, "name": route.name, "method": list(route.methods)[0]})
    return url_list


def test_endpoint_auth(monkeypatch, fastapi_app_not_authenticated):
    test_client = TestClient(fastapi_app_not_authenticated)

    responses = []
    for endpoint in get_endpoints(fastapi_app=test_client.app):
        if endpoint not in EXCLUDED_ENDPOINTS:
            if endpoint["method"] == "GET":
                if re.search("{.*}", endpoint["path"]):
                    url_with_uuid = re.sub("{.*}", str(uuid.uuid4()), endpoint["path"])
                    responses.append(test_client.get(f"{url_with_uuid}"))
                else:
                    responses.append(test_client.get(f"{endpoint['path']}"))
            elif endpoint["method"] == "POST":
                responses.append(test_client.post(f"{endpoint['path']}"))
            elif endpoint["method"] == "PUT":
                url_with_uuid = re.sub("{.*}", str(uuid.uuid4()), endpoint["path"])
                responses.append(test_client.put(f"{url_with_uuid}"))
            elif endpoint["method"] == "DELETE":
                url_with_uuid = re.sub("{.*}", str(uuid.uuid4()), endpoint["path"])
                responses.append(test_client.delete(f"{url_with_uuid}"))

    not_401_responses = []

    for response in responses:
        print(response.json())
        if response.status_code != 401:
            not_401_responses.append(response)

    assert (
        len(not_401_responses) == 0
    ), f"These response where not behind security: {[(i.request.method, i.url) for i in not_401_responses]}"
