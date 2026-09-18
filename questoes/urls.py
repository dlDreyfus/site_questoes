# Importa a função path, que liga um endereço (URL) a uma view.
from django.urls import path
# Importa o módulo views deste mesmo app (o "." significa "pasta atual").
from . import views

# Namespace do app (útil para links no HTML)
# Permite referenciar as rotas como 'questoes:lista_questoes' no {% url %} dos templates.
app_name = 'questoes'

# Lista de rotas deste app; o Django percorre em ordem até achar a que casa com a URL.
urlpatterns = [
    # '' = raiz do app; chama a view lista_questoes e dá o nome 'lista_questoes' à rota.
    path('', views.lista_questoes, name='lista_questoes'),
# Fecha a lista de rotas.
]
