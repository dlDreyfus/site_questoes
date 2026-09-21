# Importa o módulo de modelos do Django (ORM): fornece a classe base Model
# e os tipos de campo usados para descrever as tabelas do banco em Python.
from django.db import models
from django.db.models.functions import Length
# Importa as configurações do projeto para referenciar o model de usuário (AUTH_USER_MODEL).
from django.conf import settings

# 1. TABELAS DE DOMÍNIO (Nossos Filtros Básicos)

# Tabela das bancas examinadoras (ex.: FGV, Cebraspe).
class Banca(models.Model):
    # Nome completo da banca; texto de até 100 caracteres, sem repetição no banco.
    nome = models.CharField(max_length=100, unique=True)
    # Sigla opcional: blank=True permite deixar vazio no formulário/admin
    # e null=True permite gravar NULL no banco.
    sigla = models.CharField(max_length=20, blank=True, null=True)

    # Define como o objeto aparece como texto (no admin, no shell, em selects).
    def __str__(self):
        # Mostra a sigla se ela existir; caso contrário, mostra o nome.
        return self.sigla if self.sigla else self.nome

# Tabela dos órgãos que realizaram o concurso (ex.: TCU, TCE-RJ).
class Orgao(models.Model):
    # Nome completo do órgão; até 150 caracteres e único.
    nome = models.CharField(max_length=150, unique=True)
    # Sigla obrigatória do órgão (sem blank/null, o campo não pode ficar vazio).
    sigla = models.CharField(max_length=20)

    # Representação textual do órgão.
    def __str__(self):
        # Exibe a sigla do órgão.
        return self.sigla

# Tabela dos cargos cobrados nos concursos (ex.: Auditor de Controle Externo).
class Cargo(models.Model):
    # Nome do cargo; até 150 caracteres e único.
    nome = models.CharField(max_length=150, unique=True)

    # Representação textual do cargo.
    def __str__(self):
        # Exibe o nome do cargo.
        return self.nome

# Tabela das matérias/disciplinas (ex.: Direito Administrativo).
class Materia(models.Model):
    # Nome da matéria; até 100 caracteres e único.
    nome = models.CharField(max_length=100, unique=True)

    # Representação textual da matéria.
    def __str__(self):
        # Exibe o nome da matéria.
        return self.nome

# Tabela dos tópicos (assuntos) dentro de cada matéria.
class Topico(models.Model):
    # Nome do tópico; não é único porque matérias diferentes podem ter tópicos homônimos.
    nome = models.CharField(max_length=150)
    # 1:N - Um tópico pertence a uma matéria. Se a matéria for deletada (CASCADE), os tópicos vão junto.
    # related_name='topicos' permite acessar os tópicos a partir da matéria: materia.topicos.all()
    materia = models.ForeignKey(Materia, on_delete=models.CASCADE, related_name='topicos')

    class Meta:
        ordering = ['materia__nome', 'nome']

    # Representação textual do tópico.
    def __str__(self):
        # Exibe "Matéria - Tópico" para deixar claro a qual matéria o tópico pertence.
        return f"{self.materia.nome} - {self.nome}"

# 2. O NÚCLEO DO SISTEMA (Questões e Alternativas)

# Tabela principal: cada registro é uma questão de concurso.
class Questao(models.Model):
    # Enumeração para travar o tipo de questão
    class TipoQuestao(models.TextChoices):
        # Valor gravado no banco: 'ME'; rótulo exibido ao usuário: 'Múltipla Escolha'.
        MULTIPLA_ESCOLHA = 'ME', 'Múltipla Escolha'
        # Valor gravado no banco: 'CE'; rótulo exibido ao usuário: 'Certo/Errado'.
        CERTO_ERRADO = 'CE', 'Certo/Errado'

    # Identificador próprio da questão (ex: "FGV-TCU-2024-015"), usado na importação por planilha
    # para impedir que a mesma questão seja importada duas vezes. Opcional: questões cadastradas
    # pelo admin podem ficar sem código (NULL não conflita com o unique).
    codigo = models.CharField(max_length=50, unique=True, null=True, blank=True)
    # Texto do enunciado; TextField não tem limite de tamanho.
    enunciado = models.TextField()
    # Tipo da questão: 2 caracteres, restrito às opções acima; padrão é múltipla escolha.
    tipo = models.CharField(max_length=2, choices=TipoQuestao.choices, default=TipoQuestao.MULTIPLA_ESCOLHA)
    # Ano de aplicação da prova.
    ano = models.IntegerField()

    # PROTECT: Impede que alguém delete a "FGV" do sistema e apague 10 mil questões junto sem querer.
    banca = models.ForeignKey(Banca, on_delete=models.PROTECT)
    # Órgão do concurso; PROTECT impede apagar um órgão que ainda tenha questões.
    orgao = models.ForeignKey(Orgao, on_delete=models.PROTECT)
    # Cargo do concurso; PROTECT impede apagar um cargo que ainda tenha questões.
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT)

    # N:M - Uma questão pode cobrar dois tópicos diferentes simultaneamente.
    # O Django cria sozinho a tabela intermediária; related_name='questoes'
    # permite fazer topico.questoes.all().
    topicos = models.ManyToManyField(Topico, related_name='questoes')

    class Meta:
        # Ordem padrão da listagem: provas mais recentes primeiro (a paginação exige ordem definida).
        ordering = ['-ano', 'id']
        # Permissão própria para a importação por planilha: superusuários já a têm;
        # os demais recebem pelo grupo "Administrador" (ou individualmente, pelo admin)
        permissions = [('importar_questoes', 'Pode importar questões por planilha CSV')]

    # Representação textual da questão.
    def __str__(self):
        # Exibe algo como "Questão 12 - FGV (2024)".
        return f"Questão {self.id} - {self.banca} ({self.ano})"

# Tabela das alternativas de cada questão.
class Alternativa(models.Model):
    # 1:N - Se a questão for apagada, as alternativas dela são apagadas (CASCADE)
    # related_name='alternativas' permite fazer questao.alternativas.all().
    questao = models.ForeignKey(Questao, on_delete=models.CASCADE, related_name='alternativas')
    # Posição da alternativa na questão (1 = A, 2 = B, ...), para exibir sempre na mesma ordem.
    ordem = models.PositiveSmallIntegerField(default=0)
    # Texto da alternativa.
    texto = models.TextField()
    # Marca se esta é a alternativa correta; por padrão, é falsa.
    is_correta = models.BooleanField(default=False)

    class Meta:
        # Sem ordering o banco pode devolver as alternativas em qualquer ordem; 'id' desempata.
        ordering = ['ordem', 'id']
        constraints = [
            # Garante no próprio banco que cada questão tenha no máximo UMA alternativa correta.
            # (O "exatamente uma" é validado no admin, em AlternativaFormSet.)
            models.UniqueConstraint(
                fields=['questao'],
                condition=models.Q(is_correta=True),
                name='uma_alternativa_correta_por_questao',
                violation_error_message='Esta questão já possui uma alternativa correta.',
            ),
        ]

    # Representação textual da alternativa.
    def __str__(self):
        # questao_id já está no objeto; usar self.questao.id faria uma consulta extra ao banco.
        return f"Alternativa da Questão {self.questao_id}"

# Tabela com o comentário/resolução oficial de cada questão.
class ResolucaoOficial(models.Model):
    # 1:1 - Cada questão tem no máximo uma resolução oficial associada.
    # related_name='resolucao' permite fazer questao.resolucao.
    questao = models.OneToOneField(Questao, on_delete=models.CASCADE, related_name='resolucao')
    # Texto da resolução.
    texto = models.TextField()
    # Usuários que curtiram a resolução (mesmo esquema das curtidas dos comentários:
    # par (resolução, usuário) único; "descurtir" remove o par).
    curtidas = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='resolucoes_curtidas', blank=True)
    # Usuários que descurtiram (👎) a resolução. Curtir e descurtir se excluem: a view remove o
    # usuário de uma lista quando ele entra na outra (ver _alternar_curtida em views.py).
    descurtidas = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='resolucoes_descurtidas', blank=True)

    # Representação textual da resolução.
    def __str__(self):
        # Exibe a qual questão a resolução pertence.
        return f"Resolução - Questão {self.questao_id}"

# 3. HISTÓRICO DO USUÁRIO

# Tabela com cada tentativa de resposta de um usuário.
class HistoricoResolucao(models.Model):
    # Usuário que respondeu; settings.AUTH_USER_MODEL aponta para o User do Django.
    # related_name='historico' permite fazer usuario.historico.all().
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='historico')
    # Questão respondida; se a questão for apagada, o histórico dela vai junto.
    questao = models.ForeignKey(Questao, on_delete=models.CASCADE, related_name='historico')
    # Alternativa marcada pelo usuário. SET_NULL: se a alternativa for apagada/corrigida no admin,
    # a tentativa continua no histórico (o campo 'acertou' preserva o resultado).
    alternativa_escolhida = models.ForeignKey(Alternativa, on_delete=models.SET_NULL, null=True, blank=True)
    # Guarda se a tentativa foi um acerto.
    acertou = models.BooleanField()
    # Preenchido automaticamente com a data/hora da resposta.
    data_resposta = models.DateTimeField(auto_now_add=True)
    # Simulado em que a resposta foi dada (vazio = resposta na lista de questões). SET_NULL: se o
    # simulado for apagado, a resposta continua valendo nas estatísticas do painel de desempenho.
    simulado = models.ForeignKey(
        'Simulado', on_delete=models.SET_NULL, null=True, blank=True, related_name='resolucoes',
    )

    class Meta:
        ordering = ['-data_resposta']
        verbose_name = 'histórico de resolução'
        verbose_name_plural = 'histórico de resoluções'
        constraints = [
            # Num simulado cada questão é respondida uma única vez (fora dele, pode-se refazer à vontade)
            models.UniqueConstraint(
                fields=['simulado', 'questao'],
                condition=models.Q(simulado__isnull=False),
                name='uma_resposta_por_questao_no_simulado',
            ),
        ]

    # Representação textual da tentativa.
    def __str__(self):
        return f"{self.usuario} - Questão {self.questao_id} - {'Acertou' if self.acertou else 'Errou'}"

# 4. SIMULADOS

# Simulado: conjunto FIXO de questões escolhido pelo usuário. As questões que atendiam aos filtros
# no momento da criação ficam gravadas aqui: cadastrar ou responder questões depois não muda o simulado.
class Simulado(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='simulados')
    nome = models.CharField(max_length=100)
    # Resumo legível dos filtros usados na criação (ex: "Banca: FGV · Ano: 2024"), só para exibir
    descricao = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    # N:M - as questões do simulado; related_name='simulados' permite questao.simulados.all()
    questoes = models.ManyToManyField(Questao, related_name='simulados')

    class Meta:
        # Mais recentes primeiro
        ordering = ['-criado_em', '-id']

    def __str__(self):
        return f'{self.nome} ({self.usuario})'


# 5. FÓRUM (comentários das questões)

# Tamanho máximo de um comentário: 1 a 2 parágrafos, suficiente para explicar um raciocínio
# ou citar um artigo de lei sem virar redação. Para mudar o limite, altere só este número
# (e gere uma migração, porque a constraint do banco usa o valor).
COMENTARIO_TAMANHO_MAXIMO = 1000


# Comentário de um usuário numa questão. As respostas usam um só nível de aninhamento:
# resposta_a sempre aponta para um comentário principal (quem responde a uma resposta entra
# na mesma conversa, mencionando o autor com @usuario). Isso mantém o fórum legível no celular.
class Comentario(models.Model):
    questao = models.ForeignKey(Questao, on_delete=models.CASCADE, related_name='comentarios')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comentarios')
    # max_length num TextField limita o formulário (e o maxlength da caixa de texto no navegador)
    texto = models.TextField(max_length=COMENTARIO_TAMANHO_MAXIMO)
    # Vazio = comentário principal; preenchido = resposta ao comentário principal indicado
    resposta_a = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True, related_name='respostas',
    )
    data_criacao = models.DateTimeField(auto_now_add=True)
    # Usuários que curtiram o comentário. O Django cria a tabela intermediária com o par
    # (comentário, usuário) único: cada usuário curte no máximo uma vez; "descurtir" remove o par.
    curtidas = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='comentarios_curtidos', blank=True)

    class Meta:
        # Conversas em ordem cronológica, como num fórum
        ordering = ['data_criacao', 'id']
        verbose_name = 'comentário'
        verbose_name_plural = 'comentários'
        constraints = [
            # Mesmo que alguém grave direto no banco, o texto não pode ficar vazio nem passar do limite
            models.CheckConstraint(
                condition=models.lookups.GreaterThan(Length('texto'), 0)
                & models.lookups.LessThanOrEqual(Length('texto'), COMENTARIO_TAMANHO_MAXIMO),
                name='comentario_tamanho_valido',
            ),
        ]

    def __str__(self):
        tipo = 'Resposta' if self.resposta_a_id else 'Comentário'
        return f'{tipo} de {self.usuario} na Questão {self.questao_id}'
