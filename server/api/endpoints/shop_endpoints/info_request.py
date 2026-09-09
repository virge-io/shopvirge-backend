from http import HTTPStatus
from typing import Any, ClassVar
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.param_functions import Body
from pydantic import ConfigDict, EmailStr
from pydantic_forms.core import FormPage as PydanticFormsFormPage
from pydantic_forms.core import post_form
from pydantic_forms.types import JSON, State
from sqlalchemy.exc import IntegrityError

from server.api.helpers import load
from server.crud.crud_info_request import info_request_crud
from server.crud.crud_product import product_crud
from server.db.models import ShopTable
from server.mail import generate_confirmation_mail, send_mail
from server.schemas.info_request import InfoRequestCreate
from server.settings import mail_settings
from server.utils.discord.discord import post_discord_info_request
from server.utils.types import MailAddress, MailType

logger = structlog.get_logger(__name__)

router = APIRouter()


class FormPage(PydanticFormsFormPage):
    meta__: ClassVar[JSON] = {"hasNext": True}


class SubmitFormPage(FormPage):
    meta__: ClassVar[JSON] = {"hasNext": False}


@router.post("/form")
async def form(shop_id: UUID, product_id: UUID, form_data: list[dict] = []):  # noqa: B006 -- FastAPI body default, part of the schema
    def form_generator(state: State):
        class EmailForm(FormPage):
            model_config = ConfigDict(title="Form Title Page 1")

            email: EmailStr

        form_data_email = yield EmailForm

        return form_data_email.model_dump()

    post_form(form_generator, state={}, user_inputs=form_data)
    create_info_request(InfoRequestCreate(email=form_data[0]["email"], product_id=product_id, shop_id=shop_id))


def create_info_request(data: InfoRequestCreate = Body(...)) -> Any:
    try:
        logger.info("Saving early access", data=data)
        info_request = info_request_crud.create(obj_in=data)
        product = product_crud.get_id_by_shop_id(data.shop_id, data.product_id)
        shop = load(ShopTable, data.shop_id)

        try:
            if shop.discord_webhook is not None:
                post_discord_info_request(
                    f"New info request from {data.email} about product: {product.translation.main_name}",
                    botname=shop.name,
                    webhook=shop.discord_webhook,
                    email=data.email,
                    product_name=product.translation.main_name,
                    product_id=data.product_id,
                )
        except Exception as e:
            logger.error("Failed to post to Discord: ", error=str(e))

        if mail_settings.SHOP_MAIL_ENABLED:
            contact_persons = [MailAddress(email=data.email, name="")]
            confirmation_mail = generate_confirmation_mail(
                product, MailType.INFO, shop.name, contact_persons, None, None
            )
            logger.info("Sending info mail", email=data.email)
            send_mail(confirmation_mail)
        else:
            logger.info("Sending the email is disabled for this specific step, not actually sending it.")

        return info_request

    # except ValidationError as ve:
    #     # Log the validation error
    #     logger.error("Validation error occurred", error=str(ve), data=data)
    #     # Raise 422 for incorrect input format
    #     raise HTTPException(
    #         status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
    #         detail="Incorrect input format or missing fields in the request.",
    #     )

    except IntegrityError as ie:
        # Log the duplicate entry error
        logger.error("Duplicate entry error", error=str(ie), data=data)
        # Raise 409 for duplicate entry (e.g., unique constraint violation)
        raise HTTPException(
            status_code=HTTPStatus.CONFLICT,
            detail="Duplicate entry. The record already exists.",
        )

    # except RequestValidationError as rve:
    #     # Log the 400 Bad Request error
    #     logger.error("Bad request error", error=str(rve), data=data)
    #     # Raise 400 for bad requests (malformed or incomplete data)
    #     raise HTTPException(
    #         status_code=HTTPStatus.BAD_REQUEST,
    #         detail="Malformed request or invalid data.",
    #     )

    except Exception as e:
        # Log the unexpected error
        logger.error("Unexpected error occurred", error=str(e), data=data)
        # Raise 500 for unexpected errors
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}",
        )
