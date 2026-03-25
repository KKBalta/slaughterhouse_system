def tenant_context(request):
    """Expose current tenant on templates as ``tenant`` (None on public / non-multitenant)."""
    return {"tenant": getattr(request, "tenant", None)}
