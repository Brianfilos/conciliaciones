from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('home/', views.HomeView.as_view(), name='home'),
    path('perfil/', views.PerfilView.as_view(), name='perfil'),
]
