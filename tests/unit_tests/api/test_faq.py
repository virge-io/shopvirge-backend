from server.db.models import FaqTable
from server.utils.json import json_dumps


def test_faq_create(test_client):
    body = {
        "question": "How do I reset my password?",
        "answer": "Click on 'Forgot Password' on the login page.",
        "category": "Account",
    }

    response = test_client.post("/faq", content=json_dumps(body))
    assert response.status_code == 201
    faq = FaqTable.query.first()
    assert faq.question == "How do I reset my password?"
    assert faq.answer == "Click on 'Forgot Password' on the login page."
    assert faq.category == "Account"


def test_faq_create_missing_fields(test_client):
    body = {
        "question": "What is your return policy?",
        # Missing 'answer' and 'category'
    }

    response = test_client.post("/faq", content=json_dumps(body))
    assert response.status_code == 422
    assert "Field required" in response.json()["detail"][0]["msg"]


def test_faq_create_invalid_type(test_client):
    body = {
        "question": "What is your refund period?",
        "answer": 1234,  # Invalid type: should be str
        "category": "Orders",
    }

    response = test_client.post("/faq", content=json_dumps(body))
    assert response.status_code == 422
    assert "Input should be a valid string" in response.json()["detail"][0]["msg"]
