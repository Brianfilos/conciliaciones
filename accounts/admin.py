from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ['username', 'email', 'municipio', 'rol', 'is_active']
    list_filter = ['rol', 'municipio', 'is_active']
    fieldsets = UserAdmin.fieldsets + (
        ('Municipio y Rol', {'fields': ('municipio', 'rol')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Municipio y Rol', {'fields': ('email', 'municipio', 'rol')}),
    )
