from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.views.generic.edit import CreateView
from .forms import UserRegistrationForm
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required

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

@login_required
def dashboard_view(request):
    return render(request, 'users/dashboard.html')