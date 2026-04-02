# Email Marketing & Async Job Queue — Implementation Plan

> Status: **Planned — not yet started**
> Prerequisite for: email campaigns, bulk notifications, scheduled reports
> Depends on: Redis (already live as of Phase 0–3)

---

## Background

The system already has Redis running and a session/cache infrastructure in place.
The next logical step before email marketing is a proper async job queue — reports,
email sends, and exports should never block a web worker.

This document covers both the job queue infrastructure and the email marketing
feature built on top of it.

---

## Part 1 — Async Job Queue (django-rq)

### Why django-rq over Celery

| | django-rq | Celery |
|---|---|---|
| Setup complexity | Low — one Redis connection, no broker config | High — broker + backend + worker config |
| Visibility | Built-in Django admin integration | Requires Flower or custom setup |
| Sufficient for | Reports, emails, exports | Complex workflows, chains, chords |
| Overhead | Minimal | Significant |

At CarniTrack's current scale, django-rq is sufficient. Migrate to Celery only if
you need task chaining, rate-limiting per task type, or canvas workflows.

### Installation

```
pip install django-rq
```

**`requirements.txt`** — add:
```
django-rq>=2.10
```

### Settings (`config/settings.py`)

```python
INSTALLED_APPS += ["django_rq"]

RQ_QUEUES = {
    "default": {
        "USE_REDIS_CACHE": "default",   # reuse existing django-redis connection
    },
    "email": {
        "USE_REDIS_CACHE": "default",
        "DEFAULT_TIMEOUT": 300,         # 5 min max per email job
    },
    "reports": {
        "USE_REDIS_CACHE": "default",
        "DEFAULT_TIMEOUT": 600,         # 10 min max per report
    },
}
```

### URL wiring (`config/urls.py`)

```python
path("django-rq/", include("django_rq.urls")),   # staff-only job dashboard
```

Protect with `@staff_member_required` or restrict at the nginx/Cloud Run level.

### Worker

**`Makefile`** — add:
```makefile
worker:
    bash -c 'set -a; . "$(DEV_ENV)"; set +a; $(MANAGE) rqworker default email reports'

worker-staging:
    bash -c 'set -a; . "$(STAGING_ENV)"; set +a; $(MANAGE) rqworker default email reports'
```

**`docker-compose.yml`** — add alongside `redis`:
```yaml
worker:
  build: .
  command: python manage.py rqworker default email reports
  env_file: .env.dev
  depends_on:
    - db
    - redis
```

### Migrating the existing report thread

`reporting/views.py` currently does:
```python
thread = threading.Thread(target=generate_daily_reports, ...)
thread.daemon = True
thread.start()
```

Replace with:
```python
import django_rq
queue = django_rq.get_queue("reports")
job = queue.enqueue(generate_report_task, start_date, end_date, tenant_schema)
return JsonResponse({"job_id": job.id, "status": "queued"})
```

Add a `reporting/tasks.py`:
```python
def generate_report_task(start_date, end_date, tenant_schema):
    from django_tenants.utils import schema_context
    with schema_context(tenant_schema):
        # existing report generation logic
        ...
```

Add a status endpoint:
```python
# GET /reporting/jobs/<job_id>/
def report_job_status(request, job_id):
    import django_rq
    job = django_rq.get_queue("reports").fetch_job(job_id)
    if not job:
        return JsonResponse({"status": "not_found"}, status=404)
    return JsonResponse({
        "status": job.get_status(),   # queued | started | finished | failed
        "result": job.result if job.is_finished else None,
        "error": str(job.exc_info) if job.is_failed else None,
    })
```

---

## Part 2 — Email Marketing Service

### Architecture Overview

```
Django (tenant context)
    │
    ├── Campaign model (tenant-scoped)
    ├── EmailList / Recipient model (tenant-scoped)
    │
    ▼
RQ "email" queue
    │
    ▼
Email provider SDK (SendGrid / Mailchimp / Brevo)
    │
    ▼
Recipient inboxes
```

All email jobs run in tenant context — each tenant's campaigns, recipients, and
send history are isolated in their own schema.

---

### Email Provider Options

| Provider | Best for | Notes |
|----------|----------|-------|
| **SendGrid** | Transactional + marketing | Strong API, good deliverability, Django integration via `sendgrid-python` |
| **Brevo (ex-Sendinblue)** | Cost-effective marketing | Free tier generous, good EU data residency |
| **Mailchimp** | Marketing-focused teams | Better UX for non-technical users; API less flexible |
| **AWS SES** | High volume, low cost | Requires more setup; good if already on AWS |

**Recommendation:** Start with **Brevo** (EU data residency matters for a Turkish/EU food business) or **SendGrid** (best developer experience). Both have Python SDKs and support transactional + bulk sends from the same account.

---

### Django Models (tenant-scoped)

```python
# email_marketing/models.py

class EmailContact(BaseModel):
    """A recipient in a tenant's contact list."""
    email = models.EmailField()
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    is_subscribed = models.BooleanField(default=True)
    unsubscribed_at = models.DateTimeField(null=True, blank=True)
    tags = models.JSONField(default=list)   # e.g. ["client", "vip", "cold_storage"]

    class Meta:
        unique_together = [("email",)]      # per-tenant schema, so no cross-tenant clash


class EmailCampaign(BaseModel):
    """A bulk email send to a set of contacts."""
    name = models.CharField(max_length=200)
    subject = models.CharField(max_length=500)
    body_html = models.TextField()
    body_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=[("draft","Draft"),("scheduled","Scheduled"),
                 ("sending","Sending"),("sent","Sent"),("failed","Failed")],
        default="draft",
    )
    scheduled_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipient_tags = models.JSONField(default=list)   # send to contacts with these tags
    total_recipients = models.IntegerField(default=0)
    sent_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)


class EmailSendLog(BaseModel):
    """Per-recipient send record for tracking opens/bounces."""
    campaign = models.ForeignKey(EmailCampaign, on_delete=models.CASCADE, related_name="send_logs")
    contact = models.ForeignKey(EmailContact, on_delete=models.SET_NULL, null=True)
    email = models.EmailField()             # snapshot at send time
    status = models.CharField(max_length=20, default="queued")
    provider_message_id = models.CharField(max_length=200, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    bounced_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
```

---

### Task Design

```python
# email_marketing/tasks.py

def send_campaign(campaign_id: int, tenant_schema: str) -> None:
    """RQ task: send a campaign to all matching contacts in batches."""
    from django_tenants.utils import schema_context
    with schema_context(tenant_schema):
        campaign = EmailCampaign.objects.get(pk=campaign_id)
        campaign.status = "sending"
        campaign.save(update_fields=["status", "updated_at"])

        contacts = EmailContact.objects.filter(
            is_subscribed=True,
            tags__overlap=campaign.recipient_tags,   # PostgreSQL array overlap
        )

        # Send in batches of 500 to avoid provider rate limits
        batch = []
        for contact in contacts.iterator(chunk_size=500):
            batch.append(contact)
            if len(batch) >= 500:
                _send_batch(campaign, batch, tenant_schema)
                batch = []
        if batch:
            _send_batch(campaign, batch, tenant_schema)

        campaign.status = "sent"
        campaign.sent_at = timezone.now()
        campaign.save(update_fields=["status", "sent_at", "updated_at"])


def _send_batch(campaign, contacts, tenant_schema):
    """Send one batch via provider SDK and log results."""
    # Provider-specific implementation goes here
    # e.g. sendgrid.send_bulk([...])
    ...
```

---

### Transactional vs Marketing Emails

Keep these on separate sending paths:

| Type | Examples | Queue | Provider setting |
|------|---------|-------|-----------------|
| **Transactional** | Password reset, order confirmation, invoice | `default` | Dedicated IP / high priority |
| **Marketing** | Campaigns, newsletters, promotions | `email` | Shared IP / bulk |

Mixing them risks bulk sends affecting transactional deliverability.

---

### Unsubscribe & Compliance (GDPR / KVKK)

Turkey's KVKK and EU GDPR both require:

- [ ] One-click unsubscribe link in every marketing email
- [ ] Unsubscribe webhook from provider → set `EmailContact.is_subscribed = False`
- [ ] Record consent at signup (timestamp + source)
- [ ] Honor unsubscribes within 10 business days (KVKK) / immediately (GDPR best practice)
- [ ] Data export on request (covered by existing tenant data export)

Implement a public unsubscribe endpoint (no auth required):
```python
# GET /unsubscribe/?token=<signed_token>
# Token = TimestampSigner(contact_id + tenant_schema)
```

---

### Multi-tenant Considerations

- All models live in tenant schemas — contact lists and campaigns are fully isolated
- The RQ worker runs with no tenant context; the task must call `schema_context(tenant_schema)` explicitly (shown above)
- Shared Redis queue is fine — job payloads only contain `tenant_schema` + IDs, not PII
- Provider API key can be per-tenant (stored in `Client` model) or global with sub-account routing

---

### Implementation Order

1. Set up django-rq + worker (prerequisite for everything else)
2. `EmailContact` model + import from existing client list
3. Basic campaign compose + send (single batch, no scheduling)
4. `EmailSendLog` + provider webhook for open/bounce tracking
5. Scheduling (`scheduled_at` + a periodic RQ job that checks for due campaigns)
6. Unsubscribe flow + KVKK/GDPR compliance
7. Campaign analytics dashboard (open rate, bounce rate, by tag)

---

### Files to Create

```
email_marketing/
├── __init__.py
├── apps.py
├── models.py          # EmailContact, EmailCampaign, EmailSendLog
├── tasks.py           # send_campaign, _send_batch
├── views.py           # compose, send, status, unsubscribe
├── urls.py
├── admin.py
├── migrations/
└── templates/
    └── email_marketing/
        ├── campaign_compose.html
        └── unsubscribe.html
```

---

### Environment Variables to Add

```bash
# .env.dev / .env.staging / .env.production
EMAIL_PROVIDER=sendgrid          # or brevo, mailchimp, ses
EMAIL_API_KEY=your_api_key_here
EMAIL_FROM_ADDRESS=noreply@carnitrack.com
EMAIL_FROM_NAME=CarniTrack
EMAIL_UNSUBSCRIBE_SECRET=your_signing_secret
```
