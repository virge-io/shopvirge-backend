from http import HTTPStatus
from unittest import mock

from sqlalchemy.exc import OperationalError


def test_get_health(test_client):
    response = test_client.get("/health/")
    assert HTTPStatus.OK == response.status_code
    assert response.json() == "OK"


@mock.patch("server.api.endpoints.system.health.ProductTable")
def test_get_health_no_connection(mock_preference, test_client):
    mock_preference.query.with_entities().limit().first.side_effect = OperationalError("THIS", "IS", "KABOOM")
    response = test_client.get("/health/")
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
