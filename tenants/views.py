from django.shortcuts import render


def public_landing(request):
    return render(request, "public/landing.html")
