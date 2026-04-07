# Walk-in profile backfill and verification

## When to use

Run `backfill_walkin_profiles` when historical `SlaughterOrder` rows have walk-in name and phone filled but `client` is null (legacy data or failed prospect creation). The command creates or reuses a manageable `ClientProfile` per normalized phone and links matching orders.

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
