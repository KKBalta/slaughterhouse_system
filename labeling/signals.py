from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import PrintJob


@receiver(post_save, sender=PrintJob)
def _print_job_post_save_bump_cache(sender, instance, **kwargs):
    """Invalidate the per-site pending-print-jobs cache on every PrintJob save.

    Any mutation of an edge-dispatched PrintJob — enqueue, operator edit of
    target_role / prn_content / target_printer on a pending job, retry attempt
    bump, ack (which flips status out of 'pending') — bumps the site's cache
    version so the next edge poll at that site skips the stale cache entry
    and re-queries. Prevents the class of bug found in the /sessions audit
    where web-UI mutations silently bypassed the cache invalidation.

    Local-dispatch jobs (dispatch_mode != 'edge') don't affect the edge poll,
    so skip the bump for them to avoid unnecessary cache churn.

    Note: PrintJob.objects.filter(...).update(...) bypasses post_save. Audit
    confirmed no caller uses bulk update today; if one is added, the caller
    must invoke _bump_edge_print_jobs_version(site_id) explicitly.
    """
    if getattr(instance, "dispatch_mode", None) != "edge":
        return
    site_id = getattr(instance, "site_id", None)
    if site_id is None:
        return
    from scales.api_views import _bump_edge_print_jobs_version

    _bump_edge_print_jobs_version(site_id)
