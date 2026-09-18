from django.contrib import admin
from .models import Banca, Orgao, Cargo, Materia, Topico, Questao, Alternativa, ResolucaoOficial

# Cadastros simples
admin.site.register(Banca)
admin.site.register(Orgao)
admin.site.register(Cargo)
admin.site.register(Materia)
admin.site.register(Topico)
admin.site.register(ResolucaoOficial)

# Configuração Avançada (Inlines)
class AlternativaInline(admin.TabularInline):
    model = Alternativa
    extra = 4  # Quando abrir a tela, já exibe 4 campos em branco para as alternativas (A, B, C, D)

@admin.register(Questao)
class QuestaoAdmin(admin.ModelAdmin):
    # O que vai aparecer na lista geral de questões
    list_display = ('id', 'banca', 'orgao', 'ano', 'tipo')
    
    # Cria uma barra lateral para filtrar rapidamente
    list_filter = ('banca', 'ano', 'tipo')
    
    # Cria uma barra de pesquisa que busca pelo texto do enunciado
    search_fields = ('enunciado',)
    
    # Diz ao Django para colocar as alternativas dentro da tela da questão
    inlines = [AlternativaInline]