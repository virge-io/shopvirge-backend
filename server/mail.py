import os
from datetime import datetime, timezone
from email.encoders import encode_base64
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import singledispatch
from itertools import filterfalse
from smtplib import SMTP
from typing import Any, Callable, NoReturn
from zoneinfo import ZoneInfo

import html2text
import jinja2
import structlog

from server.schemas.product import ProductBase
from server.settings import mail_settings, template_environment
from server.utils.date_utils import nowtz

# from formatics.utils.singledispatch import single_dispatch_base
from server.utils.types import ConfirmationMail, InlineImage, MailAddress, MailAttachment, MailType

loader = jinja2.FileSystemLoader(os.path.join(os.path.dirname(__file__), "mail_templates"))

logger = structlog.get_logger(__name__)

BCC: list[MailAddress] = [
    {"email": mail_settings.MAIL_BCC, "name": "BCC"},
]
IMAGES_SHOP_VIRGE = [
    InlineImage(cid="bannerimg", filename="shop_virge_banner.png", subtype="png"),
    # jpeg example:
    # InlineImage(cid="bannerimg", filename="shop_virge_banner.png", subtype="jpeg"),
]


def get_template_for_product_summary(filename: str) -> jinja2.Template:
    env = template_environment(loader)
    return env.get_template(
        f"product_types/{filename}",
        globals={
            "generate_product_summary": generate_product_summary,
        },
    )


def single_dispatch_base(func: Callable, value: Any) -> NoReturn:
    registry = func.registry  # type: ignore

    supported_models = ", ".join(map(str, filterfalse(lambda t: t is object, registry.keys())))
    model_type = type(value)
    raise TypeError(
        f"`{func.__name__}` called for unsupported model type {model_type}. "
        f"Supported model types are: {supported_models}"
    )


def _generate_subject(mail_type: MailType, language: str, product: str, shop: str, ticket_id: str | None = None) -> str:
    """Return a subject based on info from the original fourme ticket or return a fallback subject if no fourme info is found.

    Args:
        ticket_id: a ticket ID or not
        mail_type: CREATE, MODIFY, TERMINATE
        model: The subscription Model
        language: English or Dutch

    Returns: a string with an e-mail subject

    """
    ticket_prefix = f"[{ticket_id}] - " if ticket_id else ""

    templates = {
        MailType.INFO: {
            "NL": f"{ticket_prefix}Vraag over {product} van {shop}",
            "EN": f"{ticket_prefix}Question about {product} from {shop}",
        },
    }

    try:
        subject = templates[mail_type][language]
    except KeyError as ke:
        raise ValueError(f"No valid workflow target. {mail_type}") from ke
    logger.debug(
        "Generating an email subject with the following params:",
        subject=subject,
        language=language,
        target=mail_type,
        ticket_id=ticket_id,
    )

    return subject


def send_mail(
    confirmation_mail: ConfirmationMail, attachments: list[MailAttachment] = [], allow_unsupervised: bool = False
) -> MIMEMultipart:
    """

    Send E-mail
    """
    message = make_mime_mail(confirmation_mail, attachments, allow_unsupervised)
    if mail_settings.MAIL_ENABLED:
        logger.debug("Sending an email", message=message)
        mailer = SMTP(host=mail_settings.MAIL_SERVER, port=mail_settings.MAIL_PORT)
        if mail_settings.MAIL_STARTTLS:
            mailer.starttls()
        if mail_settings.MAIL_SMTP_USERNAME and mail_settings.MAIL_SMTP_PASSWORD:
            mailer.login(user=mail_settings.MAIL_SMTP_USERNAME, password=mail_settings.MAIL_SMTP_PASSWORD)
        mailer.send_message(message)
        mailer.quit()
    return message


def make_mime_mail(
    confirmation_mail: ConfirmationMail, attachments: list[MailAttachment] = [], allow_unsupervised: bool = False
) -> MIMEMultipart:
    """
    The MIME body has the following structure:
    * mixed
      * alternative
        * plain text
        * related
          * html
          * inline image 1
          * inline image n
      * attachment 1
      * attachment n
    """
    if not confirmation_mail["to"]:
        raise ValueError("No recipients")
    if not (confirmation_mail["bcc"]) and not allow_unsupervised:
        raise ValueError("No CC or BCC list. Unsupervised mailing not advised (yet).")

    plain_text_message = html2text.HTML2Text()
    plain_text_message.unicode_snob = True
    plain_text_message.ignore_emphasis = True
    plain_text_message.single_line_break = True
    plain_text = MIMEText(plain_text_message.handle(confirmation_mail["message"]), _subtype="plain")

    message = MIMEMultipart(_subtype="mixed")

    message_from = confirmation_mail.get("sender", {}).get("email", mail_settings.MAIL_FROM)
    message["From"] = message_from
    message["Sender"] = message_from
    message["Reply-To"] = message_from
    message["Subject"] = confirmation_mail["subject"]
    message["To"] = ",".join([r["email"] for r in confirmation_mail["to"]])
    cc = ",".join([r["email"] for r in confirmation_mail["cc"]])
    if cc:
        message["Cc"] = cc
    bcc = ",".join([r["email"] for r in confirmation_mail["bcc"]])
    if bcc:
        message["Bcc"] = bcc

    related = MIMEMultipart(_subtype="related")
    related.attach(MIMEText(confirmation_mail["message"], _subtype="html"))

    for image in confirmation_mail.get("images", []):
        with open(os.path.join(os.path.dirname(__file__), "mail_templates/images", image["filename"]), "rb") as file:
            data = file.read()
        img = MIMEImage(data, image["subtype"])
        img.add_header("Content-Id", f"<{image['cid']}>")
        img.add_header("Content-Disposition", "inline", filename=image["filename"])
        related.attach(img)

    alternative = MIMEMultipart(_subtype="alternative")
    alternative.attach(plain_text)
    alternative.attach(related)
    message.attach(alternative)
    for attachment in attachments:
        content_type = attachment["content_type"]
        mime_type = content_type.split("/") if "/" in content_type else ("application", "octet-stream")
        part = MIMEBase(*mime_type)
        part.set_payload(attachment["data"])
        encode_base64(part)
        part.set_param("name", attachment["filename"])
        part.add_header("Content-Disposition", "attachment", filename=attachment["filename"])
        message.attach(part)

    return message


def _generate_mail_intro_for_product_info(
    contact_names: str, product: ProductBase, language: str, summary: str, date: datetime
) -> str:
    env = template_environment(loader)
    template_file = "mail_intro_product_info.html.j2"
    template = env.get_template(f"{language.lower()}/{template_file}")
    return template.render(
        subscription=ProductBase.from_orm(product),
        contact_names=contact_names,
        summary=summary,
        date=date,
    )


# def _generate_mail_intro_for_create_workflow(
#     contact_names: str, model: SubscriptionModel, language: str, summary: str, date: datetime
# ) -> str:
#     env = template_environment(loader)
#     template_file = "mail_intro_create_workflow.html.j2"
#     template = env.get_template(os.path.join(language.lower(), template_file))
#
#     return template.render(
#         subscription=model.model_dump(),
#         contact_names=contact_names,
#         info_link=INFO_LINK,
#         summary=summary,
#         date=date,
#     )
#
#
# def _generate_mail_intro_for_modify_workflow(
#     contact_names: str, model: SubscriptionModel, language: str, summary: str, date: datetime
# ) -> str:
#     env = template_environment(loader)
#
#     template = env.get_template(os.path.join(language.lower(), "mail_intro_modify_workflow.html.j2"))
#     return template.render(
#         subscription=model.model_dump(),
#         contact_names=contact_names,
#         summary=summary,
#         date=date,
#     )
#
#
# def _generate_mail_intro_for_terminate_workflow(
#     contact_names: str, model: SubscriptionModel, language: str, summary: str
# ) -> str:
#     env = template_environment(loader)
#     template = env.get_template(os.path.join(language.lower(), "mail_intro_terminate_workflow.html.j2"))
#     return template.render(subscription=model.model_dump(), contact_names=contact_names, summary=summary)


def generate_confirmation_mail(
    product: ProductBase,
    mail_type: MailType,
    shop_name: str,
    contacts: list[MailAddress],
    ticket_id: str | None,
    extra_content: str | None = None,
    **kwargs: Any,
) -> ConfirmationMail:
    """Generate the complete product specific confirmation_email dict.

    Specific implementations of this generic function will specify the model types they work on. For
    more info about the confirmation email templates please consult: :ref:`email-confirmation-templates`

    Args:
        contacts: a list with contact info (name + email)
        product: Domain model for which to construct a payload.
        mail_type: INFO
        shop_name: name of the shop
        ticket_id: Optional ticket ID (used in subject)
        extra_content: Adds extra text to the main template
        kwargs: Extra arguments, only to be signature compatible

    Returns:
    ---
        A dictionary which contains `message`, `subject`, `to`, `cc` and `language`

    Raises:
    --
        TypeError: in case a specific implementation could not be found. The domain model it was called for will be part of the error message.
        ValueError: in case error occurred whilst determining the recipients or during the generation of the message or subject.
    """
    # Todo: Decide if language support is "generic", we only have dutch customer now.
    # Todo: Defaulting to NL for now.
    language = "NL"
    subject = _generate_subject(
        mail_type, product=product.translation.main_name, shop=shop_name, language=language, ticket_id=ticket_id
    )
    summary = generate_product_summary(ProductBase.from_orm(product), extra_content)

    contact_names = ", ".join([contact["name"] for contact in contacts])

    match mail_type:
        case MailType.INFO:
            body = _generate_mail_intro_for_product_info(contact_names, product, language, summary, nowtz())
        case _:
            raise ValueError(f"Unsupported target: {mail_type}")

    confirmation_mail: ConfirmationMail = {
        "message": body,
        "subject": subject,
        "to": contacts,
        "cc": [],
        "bcc": BCC,
        "language": language,
        "images": IMAGES_SHOP_VIRGE,
    }

    logger.info("Generated mail", language=language, subject=subject, target=mail_type)
    return confirmation_mail


@singledispatch
def generate_product_summary(model: ProductBase, extra_content: str | None = None) -> str:
    """Generate and return a HTML representation of a product summary.

    Specific implementations of this generic function will specify the model types they work on. For
    more info about the confirmation email templates please consult: :ref:`email-confirmation-templates`

    Args:
        product: Domain model for which to construct a payload.
        extra_content: Optional str to add extra text above the summary

    Returns:
    ---
        ProductTable summary in HTML

    Raises:
    --
        TypeError: in case a specific implementation could not be found. The domain model it was called for will be part of the error message.
        ValueError: in case error occurred whilst resource types couldn't be resolved in external systems.

    """
    return single_dispatch_base(generate_product_summary, model, extra_content)


@generate_product_summary.register
def shop_product_summary(product: ProductBase, extra_content: str | None = None) -> str:
    """Create and return an ConfirmationMail for :class:`~products.product_types.ntd.NtdProvisioning`.

    Args:
        model: NtdProvisioning
        extra_content: Optional str to add extra text above the summary
        kwargs: Extra arguments, only to be signature compatible

    Returns: HTML string
    """
    labels = {
        # section headers
        "title": product.translation.main_name,
        "product": "Product",
        # data fields
        "name": "Naam",
        "short_description": "Korte Beschrijving",
        "price": "Prijs",
        "category": "Categorie",
    }
    # Map domain model data to labels
    data = {
        "name": product.translation.main_name,
        "short_description": product.translation.main_description_short,
        "price": product.price,
        "category": product.category_id,
    }

    # Group data in to sections
    section_fields = {
        "product": ["name", "short_description", "price", "category"],
    }
    sections = ["product"]

    template = get_template_for_product_summary("product_summary.html.j2")
    return template.render(
        subscription=product.model_dump(),
        sections=sections,
        section_fields=section_fields,
        data=data,
        labels=labels,
        extra_content=extra_content,
    )


def _map_language(language_name: str) -> str:
    """Map a language name from shop config to a template folder code."""
    mapping = {
        "nederlands": "NL",
        "dutch": "NL",
        "nl": "NL",
        "english": "EN",
        "en": "EN",
        "engels": "EN",
        "deutsch": "DE",
        "german": "DE",
        "de": "DE",
    }
    return mapping.get(language_name.lower().strip(), "NL")


def _compute_order_lines_for_email(order_info: list[dict], shop: Any) -> list[dict]:
    """Build enriched order line dicts with VAT and attribute info for email templates."""
    from server.crud.crud_product import product_crud
    from server.services.shipping import resolve_vat_rate

    lines = []
    for item in order_info:
        product = product_crud.get_id_by_shop_id(shop.id, item["product_id"])

        vat_rate = resolve_vat_rate(product, shop)

        # order_info prices are VAT-inclusive (they match the catalog price the
        # customer sees in the shop). Derive the ex-VAT figures by dividing out
        # the rate, and keep the inc-VAT line total as the authoritative value
        # so shown totals match what the customer paid.
        quantity = item.get("quantity", 1)
        price_inc = item["price"]
        vat_divisor = 1 + vat_rate / 100
        price_ex = round(price_inc / vat_divisor, 2)
        line_total_inc = round(price_inc * quantity, 2)
        line_total_ex = round(line_total_inc / vat_divisor, 2)

        # Collect product attributes
        attributes = []
        if product and hasattr(product, "attribute_values") and product.attribute_values:
            for av in product.attribute_values:
                attr_name = av.attribute.name
                if av.attribute.translation and av.attribute.translation.main_name:
                    attr_name = av.attribute.translation.main_name
                attr_value = av.option.value_key if av.option else ""
                attr_unit = av.attribute.unit or ""
                attributes.append({"name": attr_name, "value": attr_value, "unit": attr_unit})

        lines.append(
            {
                "product_name": item.get("product_name", "Unknown product"),
                "description": item.get("description"),
                "attributes": attributes,
                "quantity": quantity,
                "price_ex_btw": price_ex,
                "price_inc_btw": price_inc,
                "btw_rate": vat_rate,
                "line_total_ex_btw": line_total_ex,
                "line_total_inc_btw": line_total_inc,
            }
        )
    return lines


def send_order_confirmation_emails(order: Any, shop: Any, account: Any) -> None:
    """Send order confirmation emails to both customer and shop owner.

    Args:
        order: OrderTable instance with order_info, customer_order_id, completed_at
        shop: ShopTable instance with config (contact, legal, languages) and VAT rates
        account: Account instance with name (customer email) and details (optional business info)
    """
    try:
        config = shop.config
        contact = config.get("contact", {})
        legal = config.get("legal") or {}

        # Determine language from shop config
        language = "NL"
        languages_config = config.get("languages", {})
        main_lang = languages_config.get("main", {})
        if main_lang.get("language_name"):
            language = _map_language(main_lang["language_name"])

        # Build order lines with VAT and attribute data
        order_lines = _compute_order_lines_for_email(order.order_info, shop)

        # Compute item totals
        items_total_ex_btw = round(sum(line["line_total_ex_btw"] for line in order_lines), 2)
        items_total_inc_btw = round(sum(line["line_total_inc_btw"] for line in order_lines), 2)

        # Build shipping lines (one per VAT rate) using the same allocation logic
        # the order create endpoint used. Persisted on the order as a single
        # inc-VAT figure; we re-derive the per-rate split for display.
        shipping_fee_inc_btw = getattr(order, "shipping_fee_inc_btw", None)
        shipping_lines: list[dict] = []
        shipping_total_ex_btw = 0.0
        shipping_total_inc_btw = 0.0
        if shipping_fee_inc_btw is not None and shipping_fee_inc_btw > 0:
            from server.services.shipping import allocate_shipping_lines, build_rate_subtotals

            rate_subtotals = build_rate_subtotals(order.order_info, shop)
            for sl in allocate_shipping_lines(shipping_fee_inc_btw, rate_subtotals):
                shipping_lines.append(
                    {
                        "btw_rate": sl.btw_rate,
                        "amount_ex_btw": sl.amount_ex_btw,
                        "amount_inc_btw": sl.amount_inc_btw,
                        "amount_btw": sl.amount_btw,
                    }
                )
            shipping_total_ex_btw = round(sum(line["amount_ex_btw"] for line in shipping_lines), 2)
            shipping_total_inc_btw = round(shipping_fee_inc_btw, 2)

        total_ex_btw = round(items_total_ex_btw + shipping_total_ex_btw, 2)
        total_inc_btw = round(items_total_inc_btw + shipping_total_inc_btw, 2)
        total_btw = round(total_inc_btw - total_ex_btw, 2)

        # Extract business info from account details
        account_details = account.details or {} if account.details else {}
        customer_company_name = account_details.get("company_name")
        customer_btw_number = account_details.get("btw_number")

        # Format completion date. `completed_at` is stored as a naive UTC timestamp
        # (DateTime column without timezone=True); for NL mails we render it in
        # Europe/Amsterdam so the date shown to customers matches their local clock.
        completed_at_str = ""
        if order.completed_at:
            completed_at_dt = order.completed_at
            if completed_at_dt.tzinfo is None:
                completed_at_dt = completed_at_dt.replace(tzinfo=timezone.utc)
            if language == "NL":
                completed_at_dt = completed_at_dt.astimezone(ZoneInfo("Europe/Amsterdam"))
            completed_at_str = completed_at_dt.strftime("%d-%m-%Y %H:%M")

        # Common template variables
        template_vars = {
            "customer_order_id": order.customer_order_id,
            "customer_email": account.name,
            "order_lines": order_lines,
            "shipping_lines": shipping_lines,
            "shipping_fee_inc_btw": shipping_fee_inc_btw,
            "total_ex_btw": total_ex_btw,
            "total_inc_btw": total_inc_btw,
            "total_btw": total_btw,
            "shop_name": shop.name,
            "shop_company": contact.get("company", shop.name),
            "shop_address": contact.get("address", ""),
            "shop_zip_code": contact.get("zip_code", ""),
            "shop_city": contact.get("city", ""),
            "shop_phone": contact.get("phone", ""),
            "shop_email": contact.get("email", ""),
            "kvk_number": legal.get("kvk_number"),
            "btw_number": legal.get("btw_number"),
            "customer_company_name": customer_company_name,
            "customer_btw_number": customer_btw_number,
            "completed_at": completed_at_str,
        }

        env = template_environment(loader)
        lang_folder = language.lower()

        # Send customer email
        customer_template = env.get_template(f"{lang_folder}/mail_order_confirmation_customer.html.j2")
        customer_body = customer_template.render(**template_vars)

        subject_prefix_customer = {
            "NL": f"Orderbevestiging #{order.customer_order_id} - {shop.name}",
            "EN": f"Order confirmation #{order.customer_order_id} - {shop.name}",
        }

        customer_mail: ConfirmationMail = {
            "message": customer_body,
            "subject": subject_prefix_customer.get(language, subject_prefix_customer["NL"]),
            "to": [{"email": account.name, "name": account.name}],
            "cc": [],
            "bcc": BCC,
            "language": language,
            "images": IMAGES_SHOP_VIRGE,
        }
        send_mail(customer_mail)
        logger.info("Sent order confirmation to customer", order_id=str(order.id), customer=account.name)

        # Send shop owner email
        owner_email = contact.get("email")
        if owner_email:
            owner_template = env.get_template(f"{lang_folder}/mail_order_confirmation_owner.html.j2")
            owner_body = owner_template.render(**template_vars)

            subject_prefix_owner = {
                "NL": f"Nieuwe bestelling #{order.customer_order_id} - {shop.name}",
                "EN": f"New order #{order.customer_order_id} - {shop.name}",
            }

            owner_mail: ConfirmationMail = {
                "message": owner_body,
                "subject": subject_prefix_owner.get(language, subject_prefix_owner["NL"]),
                "to": [{"email": owner_email, "name": contact.get("company", shop.name)}],
                "cc": [],
                "bcc": BCC,
                "language": language,
                "images": IMAGES_SHOP_VIRGE,
            }
            send_mail(owner_mail)
            logger.info("Sent order notification to shop owner", order_id=str(order.id), owner=owner_email)

            subject_prefix_customer_copy = {
                "NL": f"[KOPIE klantmail] Orderbevestiging #{order.customer_order_id} - {shop.name}",
                "EN": f"[COPY of customer mail] Order confirmation #{order.customer_order_id} - {shop.name}",
            }

            owner_customer_copy_mail: ConfirmationMail = {
                "message": customer_body,
                "subject": subject_prefix_customer_copy.get(language, subject_prefix_customer_copy["NL"]),
                "to": [{"email": owner_email, "name": contact.get("company", shop.name)}],
                "cc": [],
                "bcc": BCC,
                "language": language,
                "images": IMAGES_SHOP_VIRGE,
            }
            send_mail(owner_customer_copy_mail)
            logger.info("Sent customer-mail copy to shop owner", order_id=str(order.id), owner=owner_email)
        else:
            logger.warning("No shop owner email configured, skipping owner notification", shop_id=str(shop.id))

    except Exception as e:
        logger.error("Failed to send order confirmation emails", error=str(e), order_id=str(order.id))
