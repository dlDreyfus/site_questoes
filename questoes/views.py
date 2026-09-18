# Importa o atalho render, que junta um template HTML com dados e devolve a resposta HTTP.
from django.shortcuts import render
# Importa o model Questao do arquivo models.py deste app.
from .models import Questao

# View que exibe a lista de questões; recebe a requisição HTTP feita pelo navegador.
def lista_questoes(request):
    # Busca todas as questões no banco de dados
    # O 'select_related' e 'prefetch_related' são otimizações para não sobrecarregar o banco
    # select_related: traz banca, órgão e cargo na mesma consulta (JOIN), pois são ForeignKey.
    # prefetch_related: traz as alternativas de todas as questões numa segunda consulta só.
    # .all(): pega todos os registros resultantes.
    questoes = Questao.objects.select_related('banca', 'orgao', 'cargo').prefetch_related('alternativas').all()

    # Cria um 'contexto', que é um dicionário para enviar dados do Python para o HTML
    context = {
        # A chave 'questoes' vira a variável {{ questoes }} dentro do template.
        'questoes': questoes
    # Fecha o dicionário.
    }

    # Renderiza o HTML passando o contexto
    # O template é procurado em questoes/templates/questoes/lista_questoes.html.
    return render(request, 'questoes/lista_questoes.html', context)
