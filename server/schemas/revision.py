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
from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RevisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: UUID
    revision_no: int
    action: str
    schema_version: int
    created_by: Optional[str] = None
    source: str
    created_at: Optional[datetime] = None
    # Human-readable label extracted from the snapshot (e.g. the product name at that point)
    name: Optional[str] = None


class RevisionDetail(RevisionSummary):
    data: dict


class UnresolvedReference(BaseModel):
    kind: str  # 'category' | 'tag' | 'attribute' | 'attribute_option'
    id: Optional[UUID] = None
    name: Optional[str] = None


class ResurrectedEntity(BaseModel):
    kind: str  # 'category' | 'tag' | 'attribute' | 'attribute_option' | 'product'
    id: UUID
    name: Optional[str] = None


class RestoreReport(BaseModel):
    """What a restore actually did — agents should read this to see what didn't come back."""

    restored: bool
    entity_type: str
    entity_id: UUID
    restored_from_revision_no: Optional[int] = None
    new_revision_no: Optional[int] = None
    # Soft-deleted related entities that were brought back to make the restore complete
    resurrected: List[ResurrectedEntity] = []
    # Snapshot fields that no longer exist on the current model and were skipped
    skipped_fields: List[str] = []
    # Snapshot references (category/tags/attributes) that could not be matched by id or name
    unresolved: List[UnresolvedReference] = []
    warnings: List[str] = []


class TrashItem(BaseModel):
    entity_type: str
    id: UUID
    name: Optional[str] = None
    deleted_at: Optional[datetime] = None
    deleted_batch_id: Optional[UUID] = None
