# Simulado — site de questões de concurso

Aplicação web em Django para resolver questões de concursos públicos, acompanhar o próprio
desempenho e discutir as questões com outros usuários.

## Funcionalidades

- **Resolução de questões** de múltipla escolha (ME) e certo/errado (CE), com correção imediata,
  resolução oficial e paginação.
- **Busca textual**, antes dos filtros: cada palavra digitada precisa aparecer no enunciado, no
  código ou em alguma alternativa da questão.
- **Filtros em cascata** por banca, órgão, cargo, ano, matéria e tópico: ao escolher um filtro, os
  demais dropdowns passam a listar só as opções que ainda têm questões com aquela escolha.
- **Seleção múltipla em todos os filtros** (ex: `?banca=1&banca=2`): dentro de um filtro vale
  qualquer opção marcada; entre filtros diferentes, todos precisam ser atendidos. Tópicos marcados
  refinam só a matéria deles (Administrativo com Licitações + Constitucional inteira). O filtro é
  aplicado ao fechar o dropdown.
- **Subcabeçalho com o total de questões** cadastradas, no topo de todas as páginas para quem está
  logado. Na lista e no painel, conta só as questões que atendem aos filtros escolhidos.
- **Simulados** (`/simulados/novo/`, a partir do Meu Desempenho ou da lista de questões, que já leva
  os filtros escolhidos): o usuário escolhe os mesmos filtros
  da lista (em cascata) mais a **situação** — "Somente questões que errei" (a última resposta à
  questão foi errada) ou "Questões que ainda não resolvi" — e o site grava um conjunto fixo com as
  questões que atendem. Dentro do simulado cada questão é respondida uma vez, e o progresso e o
  resultado aparecem no simulado e na lista "Meus simulados" do Meu Desempenho. As respostas também
  entram nas estatísticas do painel. Cada simulado pode ser **renomeado** e **apagado** (com página
  de confirmação); apagar mantém as respostas no desempenho do usuário.
- **Painel de desempenho** (`/usuarios/dashboard/`) com total de respostas e taxa de acerto,
  filtrável por banca, cargo, matéria e tópico.
- **Fórum por questão**: comentários, respostas a comentários e curtidas; a resolução oficial
  aceita curtidas e descurtidas.
- **Contas de usuário**: cadastro (a conta já nasce ativa e o usuário entra logado), login, logout
  e recuperação de senha por e-mail.
- **Importação de questões por planilha CSV** (`/importar/`), restrita a quem tem a permissão
  `questoes.importar_questoes`.
  A mesma tela traz a tabela de questões com **código, curtidas e descurtidas** da resolução oficial
  e **respondidas** (quantas vezes a questão foi respondida, somando todos os usuários)
  (ordem: mais descurtidas, mais respondidas, mais curtidas, código). Só o **superusuário e o grupo "Administrador"**
  veem, em cada linha, **Alterar** (abre a questão no admin do Django, exige `is_staff`) e
  **Deletar** (página de confirmação; apaga também alternativas, resolução, histórico e comentários).
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
| `DJANGO_DEBUG`         | Não         | Padrão `False` (produção); use `True` em desenvolvimento (o `.env.example` já traz `True`) |
| `DJANGO_ALLOWED_HOSTS` | Em produção | Domínios do site separados por vírgula (ex: `meusite.pythonanywhere.com`). Sem a variável, usa `dlDreyfus.pythonanywhere.com` |
| `EMAIL_HOST`           | Em produção | Servidor SMTP (ex: `smtp.gmail.com`). Vazio: e-mails só no terminal (veja "E-mails") |
| `EMAIL_PORT`           | Não         | Porta SMTP com STARTTLS. Padrão `587` |
| `EMAIL_HOST_USER`      | Com SMTP    | Usuário do servidor SMTP (no Gmail, o endereço da conta) |
| `EMAIL_HOST_PASSWORD`  | Com SMTP    | Senha do servidor SMTP (no Gmail, a senha de app) |
| `DJANGO_DEFAULT_FROM_EMAIL` | Não    | Remetente dos e-mails. Padrão `Simulado <nao-responda@simulado.local>` |

As variáveis podem ser definidas no ambiente ou no arquivo `.env` na raiz do projeto, que fica
fora do git. As do ambiente têm prioridade.

### E-mails

Só a recuperação de senha envia e-mails (com o nome de usuário e o link para criar uma nova senha).

- **Sem `EMAIL_HOST`** (o normal em desenvolvimento): `MAILERS` usa o backend `console` do Django.
  Nenhum e-mail é realmente enviado; o conteúdo aparece no terminal do `runserver` ou no log do servidor.
- **Com `EMAIL_HOST`**: os e-mails saem pelo servidor SMTP configurado (STARTTLS, porta 587 por padrão).

Em produção, a recuperação de senha só funciona de fato com o SMTP configurado. No PythonAnywhere,
contas gratuitas só enviam pelo Gmail: use `smtp.gmail.com`, a conta como `EMAIL_HOST_USER` e uma
[senha de app](https://myaccount.google.com/apppasswords) (exige verificação em duas etapas) como
`EMAIL_HOST_PASSWORD`. Depois de preencher o `.env`, teste com
`python manage.py sendtestemail seu-email@exemplo.com` e recarregue o site na aba Web.

## Deploy no PythonAnywhere

O site roda em https://dlDreyfus.pythonanywhere.com, com o projeto em `~/site_questoes` e o
virtualenv `meu-ambiente`. Os comandos abaixo são para um **console Bash** do PythonAnywhere.

### Atualizar o site (a cada nova versão no GitHub)

```bash
workon meu-ambiente
cd ~/site_questoes
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

Depois, clique em **Reload** na aba **Web**. O `collectstatic` é obrigatório sempre que CSS ou
JavaScript mudarem: o site serve a cópia reunida em `staticfiles/`, não a pasta `static/`.

### Primeira instalação

1. **Código e dependências**
   ```bash
   git clone https://github.com/dlDreyfus/site_questoes.git ~/site_questoes
   mkvirtualenv meu-ambiente --python=python3.13
   pip install -r ~/site_questoes/requirements.txt
   ```
2. **Arquivo `~/site_questoes/.env`** (pela aba **Files** ou com `nano`), a partir do `.env.example`:
   ```ini
   DJANGO_SECRET_KEY=<gere uma chave nova, veja "Como rodar localmente">
   DJANGO_DEBUG=False
   DJANGO_ALLOWED_HOSTS=dlDreyfus.pythonanywhere.com
   # E-mail (veja "E-mails"); vazio, a recuperação de senha não envia nada
   EMAIL_HOST=smtp.gmail.com
   EMAIL_PORT=587
   EMAIL_HOST_USER=sua-conta@gmail.com
   EMAIL_HOST_PASSWORD=<senha de app de 16 letras>
   DJANGO_DEFAULT_FROM_EMAIL=Simulado <sua-conta@gmail.com>
   ```
   O `.env` fica fora do git: o `git pull` nunca o altera. Nunca deixe `DJANGO_DEBUG=True` em produção
   (as páginas de erro mostrariam configurações e código para qualquer visitante).
3. **Banco, arquivos estáticos e administrador**
   ```bash
   cd ~/site_questoes
   python manage.py migrate
   python manage.py collectstatic --noinput
   python manage.py createsuperuser
   ```
4. **Aba Web**
   - **Virtualenv**: `/home/dlDreyfus/.virtualenvs/meu-ambiente`
   - **WSGI configuration file**: só precisa apontar para o projeto. As variáveis ficam no `.env`,
     que o `core/settings.py` lê sozinho; não as repita aqui (o valor do WSGI teria prioridade sobre
     o `.env`, e o console Bash não o enxerga).
     ```python
     import os
     import sys

     caminho = '/home/dlDreyfus/site_questoes'
     if caminho not in sys.path:
         sys.path.insert(0, caminho)

     os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings'

     from django.core.wsgi import get_wsgi_application
     application = get_wsgi_application()
     ```
   - **Static files**: URL `/static/` → Directory `/home/dlDreyfus/site_questoes/staticfiles`
   - Clique em **Reload**.

### Problemas comuns

| Sintoma | Causa e solução |
|---------|-----------------|
| `KeyError: 'DJANGO_SECRET_KEY'` ao rodar `manage.py` no console | Falta o `~/site_questoes/.env` (variáveis definidas só no arquivo WSGI não valem no console). Crie o `.env` com a mesma chave usada pelo site: trocar a chave desloga todos os usuários. |
| **Bad Request (400)** em todas as páginas | O domínio não está em `DJANGO_ALLOWED_HOSTS`. Uma linha `DJANGO_ALLOWED_HOSTS=` vazia no `.env` bloqueia tudo. O Error log da aba Web mostra `Invalid HTTP_HOST header`. |
| Admin (ou o site) sem CSS | Faltou o `collectstatic` ou o mapeamento `/static/` aponta para `static/` em vez de `staticfiles/`. Teste abrindo `/static/admin/css/base.css`. |
| Mudança de CSS/JS não aparece | Faltou `collectstatic --noinput` e **Reload** depois do `git pull`; no navegador, Ctrl+F5. |
| Recuperação de senha não chega | `EMAIL_HOST` vazio no `.env` ou senha errada (no Gmail, use a senha de app). Teste com `python manage.py sendtestemail seu-email@exemplo.com`. |

Depois de mudar o `.env` ou o arquivo WSGI, clique em **Reload**: o site só lê as variáveis ao iniciar.

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
