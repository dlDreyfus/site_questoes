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
