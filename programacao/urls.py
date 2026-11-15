from django.urls import path

from . import views # Importamos as views deste app

app_name = 'programacao'

urlpatterns = [
    # Home, em /programacao/
    path('', views.home, name='home'),
    # Página do app de programação, aberta numa aba da Home
    path('inicio/', views.inicio, name='inicio'),
]
