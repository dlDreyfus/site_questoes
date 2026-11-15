from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('usuarios/', include('usuarios.urls')),
    path('programacao/', include('programacao.urls')),
    path('', include('questoes.urls')),
]
