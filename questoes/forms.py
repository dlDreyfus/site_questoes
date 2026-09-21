from django import forms
from django.core.validators import FileExtensionValidator
from django.template.defaultfilters import filesizeformat

from .models import COMENTARIO_TAMANHO_MAXIMO, Comentario, Simulado


# Edição do simulado: só o nome. As questões são um conjunto fixo (para outras questões, crie outro simulado)
class SimuladoForm(forms.ModelForm):
    class Meta:
        model = Simulado
        fields = ['nome']
        labels = {'nome': 'Nome do simulado'}
        error_messages = {'nome': {'required': 'Dê um nome ao simulado.'}}


# Valida o comentário ou resposta do fórum. A questão e o autor vêm da view; a caixa de texto é
# montada no template (cada questão precisa de um id próprio), com rows="3" e maxlength do limite.
class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ['texto']
        error_messages = {
            'texto': {
                'required': 'Escreva algo antes de publicar.',
                'max_length': f'O comentário pode ter no máximo {COMENTARIO_TAMANHO_MAXIMO} caracteres '
                              '(o seu tem %(show_value)d).',
            },
        }

# Tamanho máximo aceito para a planilha (5 MB é suficiente para milhares de questões em texto)
TAMANHO_MAXIMO_CSV = 5 * 1024 * 1024


# Formulário de envio da planilha de importação (.csv)
class ImportarCSVForm(forms.Form):
    arquivo = forms.FileField(
        label='Planilha (.csv)',
        validators=[FileExtensionValidator(allowed_extensions=['csv'])],
        # 'accept' faz o seletor de arquivos do navegador já mostrar só arquivos .csv
        widget=forms.ClearableFileInput(attrs={'accept': '.csv,text/csv'}),
    )

    def clean_arquivo(self):
        arquivo = self.cleaned_data['arquivo']
        if arquivo.size > TAMANHO_MAXIMO_CSV:
            raise forms.ValidationError(
                f'O arquivo tem {filesizeformat(arquivo.size)}; o limite é {filesizeformat(TAMANHO_MAXIMO_CSV)}.'
            )
        if arquivo.size == 0:
            raise forms.ValidationError('O arquivo enviado está vazio.')
        return arquivo
