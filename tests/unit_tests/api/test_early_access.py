from server.db.models import EarlyAccessTable
from server.utils.json import json_dumps


def test_early_access_create(test_client):
    body = {"email": "support@shopVirge.com"}

    response = test_client.post(f"/early-access", content=json_dumps(body))
    assert response.status_code == 201
    early_access = EarlyAccessTable.query.first()
    assert early_access.email == "support@shopvirge.com"


def test_early_access_create_wrong_email(test_client):
    body = {"email": "supportshopVirge.com"}

    response = test_client.post(f"/early-access", content=json_dumps(body))
    assert response.status_code == 422
    assert "value is not a valid email" in response.json()["detail"][0]["msg"]
