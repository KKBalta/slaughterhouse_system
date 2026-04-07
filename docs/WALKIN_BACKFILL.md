# Walk-in profile backfill and verification

## When to use

Run `backfill_walkin_profiles` when historical `SlaughterOrder` rows have walk-in name and phone filled but `client` is null (legacy data or failed prospect creation). The command creates or reuses a manageable `ClientProfile` per normalized phone and links matching orders.

## Account type (UNCLASSIFIED)

New profiles are created with **`ClientProfile.account_type = UNCLASSIFIED`** and a **`User` with `role = WALKIN`** (walk-in prospect), matching live reception intake. Those records show up in **Users / client management** as unclassified prospects that staff can open and edit (e.g. upgrade to Individual or Enterprise). If an existing walk-in prospect profile is reused but had a different `account_type`, the backfill normalizes it back to **UNCLASSIFIED** when the linked user is still `WALKIN`.

## Commands

Preview without committing (multitenant example):

```bash
python manage.py backfill_walkin_profiles --dry-run
```

Limit to specific tenant schemas:

```bash
python manage.py backfill_walkin_profiles --schema your_tenant_schema
```

Apply migrations first in multitenant setups (`migrate_schemas`).

## Verifying data (Django shell)

Walk-in orders that still have no linked client:

```python
from reception.models import SlaughterOrder
SlaughterOrder.objects.filter(
    client__isnull=True,
).exclude(client_name="").exclude(client_phone="").count()
```

Inspect a sample:

```python
list(
    SlaughterOrder.objects.filter(client__isnull=True)
    .exclude(client_name="")
    .exclude(client_phone="")
    .values("id", "client_name", "client_phone")[:5]
)
```
