from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario


# Usa a tela de usuários padrão do Django (senha, permissões, grupos) para o model próprio
@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    pass
