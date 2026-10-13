import re

from django.db import migrations

# Identificação no início do enunciado, ex: "Questão aleatória de Interpretação FGV #13:"
IDENTIFICACAO = re.compile(r'^(Questão [^\n]*?#\d+:)[ \t]*(?=\S)')
# A mesma identificação já separada do enunciado por uma linha em branco
IDENTIFICACAO_SEPARADA = re.compile(r'^(Questão [^\n]*?#\d+:)\n\n')


def _substituir(apps, padrao, troca):
    Questao = apps.get_model('questoes', 'Questao')
    for questao in Questao.objects.filter(enunciado__startswith='Questão '):
        novo = padrao.sub(troca, questao.enunciado, count=1)
        if novo != questao.enunciado:
            questao.enunciado = novo
            questao.save(update_fields=['enunciado'])


def separar(apps, schema_editor):
    """Põe a identificação no topo, separada do enunciado teórico por uma linha em branco."""
    _substituir(apps, IDENTIFICACAO, r'\1\n\n')


def juntar(apps, schema_editor):
    _substituir(apps, IDENTIFICACAO_SEPARADA, r'\1 ')


class Migration(migrations.Migration):

    dependencies = [
        ('questoes', '0010_simulados'),
    ]

    operations = [
        migrations.RunPython(separar, juntar),
    ]
