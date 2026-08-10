# Despliegue en VPS

Stack: **Ubuntu 22.04 · Python 3.12 · MySQL 8 · Gunicorn · Nginx**

---

## 1. Requisitos en el VPS

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv python3-pip \
                    mysql-server mysql-client libmysqlclient-dev \
                    nginx git build-essential pkg-config
```

---

## 2. Base de datos MySQL

```sql
-- Conectarse como root: sudo mysql
CREATE DATABASE conciliaciones_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'conciliaciones_user'@'localhost' IDENTIFIED BY 'PASSWORD_SEGURO';
GRANT ALL PRIVILEGES ON conciliaciones_db.* TO 'conciliaciones_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

---

## 3. Clonar el repositorio

```bash
cd /home/ubuntu
git clone https://github.com/TU_USUARIO/TU_REPO.git app-conciliaciones
cd app-conciliaciones
```

---

## 4. Entorno virtual e instalación

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Variables de entorno

```bash
cp .env.example .env
nano .env          # completar SECRET_KEY, DB_*, ALLOWED_HOSTS
```

Generar una `SECRET_KEY` segura:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## 6. Inicializar la base de datos

```bash
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser    # usuario administrador inicial
```

---

## 7. Carpeta de logs

```bash
sudo mkdir -p /var/log/conciliaciones
sudo chown ubuntu:ubuntu /var/log/conciliaciones
```

---

## 8. Servicio Gunicorn (systemd)

```bash
# Editar el archivo y ajustar User/Group/WorkingDirectory si es necesario
nano deploy/conciliaciones.service

sudo cp deploy/conciliaciones.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable conciliaciones
sudo systemctl start conciliaciones
sudo systemctl status conciliaciones     # verificar que esté activo
```

---

## 9. Nginx

```bash
# Editar y poner tu dominio o IP en server_name
nano deploy/nginx.conf

sudo cp deploy/nginx.conf /etc/nginx/sites-available/conciliaciones
sudo ln -s /etc/nginx/sites-available/conciliaciones /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

---

## 10. (Opcional) HTTPS con Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d tu-dominio.com
```

---

## Actualizar la app

```bash
cd /home/ubuntu/app-conciliaciones
git pull
source venv/bin/activate
pip install -r requirements.txt        # si cambió requirements
python manage.py migrate               # si hay nuevas migraciones
python manage.py collectstatic --noinput
sudo systemctl restart conciliaciones
```

---

## Comandos útiles

```bash
sudo systemctl status conciliaciones      # estado del servicio
sudo journalctl -u conciliaciones -f      # logs en tiempo real
sudo tail -f /var/log/conciliaciones/gunicorn_error.log
sudo nginx -t                             # verificar config nginx
```
