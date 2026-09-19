# Simulado — site de questões de concurso

Aplicação web em Django para resolver questões de concursos públicos, acompanhar o próprio
desempenho e discutir as questões com outros usuários.

## Funcionalidades

- **Resolução de questões** de múltipla escolha (ME) e certo/errado (CE), com correção imediata,
  resolução oficial e paginação.
- **Filtros** por banca, órgão, cargo, ano, matéria e tópico.
- **Painel de desempenho** (`/usuarios/dashboard/`) com total de respostas e taxa de acerto,
  filtrável por banca, cargo, matéria e tópico.
- **Fórum por questão**: comentários, respostas a comentários e curtidas; a resolução oficial
  aceita curtidas e descurtidas.
- **Contas de usuário**: cadastro (a conta já nasce ativa e o usuário entra logado), login, logout
  e recuperação de senha por e-mail.
- **Importação de questões por planilha CSV** (`/importar/`), restrita a quem tem a permissão
  `questoes.importar_questoes`.
- **Admin do Django** (`/admin/`) para cadastrar e editar bancas, órgãos, cargos, matérias,
  tópicos e questões.

## Tecnologias

- Python 3.14 e Django 6.1
- SQLite (banco padrão em desenvolvimento)
- HTML, CSS e JavaScript puros, sem framework de front-end

## Como rodar localmente

```bash
git clone https://github.com/dlDreyfus/site_questoes.git
cd site_questoes

python -m venv venv
source venv/bin/activate          # no Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# gere uma chave e cole em DJANGO_SECRET_KEY no .env:
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Acesse http://127.0.0.1:8000/. Crie uma conta em "Cadastrar Novo Usuário" ou entre com o
superusuário, que também dá acesso ao `/admin/`.

### Variáveis de ambiente

| Variável               | Obrigatória | Descrição                                                        |
|------------------------|-------------|-------------------------------------------------------------------|
| `DJANGO_SECRET_KEY`    | Sim         | Chave secreta do Django                                          |
| `DJANGO_DEBUG`         | Não         | `True` (padrão) em desenvolvimento; `False` em produção          |
| `DJANGO_ALLOWED_HOSTS` | Em produção | Domínios do site separados por vírgula (ex: `meusite.pythonanywhere.com`) |

As variáveis podem ser definidas no ambiente ou no arquivo `.env` na raiz do projeto, que fica
fora do git. As do ambiente têm prioridade.

### E-mails

Só a recuperação de senha envia e-mails. Nenhum servidor de e-mail vem configurado,
então o Django tenta usar um servidor SMTP em `localhost:25`. Para testar localmente sem servidor
de e-mail, defina em `core/settings.py`:

```python
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
```

Assim os e-mails, com o link para redefinir a senha, aparecem no terminal do `runserver`.

## Importação de questões por CSV

A página `/importar/` mostra todas as colunas aceitas e oferece uma planilha modelo para baixar
(`/importar/modelo.csv`). Em resumo:

- Cada linha é uma questão completa. Bancas, órgãos, cargos, matérias e tópicos são
  reaproveitados quando já existem e criados quando não existem.
- `topicos` é obrigatória e aceita vários tópicos separados por `|`.
- `tipo` é `ME` ou `CE`; o `gabarito` é a letra da correta (ME) ou `CERTO`/`ERRADO` (CE).
- **Tudo ou nada**: todas as linhas são validadas antes de gravar. Se houver qualquer erro, nada
  é importado e cada erro aparece com linha, coluna e motivo (a numeração segue a do Excel, com o
  cabeçalho na linha 1).
- Um `codigo` que já existe no banco, ou que se repete na planilha, é erro.

Para liberar a importação a um usuário, dê a ele a permissão "Pode importar questões por planilha
CSV" pelo admin. Se existir um grupo chamado `Administrador`, a migração já concede a permissão a
ele.

## Testes

```bash
python manage.py test
```

## Estrutura

```
core/        configurações do projeto (settings, urls)
questoes/    questões, resolução, filtros, fórum, curtidas e importação CSV
usuarios/    modelo de usuário próprio, cadastro, login, recuperação de senha e painel de desempenho
templates/   base.html compartilhado
static/      CSS e JavaScript
```
