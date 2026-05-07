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
from typing import Dict, List, Union

from fastapi.param_functions import Query


async def common_parameters(
    skip: int = 0,
    limit: int = 100,
    filter: List[str] = Query(
        None,
        description="This filter can accept search query's like `key:value` and will split on the `:`. If it "
        "detects more than one `:`, or does not find a `:` it will search for the string in all columns.",
    ),
    sort: List[str] = Query(
        None,
        description="The sort will accept parameters like `col:ASC` or `col:DESC` and will split on the `:`. "
        "If it does not find a `:` it will sort ascending on that column.",
    ),
) -> Dict[str, Union[List[str], int]]:
    return {"skip": skip, "limit": limit, "filter": filter, "sort": sort}
