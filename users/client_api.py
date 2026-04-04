"""
JSON API for staff to list and update client profiles (tenant-scoped).
"""

import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods

from .forms import ClientProfileRegisterForm
from .models import CLIENT_MANAGEMENT_ROLES, ClientProfile
from .policies import can_manage_client_accounts
from .services import update_user_credentials

PAGE_SIZE = 20
CLIENT_PROFILE_FIELDS = (
    "account_type",
    "contact_person",
    "phone_number",
    "address",
    "default_destination",
    "company_name",
    "tax_id",
)


def _can_manage_clients(user) -> bool:
    return can_manage_client_accounts(user)


def _is_manageable_client_profile(profile: ClientProfile) -> bool:
    linked_user = profile.user
    return linked_user is None or linked_user.role in CLIENT_MANAGEMENT_ROLES


def _serialize_profile(p: ClientProfile) -> dict:
    u = p.user
    out = {
        "id": str(p.id),
        "account_type": p.account_type,
        "contact_person": p.contact_person,
        "phone_number": p.phone_number,
        "address": p.address,
        "default_destination": p.default_destination,
        "default_destination_client_id": str(p.default_destination_client_id)
        if p.default_destination_client_id
        else None,
        "default_destination_client_name": (
            p.default_destination_client.get_full_name() if p.default_destination_client is not None else None
        ),
        "company_name": p.company_name,
        "tax_id": p.tax_id,
        "is_active": p.is_active,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "user": None,
    }
    if u is not None:
        out["user"] = {
            "id": u.id,
            "username": u.username,
            "email": u.email or "",
            "role": u.role,
            "is_active": u.is_active,
        }
    return out


@login_required
@require_http_methods(["GET"])
def client_profile_list_api(request):
    if not _can_manage_clients(request.user):
        return JsonResponse({"detail": "You do not have permission to manage client profiles."}, status=403)

    search = (request.GET.get("search") or "").strip()
    qs = (
        ClientProfile.objects.select_related("user")
        .filter(Q(user__isnull=True) | Q(user__role__in=CLIENT_MANAGEMENT_ROLES))
        .order_by("-created_at")
    )
    if search:
        qs = qs.filter(
            Q(company_name__icontains=search)
            | Q(contact_person__icontains=search)
            | Q(phone_number__icontains=search)
            | Q(default_destination__icontains=search)
            | Q(default_destination_client__company_name__icontains=search)
            | Q(default_destination_client__contact_person__icontains=search)
            | Q(default_destination_client__user__username__icontains=search)
            | Q(default_destination_client__user__first_name__icontains=search)
            | Q(default_destination_client__user__last_name__icontains=search)
            | Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search)
            | Q(user__last_name__icontains=search)
        )

    paginator = Paginator(qs, PAGE_SIZE)
    page_num = request.GET.get("page") or 1
    try:
        page_num = int(page_num)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    return JsonResponse(
        {
            "count": paginator.count,
            "page": page_obj.number,
            "num_pages": paginator.num_pages,
            "results": [_serialize_profile(p) for p in page_obj.object_list],
        }
    )


@login_required
@require_http_methods(["GET", "PATCH"])
def client_profile_detail_api(request, pk):
    if not _can_manage_clients(request.user):
        return JsonResponse({"detail": "You do not have permission to manage client profiles."}, status=403)

    if request.method == "GET":
        profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
        if not _is_manageable_client_profile(profile):
            return JsonResponse({"detail": "You do not have permission to manage this profile."}, status=403)
        return JsonResponse(_serialize_profile(profile))

    profile = get_object_or_404(ClientProfile.objects.select_related("user"), pk=pk)
    if not _is_manageable_client_profile(profile):
        return JsonResponse({"detail": "You do not have permission to manage this profile."}, status=403)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"detail": "JSON body must be an object."}, status=400)

    merged = {}
    for field in CLIENT_PROFILE_FIELDS:
        val = getattr(profile, field)
        merged[field] = "" if val is None else val
    for key, value in payload.items():
        if key in CLIENT_PROFILE_FIELDS:
            merged[key] = "" if value is None else value

    form = ClientProfileRegisterForm(data=merged, instance=profile)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    form.save()
    if profile.user is not None:
        update_user_credentials(
            profile.user,
            username=profile.user.username,
            email=profile.user.email or "",
            phone_number=form.cleaned_data.get("phone_number") or "",
        )
    profile.refresh_from_db()
    return JsonResponse(_serialize_profile(profile))
