# Importa o módulo admin do Django, que gera o painel administrativo automaticamente.
from django.contrib import admin
# Importa todos os models deste app para registrá-los no painel.
from .models import Banca, Orgao, Cargo, Materia, Topico, Questao, Alternativa, ResolucaoOficial

# Cadastros simples
# Registra a Banca no admin com a tela padrão (listar, criar, editar, apagar).
admin.site.register(Banca)
# Registra o Órgão no admin com a tela padrão.
admin.site.register(Orgao)
# Registra o Cargo no admin com a tela padrão.
admin.site.register(Cargo)
# Registra a Matéria no admin com a tela padrão.
admin.site.register(Materia)
# Registra o Tópico no admin com a tela padrão.
admin.site.register(Topico)
# Registra a Resolução Oficial no admin com a tela padrão.
admin.site.register(ResolucaoOficial)

# Configuração Avançada (Inlines)
# Define um "inline": permite editar alternativas dentro da tela de outro model,
# exibidas em formato de tabela (TabularInline), uma alternativa por linha.
class AlternativaInline(admin.TabularInline):
    # Indica qual model será editado dentro da tela da questão.
    model = Alternativa
    extra = 4  # Quando abrir a tela, já exibe 4 campos em branco para as alternativas (A, B, C, D)

# Registra o model Questao usando a configuração personalizada da classe abaixo.
@admin.register(Questao)
# Classe que personaliza como as questões aparecem e são editadas no admin.
class QuestaoAdmin(admin.ModelAdmin):
    # O que vai aparecer na lista geral de questões
    list_display = ('id', 'banca', 'orgao', 'ano', 'tipo')

    # Cria uma barra lateral para filtrar rapidamente
    list_filter = ('banca', 'ano', 'tipo')

    # Cria uma barra de pesquisa que busca pelo texto do enunciado
    # (a vírgula no final é obrigatória: sem ela não seria uma tupla, e sim só um texto).
    search_fields = ('enunciado',)

    # Diz ao Django para colocar as alternativas dentro da tela da questão
    inlines = [AlternativaInline]
