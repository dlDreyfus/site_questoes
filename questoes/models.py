# Importa o módulo de modelos do Django (ORM): fornece a classe base Model
# e os tipos de campo usados para descrever as tabelas do banco em Python.
from django.db import models

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

    # Representação textual da questão.
    def __str__(self):
        # Exibe algo como "Questão 12 - FGV (2024)".
        return f"Questão {self.id} - {self.banca.sigla} ({self.ano})"

# Tabela das alternativas de cada questão.
class Alternativa(models.Model):
    # 1:N - Se a questão for apagada, as alternativas dela são apagadas (CASCADE)
    # related_name='alternativas' permite fazer questao.alternativas.all().
    questao = models.ForeignKey(Questao, on_delete=models.CASCADE, related_name='alternativas')
    # Texto da alternativa.
    texto = models.TextField()
    # Marca se esta é a alternativa correta; por padrão, é falsa.
    is_correta = models.BooleanField(default=False)

    # Representação textual da alternativa.
    def __str__(self):
        # Exibe a qual questão a alternativa pertence.
        return f"Alternativa da Questão {self.questao.id}"

# Tabela com o comentário/resolução oficial de cada questão.
class ResolucaoOficial(models.Model):
    # 1:1 - Cada questão tem no máximo uma resolução oficial associada.
    # related_name='resolucao' permite fazer questao.resolucao.
    questao = models.OneToOneField(Questao, on_delete=models.CASCADE, related_name='resolucao')
    # Texto da resolução.
    texto = models.TextField()

    # Representação textual da resolução.
    def __str__(self):
        # Exibe a qual questão a resolução pertence.
        return f"Resolução - Questão {self.questao.id}"
