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

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Union

from pydantic import BaseModel, PlainSerializer


def quantize_money(value: Union[Decimal, int, float, str], places: int = 2) -> Decimal:
    """Quantize a value to ``places`` decimal places using ROUND_HALF_UP.

    Accepts Decimal, int, float, or string. Floats are converted via ``str()``
    first to avoid binary-representation noise (e.g. ``Decimal(0.1)`` carries
    the float artefact, but ``Decimal(str(0.1))`` is exact).
    """
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(10) ** -places
    return value.quantize(q, rounding=ROUND_HALF_UP)


# Money: Decimal internally, but JSON-serialized as a number (not a string) so
# the wire format stays backward compatible with clients that expect floats.
Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]


class BoilerplateBaseModel(BaseModel):
    class Config:
        pass
        # Commented because returns Float for shop.modified_at. Needed datetime
        # json_encoders = {
        #     # Add custom decoders that you need here
        #     datetime: lambda dt: dt.timestamp(),
        # }
