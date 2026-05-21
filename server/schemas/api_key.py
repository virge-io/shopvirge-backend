# Copyright 2026 René Dohmen <acidjunk@gmail.com>
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
from datetime import datetime
from typing import Optional
from uuid import UUID

from server.schemas.base import BoilerplateBaseModel


class ApiKeyCreate(BoilerplateBaseModel):
    name: str


class ApiKeyRead(BoilerplateBaseModel):
    id: UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ApiKeyCreated(ApiKeyRead):
    """Response from minting a key. ``plaintext`` is shown ONCE — never again."""

    plaintext: str
