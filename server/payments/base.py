# Copyright 2026 René Dohmen <acidjunk@gmail.com>
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
"""Payment provider interface and the normalized objects providers speak in."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Literal, Optional

from fastapi import Request

from server.db.models import OrderTable, PaymentTable, ShopTable


class PaymentProviderError(Exception):
    """Base for everything a provider can raise; endpoints map it to HTTP errors."""


class PaymentProviderNotConfigured(PaymentProviderError):
    """The shop lacks the credentials/config needed by the selected provider."""


class PaymentWebhookInvalid(PaymentProviderError):
    """The webhook request failed verification (bad signature, garbled payload)."""


class PaymentStatus(str, Enum):
    """Normalized payment lifecycle every provider's native statuses map onto."""

    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"

    @property
    def is_terminal(self) -> bool:
        return self in (PaymentStatus.PAID, PaymentStatus.FAILED, PaymentStatus.CANCELED, PaymentStatus.EXPIRED)


PaymentFlow = Literal["redirect", "client_confirmation"]


@dataclass
class PaymentSession:
    """What the frontend needs to take a freshly created payment further.

    ``flow`` tells it how: ``redirect`` means send the browser to
    ``redirect_url`` (hosted checkout — Mollie); ``client_confirmation`` means
    confirm in-page with ``client_secret``/``publishable_key`` (Stripe
    Elements).
    """

    provider_payment_id: str
    status: PaymentStatus
    flow: PaymentFlow
    redirect_url: Optional[str] = None
    client_secret: Optional[str] = None
    publishable_key: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


@dataclass
class PaymentEvent:
    """A verified, normalized status report about one provider payment."""

    provider_payment_id: str
    status: PaymentStatus
    raw: Optional[Dict[str, Any]] = None


class PaymentProvider(ABC):
    """One PSP integration. Stateless: per-shop credentials are resolved per call."""

    id: str

    @abstractmethod
    def create_payment(
        self, *, shop: ShopTable, order: OrderTable, payment: PaymentTable, return_url: str
    ) -> PaymentSession:
        """Create the payment at the PSP for ``order.total``.

        ``payment`` is our already-persisted PaymentTable row; providers put
        its id (and the order id) in PSP metadata so webhooks can be matched
        back. Raises :class:`PaymentProviderNotConfigured` when the shop has
        no usable credentials.
        """

    @abstractmethod
    async def handle_webhook(self, *, shop: ShopTable, request: Request) -> Optional[PaymentEvent]:
        """Verify an incoming webhook and normalize it.

        Returns ``None`` for events that are valid but irrelevant (e.g. a
        Stripe event type we don't act on). Raises
        :class:`PaymentWebhookInvalid` when verification fails.
        """

    @abstractmethod
    def get_status(self, *, shop: ShopTable, provider_payment_id: str) -> PaymentEvent:
        """Fetch the current status from the PSP (poll-time sync / webhook fallback)."""
