---
title: Forms
description: Pydantic-based form endpoints in ShopVirge Backend, including the generic /forms router and the public info-request form flow.
---

# Forms

ShopVirge Backend exposes a small form API built on top of
[`pydantic-forms`](https://pydantic-forms.readthedocs.io/en/latest/).
These endpoints return or advance form pages that are defined with Pydantic
models on the backend, so the frontend can render them dynamically instead of
hard-coding every input field.

## Why this exists

- The backend owns the form schema.
- The frontend submits a list of field values and receives either the next form page or a completion/error response.
- Validation lives with the backend form definitions, not only in the browser.

For the broader architecture behind this style of backend-owned forms, use the
workflow-orchestrator docs first:

- [Domain models](https://github.com/workfloworchestrator/orchestrator-core/blob/main/docs/architecture/application/domainmodels.md)
- [Forms reference](https://workfloworchestrator.org/orchestrator-core/reference-docs/forms/)
- [Custom form fields](https://workfloworchestrator.org/orchestrator-core/reference-docs/forms/?h=forms#custom-form-fields)

Those pages are a better conceptual fit for this backend than the low-level
Pydantic docs alone, because they describe the form-flow and model patterns that
this API is closer to.

One caveat: the Workflow Orchestrator page itself marks the `Custom Form Fields`
section as out of date after the migration from `uniforms` to `pydantic-forms`,
so use that section as a conceptual reference rather than as exact current UI
implementation guidance.

For the actual frontend/UI implementation side of the `pydantic-forms`
ecosystem, this repo is also worth linking:

- [workfloworchestrator/pydantic-forms-ui](https://github.com/workfloworchestrator/pydantic-forms-ui)

For the Python/backend library itself, this source repository is also useful:

- [workfloworchestrator/pydantic-forms](https://github.com/workfloworchestrator/pydantic-forms)

## Route families

### `GET /forms`

Lists the registered backend form keys.

Implementation:

- `server/api/endpoints/forms.py`
- `pydantic_forms.core.list_forms`

Authentication:

- Protected by `auth_required`

### `POST /forms/{form_key}`

Starts or advances a registered backend form workflow.

Request body:

- `list[dict]` user inputs collected so far

Optional query params:

- `shop_id`

Implementation:

- `server/api/endpoints/forms.py`
- `pydantic_forms.core.asynchronous.start_form`
- `server/forms/__init__.py` to register available forms

Current registered form keys come from `server/forms/new_product_form.py`:

- `create_tag_form`
- `create_product_form`
- `create_categorie_form`

The last key is spelled `categorie` in code today, so the docs keep that exact
name instead of silently correcting it.

### `POST /info-request/form`

Public product info-request form endpoint used by the storefront.

Query params:

- `shop_id`
- `product_id`

Request body:

- `list[dict]` submitted form values

Implementation:

- `server/api/endpoints/shop_endpoints/info_request.py`
- `pydantic_forms.core.post_form`

This endpoint defines a simple one-page form with a Pydantic `EmailStr` field,
validates the submitted payload, and then creates an `InfoRequest` record plus
the follow-up side effects:

- optional Discord notification
- optional confirmation email

### `POST /test-forms`

Internal/demo endpoint for exercising multi-page `pydantic-forms` behavior.

Implementation:

- `server/api/endpoints/test_forms.py`

This is useful for development and experimentation, but it should not be
treated as a stable storefront contract.

## How the backend models a form

Two patterns are used in this codebase:

### Generic registered forms

The `/forms/{form_key}` router loads generator-based workflows from
`server/forms/`.

Those form workflows:

- define `FormPage` subclasses with Pydantic fields
- yield pages one by one
- use validators to keep business rules near the schema
- can use extra state such as `shop_id`

### Inline endpoint-specific forms

The `/info-request/form` and `/test-forms` endpoints define `FormPage`
subclasses directly inside the route handler and pass them through
`post_form(...)`.

That pattern is useful when a form is tightly coupled to a single endpoint and
does not need to be registered globally.

## Validation and error handling

Form validation errors raise `FormException`.
`server/main.py` registers `pydantic_forms.exception_handlers.fastapi.form_error_handler`,
so form failures are returned as structured API errors instead of raw tracebacks.

Relevant source:

- `server/main.py`
- `server/exception_handlers.py`

## Example flows

### Start a registered form

```bash
curl -X GET http://localhost:8000/forms \
  -H 'Authorization: Bearer <token>'
```

```bash
curl -X POST 'http://localhost:8000/forms/create_product_form?shop_id=<shop_uuid>' \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '[]'
```

### Start the public info-request form

```bash
curl -X POST 'http://localhost:8000/info-request/form?shop_id=<shop_uuid>&product_id=<product_uuid>' \
  -H 'Content-Type: application/json' \
  -d '[]'
```

### Submit the info-request email

```bash
curl -X POST 'http://localhost:8000/info-request/form?shop_id=<shop_uuid>&product_id=<product_uuid>' \
  -H 'Content-Type: application/json' \
  -d '[{"email":"customer@example.com"}]'
```

Use `/docs` or `/openapi.json` for the exact live response payloads, since the
shape depends on the current `pydantic-forms` library behavior.

## External references

- [Workflow Orchestrator domain models](https://github.com/workfloworchestrator/orchestrator-core/blob/main/docs/architecture/application/domainmodels.md)
- [Workflow Orchestrator forms reference](https://workfloworchestrator.org/orchestrator-core/reference-docs/forms/)
- [Workflow Orchestrator custom form fields](https://workfloworchestrator.org/orchestrator-core/reference-docs/forms/?h=forms#custom-form-fields)
- [workfloworchestrator/pydantic-forms](https://github.com/workfloworchestrator/pydantic-forms)
- [workfloworchestrator/pydantic-forms-ui](https://github.com/workfloworchestrator/pydantic-forms-ui)
- [pydantic-forms docs](https://pydantic-forms.readthedocs.io/en/latest/)
- [pydantic-forms package](https://pypi.org/project/pydantic-forms/)
- [Pydantic docs](https://docs.pydantic.dev/)
