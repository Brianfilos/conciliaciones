# Configuración de Gunicorn para producción
# Ubicación en el VPS: usar con --config deploy/gunicorn.conf.py

import multiprocessing

# Dirección y puerto interno (Nginx hace el proxy)
bind = "127.0.0.1:8000"

# Trabajadores: (2 x núcleos) + 1  es la fórmula recomendada
workers = multiprocessing.cpu_count() * 2 + 1

# Tipo de worker (sync es suficiente para esta app)
worker_class = "sync"

# Tiempo máximo de respuesta por request (seg)
timeout = 120

# Reiniciar workers después de N requests (evita memory leaks)
max_requests = 1000
max_requests_jitter = 100

# Logs
accesslog = "/var/log/conciliaciones/gunicorn_access.log"
errorlog  = "/var/log/conciliaciones/gunicorn_error.log"
loglevel  = "info"

# Usuario del proceso (ajustar al usuario del VPS)
# user  = "www-data"
# group = "www-data"
