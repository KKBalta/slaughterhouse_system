from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from .forms import UserRegistrationForm, ClientProfileRegisterForm
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from .services import create_user_with_profile
from django.contrib import messages
import secrets

# New home view for the landing page
def home_view(request):
    return render(request, 'users/home.html')

# New view for the logged out confirmation page
def logged_out_view(request):
    return render(request, 'users/logged_out.html')

class RegisterView(CreateView):
    form_class = UserRegistrationForm
    success_url = reverse_lazy('login') # Redirect to login page after successful registration
    template_name = 'users/register.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    # def dispatch(self, request, *args, **kwargs):
    #     if request.user.is_authenticated:
    #         return redirect(reverse_lazy('dashboard')) # Redirect to dashboard if already logged in
    #     return super().dispatch(request, *args, **kwargs)

class CustomLoginView(LoginView):
    template_name = 'users/login.html'
    fields = '__all__'
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy('dashboard') # Redirect to dashboard page after login

class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('logged_out') # Redirect to logged_out page after logout

class ClientProfileRegisterView(CreateView):
    form_class = ClientProfileRegisterForm
    template_name = 'users/client_profile_register.html'
    success_url = reverse_lazy('login')

    def form_valid(self, form):
        # Generate username and password
        phone = form.cleaned_data['phone_number']
        account_type = form.cleaned_data['account_type']
        contact_person = form.cleaned_data.get('contact_person')
        company_name = form.cleaned_data.get('company_name')
        # Username: company_name or contact_person + last 4 digits of phone
        if account_type == 'ENTERPRISE' and company_name:
            base_name = company_name.replace(' ', '').lower()
        else:
            base_name = (contact_person or 'client').replace(' ', '').lower()
        username = f"{base_name}{phone[-4:]}"
        password = secrets.token_urlsafe(8)
        # Create user and profile
        # Optionally, show credentials to user (flash message)
        messages.success(self.request, f"Your account has been created. Username: {username}, Password: {password}")
        return super().form_valid(form)

@login_required
def dashboard_view(request):
    return render(request, 'users/dashboard.html')