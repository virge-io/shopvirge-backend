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
"""Resolve the payment provider for a shop."""

from typing import Dict, Optional

from server.db.models import ShopTable
from server.payments.base import PaymentProvider, PaymentProviderNotConfigured
from server.payments.mollie import MollieProvider
from server.payments.stripe import StripeProvider

PROVIDERS: Dict[str, PaymentProvider] = {provider.id: provider for provider in (StripeProvider(), MollieProvider())}


def get_provider(shop: ShopTable, provider_id: Optional[str] = None) -> PaymentProvider:
    """Return the provider for ``shop``, or the explicitly named one.

    ``provider_id`` is used by webhook routes, where the provider is part of
    the URL and must not depend on the shop's (possibly since-changed)
    configuration. Raises :class:`PaymentProviderNotConfigured` for unknown
    provider names; credential errors surface later, on first provider call.
    """
    name = provider_id or getattr(shop, "payment_provider", None) or "stripe"
    provider = PROVIDERS.get(name)
    if provider is None:
        raise PaymentProviderNotConfigured(f"Unknown payment provider '{name}'")
    return provider
