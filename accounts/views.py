from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from muni.models import Municipio
from . import correo
from .forms import CambiarPasswordForm, LoginForm, RecuperarForm, UsuarioForm

User = get_user_model()


class LoginView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('municipio_home')
        form = LoginForm(request)
        return render(request, 'login.html', {'form': form})

    def post(self, request):
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            usuario = form.get_user()
            if getattr(usuario, '_con_temporal', False):
                # Entró con la contraseña temporal: debe elegir una nueva antes de seguir
                usuario.debe_cambiar_password = True
                usuario.save(update_fields=['debe_cambiar_password'])
            elif usuario.password_temporal:
                # Entró con su contraseña de siempre: la temporal ya no hace falta
                correo.limpiar_temporal(usuario)
                usuario.save(update_fields=['password_temporal', 'password_temporal_expira'])
            login(request, usuario)
            next_url = request.GET.get('next', 'municipio_home')
            return redirect(next_url)
        return render(request, 'login.html', {'form': form})


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


# ── Recuperación de contraseña ───────────────────────────────────────────────

class RecuperarPasswordView(View):
    """Envía una contraseña temporal al correo. La respuesta es siempre la misma (no revela
    qué correos existen) y se limita a un envío cada pocos minutos por usuario."""

    def get(self, request):
        return render(request, 'password_reset.html', {'form': RecuperarForm(), 'enviado': False})

    def post(self, request):
        form = RecuperarForm(request.POST)
        if form.is_valid():
            usuario = User.objects.filter(email__iexact=form.cleaned_data['email'], is_active=True).first()
            if usuario and not correo.temporal_reciente(usuario):
                plano = correo.asignar_temporal(usuario)
                correo.enviar_temporal(usuario, plano)
            return render(request, 'password_reset.html', {'form': RecuperarForm(), 'enviado': True,
                                                           'espera': settings.PASSWORD_TEMPORAL_ESPERA_MIN})
        return render(request, 'password_reset.html', {'form': form, 'enviado': False})


@method_decorator(login_required, name='dispatch')
class CambiarPasswordView(View):
    def _forzado(self, request):
        return request.user.debe_cambiar_password

    def get(self, request):
        forzado = self._forzado(request)
        return render(request, 'accounts/cambiar_password.html',
                      {'form': CambiarPasswordForm(request.user, forzado), 'forzado': forzado})

    def post(self, request):
        forzado = self._forzado(request)
        form = CambiarPasswordForm(request.user, forzado, request.POST)
        if not form.is_valid():
            return render(request, 'accounts/cambiar_password.html', {'form': form, 'forzado': forzado})
        u = request.user
        u.set_password(form.cleaned_data['nueva1'])
        u.debe_cambiar_password = False
        correo.limpiar_temporal(u)
        u.save()
        update_session_auth_hash(request, u)
        messages.success(request, 'Tu contraseña se cambió correctamente.')
        return redirect('municipio_home')


# ── Administración de usuarios (solo superusuario) ───────────────────────────

class SuperusuarioMixin:
    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied('Solo un superusuario puede administrar usuarios.')
        return super().dispatch(request, *args, **kwargs)


def _avisar_envio(request, usuario, plano, enviado, motivo):
    if enviado:
        messages.success(request, f'Se envió la contraseña temporal a {usuario.email}. '
                                  f'Vence en {settings.PASSWORD_TEMPORAL_HORAS} horas y pedirá el cambio al ingresar.')
    else:
        messages.warning(request, f'No se pudo enviar el correo a {usuario.email} (revisa la configuración de correo). '
                                  f'Entrégale esta contraseña temporal tú mismo, no se mostrará de nuevo: {plano}')


class UsuariosListaView(SuperusuarioMixin, View):
    def get(self, request):
        q = request.GET.get('q', '').strip()
        municipio = request.GET.get('municipio', '')
        rol = request.GET.get('rol', '')
        estado = request.GET.get('estado', '')
        qs = User.objects.select_related('municipio').order_by('municipio__orden', 'username')
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q)
                           | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        if municipio.isdigit():
            qs = qs.filter(municipio_id=int(municipio))
        if rol in dict(User.ROL_CHOICES):
            qs = qs.filter(rol=rol)
        if estado == 'activos':
            qs = qs.filter(is_active=True)
        elif estado == 'inactivos':
            qs = qs.filter(is_active=False)
        return render(request, 'accounts/usuarios_lista.html', {
            'usuarios': qs, 'total': User.objects.count(),
            'municipios': Municipio.objects.filter(activo=True).order_by('orden', 'nombre'),
            'roles': User.ROL_CHOICES,
            'f': {'q': q, 'municipio': municipio, 'rol': rol, 'estado': estado},
        })


class UsuarioCrearView(SuperusuarioMixin, View):
    def get(self, request):
        return render(request, 'accounts/usuario_form.html',
                      {'form': UsuarioForm(actor=request.user, initial={'is_active': True}), 'creando': True})

    def post(self, request):
        form = UsuarioForm(request.POST, actor=request.user)
        if not form.is_valid():
            return render(request, 'accounts/usuario_form.html', {'form': form, 'creando': True})
        u = form.save(commit=False)
        d = form.cleaned_data
        if d['modo_clave'] == 'manual':
            u.set_password(d['password'])
            u.debe_cambiar_password = bool(d['forzar_cambio'])
            u.save()
            messages.success(request, f'Usuario {u.username} creado con la contraseña que definiste.')
        else:
            u.set_unusable_password()
            u.save()
            plano = correo.asignar_temporal(u)
            _avisar_envio(request, u, plano, correo.enviar_temporal(u, plano, motivo='alta'), 'alta')
        return redirect('usuarios')


class UsuarioEditarView(SuperusuarioMixin, View):
    def get(self, request, pk):
        u = get_object_or_404(User, pk=pk)
        return render(request, 'accounts/usuario_form.html',
                      {'form': UsuarioForm(instance=u, actor=request.user), 'creando': False, 'u': u})

    def post(self, request, pk):
        u = get_object_or_404(User, pk=pk)
        form = UsuarioForm(request.POST, instance=u, actor=request.user)
        if not form.is_valid():
            return render(request, 'accounts/usuario_form.html', {'form': form, 'creando': False, 'u': u})
        form.save()
        messages.success(request, f'Cambios guardados para {u.username}.')
        return redirect('usuarios')


class UsuarioAccionView(SuperusuarioMixin, View):
    """Acciones rápidas: contraseña temporal, contraseña manual, activar/desactivar."""

    def post(self, request, pk):
        u = get_object_or_404(User, pk=pk)
        accion = request.POST.get('accion', '')
        volver = request.POST.get('volver', 'usuarios')
        if accion == 'temporal':
            plano = correo.asignar_temporal(u)
            _avisar_envio(request, u, plano, correo.enviar_temporal(u, plano), 'recuperacion')
        elif accion == 'manual':
            nueva = request.POST.get('password', '')
            try:
                from django.contrib.auth.password_validation import validate_password
                validate_password(nueva, u)
            except Exception as e:  # noqa: BLE001 - ValidationError con la lista de motivos
                motivos = ' '.join(getattr(e, 'messages', [str(e)]))
                messages.error(request, f'La contraseña no es válida: {motivos}')
                return redirect('usuario_editar', pk=u.pk)
            u.set_password(nueva)
            u.debe_cambiar_password = request.POST.get('forzar_cambio') == 'on'
            correo.limpiar_temporal(u)
            u.save()
            messages.success(request, f'Se definió una nueva contraseña para {u.username}.')
        elif accion in ('activar', 'desactivar'):
            if u.pk == request.user.pk and accion == 'desactivar':
                messages.error(request, 'No puedes desactivar tu propio usuario.')
            else:
                u.is_active = accion == 'activar'
                u.save(update_fields=['is_active'])
                messages.success(request, f'Usuario {u.username} {"activado" if u.is_active else "desactivado"}.')
        else:
            messages.error(request, 'Acción no reconocida.')
        return redirect('usuario_editar', pk=u.pk) if volver == 'editar' else redirect('usuarios')
