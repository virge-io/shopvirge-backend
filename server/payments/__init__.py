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
"""Pluggable payment providers.

A provider turns a (shop, order) pair into a normalized ``PaymentSession``
the frontend can act on without knowing which PSP is behind it, and turns
provider webhooks/polls into normalized ``PaymentEvent``s that drive the
order lifecycle. Select a provider per shop via ``ShopTable.payment_provider``
and resolve it with :func:`server.payments.registry.get_provider`.
"""
