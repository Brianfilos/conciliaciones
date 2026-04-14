import os
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.conf import settings
from .forms import LoginForm


def get_gobs_logos():
    gobs_img = os.path.join(str(settings.GOBS_ROOT), 'IMG')
    if not os.path.exists(gobs_img):
        return []
    exts = ('.png', '.jpg', '.jpeg', '.svg', '.webp')
    return [f for f in os.listdir(gobs_img) if f.lower().endswith(exts)]


class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('municipio_home')
        form = LoginForm(request)
        return render(request, 'login.html', {
            'form': form,
            'gobs_logos': get_gobs_logos(),
        })

    def post(self, request):
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            next_url = request.GET.get('next', 'municipio_home')
            return redirect(next_url)
        return render(request, 'login.html', {
            'form': form,
            'gobs_logos': get_gobs_logos(),
        })


class LogoutView(View):
    def post(self, request):
        logout(request)
        return redirect('login')

    def get(self, request):
        logout(request)
        return redirect('login')


@method_decorator(login_required, name='dispatch')
class HomeView(View):
    def get(self, request):
        return redirect('municipio_home')


@method_decorator(login_required, name='dispatch')
class PerfilView(View):
    def get(self, request):
        return render(request, 'accounts/perfil.html', {'user': request.user})
