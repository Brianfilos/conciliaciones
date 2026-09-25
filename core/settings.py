from pathlib import Path
import os
from decouple import config, Csv

try:
    import MySQLdb  # noqa: F401
except ImportError:
    import pymysql
    pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# Detrás de Nginx con HTTPS: Django debe saber que la petición original era https y
# confiar en el origen del dominio, si no el login falla con "CSRF verification failed".
# Ej.: CSRF_TRUSTED_ORIGINS=https://filosdev.com,https://www.filosdev.com
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'whitenoise.runserver_nostatic',
    'django.contrib.staticfiles',
    'crispy_forms',
    'crispy_bootstrap5',
    'accounts',
    'muni',
    'etl',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'accounts.middleware.ForzarCambioPasswordMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'muni.context_processors.municipio_context',
                'etl.context_processors.cola_envio',
            ],
            'libraries': {
                'etl_extras': 'etl.templatetags.etl_extras',
            },
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_USER_MODEL = 'accounts.CustomUser'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/home/'
LOGOUT_REDIRECT_URL = '/login/'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

MUNICIPIOS_ROOT = BASE_DIR / 'MUNICIPIOS'
GOBS_ROOT = BASE_DIR / 'GOBS'

# En el VPS estas carpetas se crean manualmente con los insumos del municipio activo

# Correo saliente (recuperación de contraseña y alta de usuarios).
# Sin EMAIL_HOST los correos solo se imprimen en el log del servidor.
EMAIL_HOST = config('EMAIL_HOST', default='')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
    EMAIL_TIMEOUT = 15
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='Sistema de CXC <noreply@conciliaciones.gov.co>')
SITE_URL = config('SITE_URL', default='http://localhost:8000')
PASSWORD_TEMPORAL_HORAS = config('PASSWORD_TEMPORAL_HORAS', default=24, cast=int)
# Espera mínima entre dos recuperaciones del mismo usuario (evita que alguien inunde un buzón)
PASSWORD_TEMPORAL_ESPERA_MIN = config('PASSWORD_TEMPORAL_ESPERA_MIN', default=2, cast=int)

# Remitente de las exportaciones enviadas por correo desde Ver datos (debe estar verificado en Brevo)
EXPORT_FROM_EMAIL = config('EXPORT_FROM_EMAIL', default=DEFAULT_FROM_EMAIL)
EXPORT_MAX_ADJUNTOS_MB = config('EXPORT_MAX_ADJUNTOS_MB', default=10, cast=int)
# Opcional: a dónde llegan las respuestas si el remitente es otro (p. ej. noreply@filosdev.com)
EXPORT_REPLY_TO = config('EXPORT_REPLY_TO', default='')

AUTHENTICATION_BACKENDS = [
    'accounts.backends.PasswordTemporalBackend',
    'django.contrib.auth.backends.ModelBackend',
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
