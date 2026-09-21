# Importa o módulo admin do Django, que gera o painel administrativo automaticamente.
from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.forms.models import BaseInlineFormSet
# Importa todos os models deste app para registrá-los no painel.
from .models import (
    Banca, Orgao, Cargo, Materia, Topico, Questao, Alternativa, ResolucaoOficial, HistoricoResolucao, Comentario,
    Simulado,
)

# Cadastros simples
# Registra a Banca no admin com a tela padrão (listar, criar, editar, apagar).
admin.site.register(Banca)
# Registra o Órgão no admin com a tela padrão.
admin.site.register(Orgao)
# Registra o Cargo no admin com a tela padrão.
admin.site.register(Cargo)
# Registra a Matéria no admin com a tela padrão.
admin.site.register(Materia)


@admin.register(Topico)
class TopicoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'materia')
    list_filter = ('materia',)
    search_fields = ('nome', 'materia__nome')
    # O __str__ do tópico usa a matéria: traz as duas na mesma consulta (evita uma consulta por linha)
    list_select_related = ('materia',)


@admin.register(ResolucaoOficial)
class ResolucaoOficialAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'questao')
    list_select_related = ('questao__banca',)


# Configuração Avançada (Inlines)
class AlternativaForm(forms.ModelForm):
    def validate_constraints(self):
        # Por padrão o Django checa cada alternativa sozinha contra o banco. Ao trocar a correta
        # (ex: de B para A), o banco ainda tem B marcada e a troca seria recusada. Por isso a regra
        # "uma correta por questão" (que depende de is_correta) é validada no conjunto, em
        # AlternativaFormSet.clean; as demais constraints continuam sendo checadas aqui.
        exclude = self._get_validation_exclusions()
        exclude.add('is_correta')
        try:
            self.instance.validate_constraints(exclude=exclude)
        except ValidationError as e:
            self._update_errors(e)


class AlternativaFormSet(BaseInlineFormSet):
    # Valida o conjunto de alternativas da questão antes de salvar
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        # Considera só as alternativas preenchidas e que não foram marcadas para exclusão
        corretas = [
            form for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE') and form.cleaned_data.get('is_correta')
        ]
        if len(corretas) != 1:
            raise ValidationError('Marque exatamente uma alternativa como correta.')

    def save(self, commit=True):
        # A constraint do banco só permite uma correta por vez. Se a correta mudou (ex: de D para A),
        # desmarca primeiro a antiga para que salvar a nova não viole a constraint no meio do caminho.
        # (form.instance já contém os valores novos do formulário neste ponto)
        desmarcar = [
            form.instance.pk for form in self.initial_forms
            if form in self.deleted_forms or not form.instance.is_correta
        ]
        with transaction.atomic():
            Alternativa.objects.filter(pk__in=desmarcar).update(is_correta=False)
            return super().save(commit)


# Define um "inline": permite editar alternativas dentro da tela de outro model,
# exibidas em formato de tabela (TabularInline), uma alternativa por linha.
class AlternativaInline(admin.TabularInline):
    # Indica qual model será editado dentro da tela da questão.
    model = Alternativa
    form = AlternativaForm
    formset = AlternativaFormSet
    fields = ('ordem', 'texto', 'is_correta')
    extra = 5  # Quando abrir a tela, já exibe 5 campos em branco para as alternativas (A, B, C, D, E)


# Registra o model Questao usando a configuração personalizada da classe abaixo.
@admin.register(Questao)
# Classe que personaliza como as questões aparecem e são editadas no admin.
class QuestaoAdmin(admin.ModelAdmin):
    # O que vai aparecer na lista geral de questões
    list_display = ('id', 'codigo', 'banca', 'orgao', 'ano', 'tipo')
    # Traz banca e órgão na mesma consulta da listagem (evita uma consulta por linha)
    list_select_related = ('banca', 'orgao')

    # Cria uma barra lateral para filtrar rapidamente
    list_filter = ('banca', 'ano', 'tipo')

    # Cria uma barra de pesquisa que busca pelo texto do enunciado e pelo código da importação
    search_fields = ('enunciado', 'codigo')

    # Troca a caixa de seleção múltipla dos tópicos por duas listas com busca
    filter_horizontal = ('topicos',)

    # Diz ao Django para colocar as alternativas dentro da tela da questão
    inlines = [AlternativaInline]


# Fórum: moderação dos comentários (buscar, ver o contexto e apagar os inadequados).
# Apagar um comentário principal apaga também as respostas dele.
@admin.register(Comentario)
class ComentarioAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'texto_resumido', 'data_criacao')
    list_filter = ('data_criacao',)
    search_fields = ('texto', 'usuario__username')
    date_hierarchy = 'data_criacao'
    list_select_related = ('usuario',)
    # raw_id_fields: em vez de um dropdown com TODAS as questões/comentários, um campo com o id
    raw_id_fields = ('questao', 'resposta_a', 'usuario')

    @admin.display(description='texto')
    def texto_resumido(self, comentario):
        return comentario.texto if len(comentario.texto) <= 80 else f'{comentario.texto[:80]}…'


# Simulados criados pelos usuários. As questões e o dono não se editam aqui: um simulado é um conjunto
# fixo gerado pelo site. Apagar um simulado mantém as respostas no histórico do usuário.
@admin.register(Simulado)
class SimuladoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'usuario', 'criado_em', 'total_questoes')
    list_filter = ('criado_em',)
    search_fields = ('nome', 'usuario__username')
    list_select_related = ('usuario',)
    # Sem as questões: listar milhares delas numa linha só deixaria a tela pesada
    fields = ('nome', 'usuario', 'descricao', 'criado_em')
    readonly_fields = ('usuario', 'descricao', 'criado_em')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(qtd_questoes=Count('questoes'))

    @admin.display(description='questões', ordering='qtd_questoes')
    def total_questoes(self, simulado):
        return simulado.qtd_questoes

    def has_add_permission(self, request):
        return False


# Histórico de respostas dos usuários: somente leitura (é gerado pelo site, não pelo admin)
@admin.register(HistoricoResolucao)
class HistoricoResolucaoAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'questao', 'alternativa_escolhida', 'acertou', 'data_resposta')
    list_filter = ('acertou', 'data_resposta', 'questao__banca')
    search_fields = ('usuario__username',)
    date_hierarchy = 'data_resposta'
    list_select_related = ('usuario', 'questao__banca', 'alternativa_escolhida')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
