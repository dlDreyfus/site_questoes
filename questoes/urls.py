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
    # Recebe o POST com a alternativa marcada na questão <questao_id>.
    path('questao/<int:questao_id>/responder/', views.responder_questao, name='responder_questao'),
    # Fórum: publica um comentário (ou resposta a um comentário) na questão <questao_id>.
    path('questao/<int:questao_id>/comentar/', views.comentar_questao, name='comentar_questao'),
    # Fórum: curte o comentário <comentario_id> ou, se já curtido, desfaz a curtida.
    path('comentario/<int:comentario_id>/curtir/', views.curtir_comentario, name='curtir_comentario'),
    # Curte a resolução oficial <resolucao_id> ou, se já curtida, desfaz a curtida.
    path('resolucao/<int:resolucao_id>/curtir/', views.curtir_resolucao, name='curtir_resolucao'),
    # Descurte (👎) a resolução oficial ou, se já descurtida, desfaz. Só existe para a resolução.
    path('resolucao/<int:resolucao_id>/descurtir/', views.descurtir_resolucao, name='descurtir_resolucao'),
    # Simulados: tela de criação (filtros em cascata + situação), o POST que cria e a tela de resolução.
    path('simulados/novo/', views.novo_simulado, name='novo_simulado'),
    path('simulados/criar/', views.criar_simulado, name='criar_simulado'),
    path('simulados/<int:simulado_id>/', views.simulado_detalhe, name='simulado_detalhe'),
    # Renomear e apagar (o apagar pede confirmação antes: GET mostra a pergunta, POST apaga).
    path('simulados/<int:simulado_id>/editar/', views.editar_simulado, name='editar_simulado'),
    path('simulados/<int:simulado_id>/apagar/', views.apagar_simulado, name='apagar_simulado'),
    # Upload da planilha .csv de importação (restrito a quem tem a permissão importar_questoes).
    path('importar/', views.importar_questoes, name='importar_questoes'),
    path('importar/modelo.csv', views.modelo_planilha, name='modelo_planilha'),
# Fecha a lista de rotas.
]
