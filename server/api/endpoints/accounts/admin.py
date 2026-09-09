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
"""Cross-shop admin endpoints for investigating accounts and Stripe state.

Mounted at ``/admin/accounts``. All handlers require membership of the
Cognito ``Admins`` group (M2M tokens are trusted) via
``Depends(admin_required)``. The shop-scoped ``/shops/{shop_id}/accounts``
routes remain the standard read/write path for end-user shops; this
router exists so an admin can:

* see accounts across every shop in one place,
* identify accounts that are missing a Stripe linkage,
* manually link an existing Stripe customer id to a local account, and
* pull a fresh Stripe ``Customer`` snapshot into ``Account.details``.
"""

from datetime import datetime, timezone
from http import HTTPStatus
from typing import List, Optional
from uuid import UUID

import stripe
import structlog
from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from starlette.responses import Response

from server.api.deps import common_parameters
from server.api.error_handling import raise_status
from server.crud.crud_account import account_crud
from server.db import db
from server.db.models import Account
from server.schemas.admin_account import (
    AdminAccountSchema,
    LinkStripeBody,
    SyncStripeResponse,
    build_admin_account,
)
from server.security import admin_required
from server.services import stripe_client
from server.services.stripe_client import StripeCustomerMissing, StripeNotConfigured

logger = structlog.get_logger(__name__)

router = APIRouter()


def _load_account_or_404(id: UUID) -> Account:
    account = account_crud.get(id)
    if not account:
        raise_status(HTTPStatus.NOT_FOUND, f"Account with id {id} not found")
    return account


def _require_linked_shop(account: Account) -> None:
    if account.shop_id is None or account.shop is None:
        raise_status(
            HTTPStatus.BAD_REQUEST,
            f"Account {account.id} is not linked to a shop",
        )


@router.get(
    "",
    response_model=List[AdminAccountSchema],
    summary="List accounts (admin)",
    description=(
        "List all customer accounts across every shop. Optionally filter by `shop_id` or "
        "by Stripe linkage status (`missing_stripe=true` returns accounts without a Stripe customer ID). "
        "Requires membership of the Cognito Admins group."
    ),
    responses={HTTPStatus.FORBIDDEN.value: {"description": "Not a member of the Admins group"}},
)
def list_accounts(
    response: Response,
    shop_id: Optional[UUID] = Query(None, description="Restrict to a single shop"),
    missing_stripe: Optional[bool] = Query(
        None,
        description="If true, only accounts without a stripe_customer_id; if false, only those with one.",
    ),
    common: dict = Depends(common_parameters),
    _: object = Depends(admin_required),
) -> List[AdminAccountSchema]:
    query = db.session.query(Account).options(joinedload(Account.shop))

    if shop_id is not None:
        query = query.filter(Account.shop_id == shop_id)

    if missing_stripe is True:
        # The ``->>`` operator returns NULL when the key is absent or the
        # value is JSON null; combined with the IS NULL check on details
        # itself this also covers accounts whose details column is unset.
        query = query.filter(
            or_(
                Account.details.is_(None),
                Account.details.op("->>")("stripe_customer_id").is_(None),
            )
        )
    elif missing_stripe is False:
        query = query.filter(Account.details.op("->>")("stripe_customer_id").isnot(None))

    accounts, header_range = account_crud.get_multi(
        skip=common["skip"],
        limit=common["limit"],
        filter_parameters=common["filter"],
        sort_parameters=common["sort"],
        query_parameter=query,
    )
    response.headers["Content-Range"] = header_range
    return [build_admin_account(a) for a in accounts]


@router.get(
    "/{id}",
    response_model=AdminAccountSchema,
    summary="Get account (admin)",
    description="Retrieve a single account by UUID, including its Stripe metadata. Requires Admins group membership.",
    responses={
        HTTPStatus.FORBIDDEN.value: {"description": "Not a member of the Admins group"},
        HTTPStatus.NOT_FOUND.value: {"description": "Account not found"},
    },
)
def get_account(
    id: UUID,
    _: object = Depends(admin_required),
) -> AdminAccountSchema:
    account = _load_account_or_404(id)
    return build_admin_account(account)


@router.get(
    "/{id}/stripe-customer",
    summary="Fetch Stripe customer (admin)",
    description="Read-through to Stripe: returns the live Stripe Customer object for this account. Does not persist anything — use POST /sync-stripe to save the snapshot.",
    responses={
        HTTPStatus.FORBIDDEN.value: {"description": "Not a member of the Admins group"},
        HTTPStatus.NOT_FOUND.value: {"description": "Account not found"},
        HTTPStatus.BAD_REQUEST.value: {"description": "Account or shop not configured for Stripe"},
        HTTPStatus.BAD_GATEWAY.value: {"description": "Stripe API error"},
    },
)
def get_stripe_customer(
    id: UUID,
    _: object = Depends(admin_required),
) -> dict:
    """Read-through: fetch the Stripe customer for this account.

    Does NOT persist anything; use ``POST /sync-stripe`` to write the
    snapshot back into the account's ``details`` column.
    """
    account = _load_account_or_404(id)
    _require_linked_shop(account)

    try:
        customer_id = stripe_client.get_customer_id(account)
    except StripeCustomerMissing as exc:
        raise_status(HTTPStatus.BAD_REQUEST, str(exc))

    try:
        customer = stripe_client.fetch_customer(account.shop, customer_id)
    except StripeNotConfigured as exc:
        raise_status(HTTPStatus.BAD_REQUEST, str(exc))
    except stripe.error.StripeError as exc:
        logger.warning("Stripe error fetching customer", account_id=str(id), error=str(exc))
        raise_status(HTTPStatus.BAD_GATEWAY, f"Stripe error: {exc}")

    return {
        "account_id": str(id),
        "stripe_customer_id": customer_id,
        "stripe_customer": customer,
    }


@router.post(
    "/{id}/sync-stripe",
    response_model=SyncStripeResponse,
    summary="Sync Stripe customer snapshot (admin)",
    description="Fetch the Stripe Customer and persist it in `Account.details` (`stripe_customer` + `stripe_synced_at`). Existing details keys are preserved.",
    responses={
        HTTPStatus.FORBIDDEN.value: {"description": "Not a member of the Admins group"},
        HTTPStatus.NOT_FOUND.value: {"description": "Account not found"},
        HTTPStatus.BAD_REQUEST.value: {"description": "Account or shop not configured for Stripe"},
        HTTPStatus.BAD_GATEWAY.value: {"description": "Stripe API error"},
    },
)
def sync_stripe(
    id: UUID,
    _: object = Depends(admin_required),
) -> SyncStripeResponse:
    """Pull the Stripe customer snapshot and persist it on the account.

    Writes ``details["stripe_customer"]`` (the full Stripe payload) and
    ``details["stripe_synced_at"]`` (ISO timestamp). Existing keys in
    ``details`` are preserved.
    """
    account = _load_account_or_404(id)
    _require_linked_shop(account)

    try:
        customer_id = stripe_client.get_customer_id(account)
    except StripeCustomerMissing as exc:
        raise_status(HTTPStatus.BAD_REQUEST, str(exc))

    try:
        customer = stripe_client.fetch_customer(account.shop, customer_id)
    except StripeNotConfigured as exc:
        raise_status(HTTPStatus.BAD_REQUEST, str(exc))
    except stripe.error.StripeError as exc:
        logger.warning("Stripe error during sync", account_id=str(id), error=str(exc))
        raise_status(HTTPStatus.BAD_GATEWAY, f"Stripe error: {exc}")

    synced_at = datetime.now(timezone.utc)
    # SQLAlchemy's change detection on ``JSON`` columns is identity-based,
    # so assign a NEW dict instead of mutating ``account.details`` in place.
    new_details = dict(account.details or {})
    new_details["stripe_customer"] = customer
    new_details["stripe_synced_at"] = synced_at.isoformat()
    account.details = new_details

    db.session.add(account)
    db.session.commit()
    db.session.refresh(account)

    return SyncStripeResponse(
        id=account.id,
        stripe_customer_id=customer_id,
        stripe_synced_at=synced_at,
        stripe_customer=customer,
    )


@router.post(
    "/{id}/link-stripe",
    response_model=AdminAccountSchema,
    summary="Link Stripe customer ID (admin)",
    description="Manually associate an existing Stripe customer ID with a local account. Follow up with POST /sync-stripe to pull the full snapshot.",
    responses={
        HTTPStatus.FORBIDDEN.value: {"description": "Not a member of the Admins group"},
        HTTPStatus.NOT_FOUND.value: {"description": "Account not found"},
    },
)
def link_stripe(
    id: UUID,
    body: LinkStripeBody = Body(...),
    _: object = Depends(admin_required),
) -> AdminAccountSchema:
    """Manually associate a Stripe customer id with an account.

    Useful for reconciling local records that pre-date the
    auto-customer-create flow. This does NOT call Stripe; follow up
    with ``POST /sync-stripe`` to pull the snapshot.
    """
    account = _load_account_or_404(id)

    new_details = dict(account.details or {})
    new_details["stripe_customer_id"] = body.stripe_customer_id
    account.details = new_details

    db.session.add(account)
    db.session.commit()
    db.session.refresh(account)

    return build_admin_account(account)
