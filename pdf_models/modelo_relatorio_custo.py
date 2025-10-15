# Em: pdf_models/modelo_relatorio_custo.py

from fpdf import FPDF
from models import Orcamento
import os
from datetime import datetime

# --- CAMINHO DO LOGO RESTAURADO ---
# Voltando a usar o caminho específico que você tinha
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(MODEL_DIR, '..', 'static', 'construtora_araras','logo_construtora.png')

def format_brl_relatorio(value):
    if value is None or not isinstance(value, (int, float)):
        return "R$ 0,00"
    if value < 0:
        # Usa parênteses para negativos, uma convenção contábil clara
        return f"(R$ {abs(value):,.2f})".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

class RelatorioCustoPDF(FPDF):
    def __init__(self, *args, orcamento: Orcamento, **kwargs):
        super().__init__(*args, **kwargs)
        self.orcamento = orcamento
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        # --- LOGO DE VOLTA NO LUGAR CERTO ---
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=10, y=0, w=50)

        self.set_y(15)
        self.set_font("Arial", "B", 16)
        self.cell(0, 10, "Relatório de Análise de Custo", 0, 1, 'C')
        
        self.set_font("Arial", "I", 10)
        self.cell(0, 8, f"Orçamento #{self.orcamento.numero} - {self.orcamento.nome_cliente}", 0, 1, 'C')
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128)
        self.cell(0, 10, f"Página {self.page_no()}", 0, 0, 'C')
        self.cell(0, 10, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", 0, 0, 'R')
        
# Função auxiliar para desenhar uma linha da tabela, como no modelo antigo
def draw_line_item(pdf, label, value, is_total=False, is_summary=False):
    pdf.set_x(15) # Alinha todas as linhas à esquerda com uma margem
    font_style = "B" if is_total or is_summary else ""
    pdf.set_font("Arial", font_style, 10)
    pdf.cell(140, 8, label, border=1)
    
    # Formata o valor e o alinha à direita
    formatted_value = format_brl_relatorio(value)
    pdf.cell(40, 8, formatted_value, border=1, ln=1, align='R')

def gerar_pdf_relatorio_custo(file_path, orcamento: Orcamento):
    pdf = RelatorioCustoPDF(orcamento=orcamento, unit="mm", format="A4")
    pdf.add_page()
    
    # --- Seção de Cálculos com a Lógica Atualizada ---
    receita_bruta = orcamento.valor_obra_total or 0

    # Pega os novos percentuais de imposto
    perc_imposto_servico = orcamento.percentual_imposto_servico or 0
    perc_imposto_material = orcamento.percentual_imposto_material or 0

    custo_mo = orcamento.custo_mao_de_obra or 0
    custo_mat = orcamento.custo_materiais or 0

    despesas_extras_list = orcamento.despesas_extras or []
    custo_despesas_extras = sum(item.get('valor', 0) for item in despesas_extras_list)

    # --- Lógica de cálculo dos impostos separados ---
    # 1. Pega os totais brutos de serviços e materiais dos itens do orçamento
    total_servicos_bruto = sum(item['valor'] * item['quantidade'] for item in orcamento.itens if item['tipo'] == 'servico')
    total_materiais_bruto = sum(item['valor'] * item['quantidade'] for item in orcamento.itens if item['tipo'] == 'material')

    # 2. Calcula o valor monetário de cada imposto
    valor_imposto_servico = total_servicos_bruto * (perc_imposto_servico / 100)
    valor_imposto_material = total_materiais_bruto * (perc_imposto_material / 100)

    # 3. Calcula as somas para o relatório
    receita_liquida = receita_bruta - valor_imposto_servico - valor_imposto_material
    custo_total = custo_mo + custo_mat + custo_despesas_extras
    soma_de_custos_e_impostos = custo_total + valor_imposto_servico + valor_imposto_material
    lucro_liquido = receita_bruta - soma_de_custos_e_impostos
    dizimo = lucro_liquido * 0.10 if lucro_liquido > 0 else 0

    # --- Desenho do Relatório no Estilo Tabela ---
    
    # 1. RECEITA
    pdf.set_font("Arial", "B", 12)
    pdf.set_x(15)
    pdf.cell(0, 10, "Receita Bruta", ln=1, align='L')
    draw_line_item(pdf, "Valor Total do Orçamento", receita_bruta)
    pdf.ln(8)
    
    # 2. DEDUÇÕES E CUSTOS
    pdf.set_font("Arial", "B", 12)
    pdf.set_x(15)
    pdf.cell(0, 10, "Deduções e Custos", ln=1, align='L')
    draw_line_item(pdf, "(-) Custo de Mão de Obra", custo_mo)
    draw_line_item(pdf, "(-) Custo de Materiais", custo_mat)
    draw_line_item(pdf, f"(-) Imposto sobre Serviço ({perc_imposto_servico:.2f}%)", valor_imposto_servico)
    draw_line_item(pdf, f"(-) Imposto sobre Material ({perc_imposto_material:.2f}%)", valor_imposto_material)
    
    # --- Loop para adicionar as despesas extras dinâmicas ---
    if despesas_extras_list:
        for item in despesas_extras_list:
            label = f"(-) {item.get('descricao', 'Despesa Extra')}"
            value = item.get('valor', 0)
            draw_line_item(pdf, label, value)

    pdf.ln(5)
    
    # 3. RESULTADOS
    pdf.set_font("Arial", "B", 12)
    pdf.set_x(15)
    pdf.cell(0, 10, "Resultado da Análise", ln=1, align='L')
    draw_line_item(pdf, "Soma de Todos os Custos e Impostos", soma_de_custos_e_impostos, is_summary=True)
    pdf.ln(5)

    # --- Destaque para o Lucro Líquido ---
    pdf.set_x(15)
    if lucro_liquido >= 0:
        pdf.set_fill_color(230, 255, 230) # Verde claro
        pdf.set_text_color(0, 100, 0) # Verde escuro
    else:
        pdf.set_fill_color(255, 230, 230) # Vermelho claro
        pdf.set_text_color(180, 0, 0) # Vermelho escuro

    pdf.set_font("Arial", "B", 12)
    pdf.cell(140, 10, "Lucro Líquido Final:", border=1, fill=True)
    pdf.cell(40, 10, format_brl_relatorio(lucro_liquido), border=1, ln=1, align='R', fill=True)

    # Restaurar cores padrão
    pdf.set_fill_color(255)
    pdf.set_text_color(0)
    pdf.ln(5)
    
    # Dízimo
    draw_line_item(pdf, "Valor Sugerido para Dízimo (10% do Lucro)", dizimo)

    # --- Finalização ---
    # Escreve os bytes do PDF diretamente no objeto BytesIO
    file_path.write(pdf.output(dest='S').encode('latin-1'))