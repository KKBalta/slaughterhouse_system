# Backfilling `tenants.Client` company fields (legacy → multi-tenant)

When upgrading from single-tenant settings (`COMPANY_NAME`, `LICENSE_NO`, etc.) to PostgreSQL + `django-tenants`, each row in `public.tenants_client` should carry the same values you used on labels.

## What to set

| `Client` field        | Former setting / meaning                                      |
|-----------------------|-------------------------------------------------------------|
| `company_name`        | Short name on label header                                  |
| `company_full_name`   | Legal title on labels                                       |
| `company_address`     | Address block on labels / reports                             |
| `license_no`          | İşletme onay no (same as `isletme_onay_no` in label payloads) |
| `operation_no`        | VD / tax office operation number on labels                  |
| `printer_turkish_mode`| `unicode`, `ascii`, or `codepage1254`                       |

## Option A — Django shell (public schema)

```bash
# From project root, with DB env pointing at your Cloud SQL / local Postgres
python manage.py shell
```

```python
from django_tenants.utils import get_public_schema_name, schema_context
from tenants.models import Client

with schema_context(get_public_schema_name()):
    c = Client.objects.get(schema_name="your_tenant_slug")
    c.company_name = "..."
    c.company_full_name = "..."
    c.company_address = "..."
    c.license_no = "17-0509"
    c.operation_no = "4290056890"
    c.save()
```

## Option B — SQL (public schema only)

Connect to the database as a superuser, `SET search_path TO public`, then:

```sql
UPDATE tenants_client
SET
  company_name = 'GUNDOGDULAR GIDA',
  company_full_name = 'SAN VE TUR. TIC. LTD STI',
  company_address = 'BOZALAN - EZINE / CANAKKALE',
  license_no = '17-0509',
  operation_no = '4290056890'
WHERE schema_name = 'your_tenant_slug';
```

Adjust column names if your migration history differs.

## After backfill

- Re-print a test label and confirm TSPL shows the expected **İşletme onay no** line.
- Tenant staff can maintain values at **Dashboard → Company & label settings** (manager+), without SQL.
