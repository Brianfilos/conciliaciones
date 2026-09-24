from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('home/', views.HomeView.as_view(), name='home'),
    path('perfil/', views.PerfilView.as_view(), name='perfil'),
    # Recuperación y cambio de contraseña
    path('recuperar/', views.RecuperarPasswordView.as_view(), name='password_reset'),
    path('cambiar-password/', views.CambiarPasswordView.as_view(), name='cambiar_password'),
    # Administración de usuarios (superusuario)
    path('usuarios/', views.UsuariosListaView.as_view(), name='usuarios'),
    path('usuarios/nuevo/', views.UsuarioCrearView.as_view(), name='usuario_nuevo'),
    path('usuarios/<int:pk>/', views.UsuarioEditarView.as_view(), name='usuario_editar'),
    path('usuarios/<int:pk>/accion/', views.UsuarioAccionView.as_view(), name='usuario_accion'),
]
