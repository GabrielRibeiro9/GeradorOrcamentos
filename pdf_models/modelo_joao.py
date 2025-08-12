import os
import re
import json
from fpdf import FPDF
from models import Orcamento


# --- Constantes de layout que sua classe usa ---
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, 'static', 'joao')
FULL_PAGE_BACKGROUND_IMAGE = os.path.join(STATIC_DIR, 'fundo_joao.png')
LOGO_PATH = os.path.join(STATIC_DIR, 'logo_joao.png')
FIXED_RECT_HEIGHT = 7
PADDING_RECT_VERTICAL = 1
LINE_HEIGHT = 4
TABLE_COL_WIDTHS = [10, 80, 30, 40, 30]
TABLE_TOTAL_WIDTH = sum(TABLE_COL_WIDTHS)

# --- Função auxiliar que sua classe usa ---
def format_brl(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X",".")

class JoaoPDF(FPDF):
    def __init__(self, *args, orcamento: Orcamento, **kwargs):
        super().__init__(*args, **kwargs)
        # Armazena o objeto orcamento inteiro na criação da classe
        self.orcamento = orcamento
        self.set_auto_page_break(auto=True, margin=15)
        self.alias_nb_pages()

    def header(self):
        if os.path.exists(FULL_PAGE_BACKGROUND_IMAGE):
            self.image(FULL_PAGE_BACKGROUND_IMAGE, 0, 0, self.w, self.h)
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=145, y=5, w=60)
        
        self.set_xy(0, 50)
        self.set_font("Arial", "B", 24)
        self.set_text_color(0, 51, 102)
        titulo_documento = self.orcamento.status.upper() if self.orcamento.status else "ORÇAMENTO"
        self.cell(self.w, 10, titulo_documento, align='C', ln=True)
        
        self.set_xy(0, self.get_y() - 2)
        self.set_font("Arial", "B", 18)
        # Usa os dados diretamente do objeto orcamento armazenado
        self.cell(self.w, 8, f"Nº{self.orcamento.numero}", align='C', ln=True)
        
        self.ln(-2)
        self.set_font("Arial", "", 6)
        self.set_text_color(0, 51, 102)
        self.set_x(10)
        self.cell(0, 4, f"DATA EMISSÃO: {self.orcamento.data_emissao}", align='L', ln=True)
        self.ln(2)

    def footer(self):
        # Posiciona o cursor a 1.5 cm do final da página
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128) # Cinza
        # Cria o texto "Página X de Y"
        self.cell(0, 10, f"Página {self.page_no()} de {{nb}}", 0, 0, "C")

    def draw_table(self, itens_do_tipo):
        titles = ["ITEM", "DESCRIÇÃO", "QTD", "UNITÁRIO", "TOTAL"]
        self.set_fill_color(255, 204, 0)
        self.set_font("Arial", "B", 9)
        self.set_text_color(0, 51, 102)
        self.set_x(10)
        for w, title in zip(TABLE_COL_WIDTHS, titles):
            self.cell(w, 8, title, 1, align='C', fill=True)
        self.ln()

        for idx, it in enumerate(itens_do_tipo, start=1):
            self.set_font("Arial", "", 9)
            self.set_text_color(0, 0, 0)
            start_y = self.get_y()
            nome_limpo = str(it.get("nome", "")).encode('latin-1', 'replace').decode('latin-1')
            lines = self.multi_cell(TABLE_COL_WIDTHS[1], 4, it.get("nome", ""), split_only=True)
            text_height = len(lines) * 4
            row_height = max(7, text_height + 2)

            if self.get_y() + row_height > self.page_break_trigger:
                self.add_page()
                self.set_font("Arial", "B", 9)
                self.set_fill_color(255, 204, 0)
                self.set_text_color(0, 51, 102)
                self.set_x(10)

                for w, title in zip(TABLE_COL_WIDTHS, titles):
                    self.cell(w, 8, title, 1, align='C', fill=True)
                self.ln()
                self.set_text_color(0, 0, 0)
                self.set_font("Arial", "", 9)
                start_y = self.get_y()
            
            self.set_y(start_y)
            self.set_x(10)
            self.cell(TABLE_COL_WIDTHS[0], row_height, str(idx), border=1, align='C')
            x_after_item = self.get_x()
            y_text_pos = start_y + (row_height - text_height) / 2
            self.set_xy(x_after_item, y_text_pos)
            self.multi_cell(TABLE_COL_WIDTHS[1], 5, it.get("nome", ""), border=0, align='L')
            self.rect(x=x_after_item, y=start_y, w=TABLE_COL_WIDTHS[1], h=row_height)
            self.set_y(start_y)
            self.set_x(x_after_item + TABLE_COL_WIDTHS[1])
            self.cell(TABLE_COL_WIDTHS[2], row_height, str(it.get("quantidade", "")), border=1, align='C')
            self.cell(TABLE_COL_WIDTHS[3], row_height, format_brl(it.get('valor', 0)), border=1, align="R")
            quantidade = it.get('quantidade', 0)
            valor = it.get('valor', 0)
            total = quantidade * valor
            self.cell(TABLE_COL_WIDTHS[4], row_height, format_brl(total), border=1, align="R", ln=1)

    def draw_info_line(self, label, value, is_italic=False):
        """
        Desenha uma linha de informação com rótulo e valor,
        com quebra de linha do valor recuada sob o rótulo.
        """
        if not value:
            return
            
        self.set_x(10)
        self.set_font("Arial", "B", 10)
        self.set_text_color(0, 51, 102)
        
        label_text = f"{label}:"
        self.cell(self.get_string_width(label_text) + 2, 5, label_text, 0, 0, 'L')
        
        # 1. Calcula os espaços disponíveis
        value_x_start = self.get_x()
        first_line_width = self.w - self.r_margin - value_x_start
        subsequent_lines_width = self.w - self.r_margin - 10 # 10 é a margem inicial (start_x)
        
        text = str(value).encode('latin-1', 'replace').decode('latin-1')
        
        # 2. Define a fonte do valor e pré-calcula as linhas
        font_style = "I" if is_italic else ""
        self.set_font("Arial", font_style, 10)
        self.set_text_color(0, 0, 0)
        lines = self.multi_cell(first_line_width, 5, text, split_only=True)
        
        # 3. Desenha o conteúdo linha a linha com controle total da posição
        if lines:
            current_y = self.get_y()
            self.set_xy(value_x_start, current_y)
            self.cell(first_line_width, 5, lines[0], ln=1) # Usa ln=1 para pular para a próxima linha

            remaining_text = " ".join(lines[1:])
            if remaining_text:
                self.set_x(10) # Recua para o início da margem
                self.multi_cell(subsequent_lines_width, 5, remaining_text, 0, 'L')
        
        self.ln(1) # Espaço final  

    # A função agora não recebe mais 'orcamento' como parâmetro, pois já o tem
    def draw_content(self):
        orcamento = self.orcamento

        # --- LÓGICA CORRIGIDA E SIMPLIFICADA ---
        # Sempre usamos os campos do próprio orçamento, pois eles são a "foto" fiel.
        nome = orcamento.nome_cliente
        telefone = orcamento.telefone_cliente
        logradouro = orcamento.logradouro_cliente
        numero_casa = orcamento.numero_casa_cliente
        complemento = orcamento.complemento_cliente
        bairro = orcamento.bairro_cliente
        cidade_uf = orcamento.cidade_uf_cliente
        # --- FIM DA CORREÇÃO ---

        endereco_base = f"{logradouro}, {numero_casa}" if logradouro and numero_casa else (logradouro or "")

        # Adiciona o complemento APENAS se ele existir e não estiver vazio
        if complemento and complemento.strip():
            endereco_completo = f"{endereco_base} - {complemento} - {bairro} - {cidade_uf}"
        else:
            endereco_completo = f"{endereco_base} - {bairro} - {cidade_uf}"

        # O restante da sua função continua exatamente o mesmo...
        campos = [
            ("CLIENTE: ", nome),
            ("ENDEREÇO: ", endereco_completo),
            ("TELEFONE: ", telefone),
            ("DESCRIÇÃO DO SERVIÇO: ", orcamento.descricao_servico)
        ]
        
        current_y = 70
        for label, value in campos:
            is_desc = label.startswith("DESCRIÇÃO")
            self.set_font("Arial", "B", 10)
            w_label = self.get_string_width(label)
            w_val = TABLE_TOTAL_WIDTH - w_label - 2 * PADDING_RECT_VERTICAL
            if not is_desc:
                h_rect = FIXED_RECT_HEIGHT
            else:
                self.set_font("Arial", "", 10)
                lines = self.multi_cell(w_val, LINE_HEIGHT, str(value), split_only=True)
                h_rect = max(FIXED_RECT_HEIGHT, len(lines) * LINE_HEIGHT + 2 * PADDING_RECT_VERTICAL)
            self.set_fill_color(240, 240, 240); self.rect(10, current_y, TABLE_TOTAL_WIDTH, h_rect, "F")
            self.set_xy(10 + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
            self.set_font("Arial", "B", 10); self.set_text_color(0, 51, 102); self.cell(w_label, LINE_HEIGHT, label, ln=0)
            self.set_text_color(0, 0, 0); self.set_font("Arial", "", 10)
            self.set_xy(10 + w_label + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
            self.multi_cell(w_val, LINE_HEIGHT, str(value))
            current_y += h_rect + 2
        
        self.set_y(current_y); self.ln(2)

        servicos = [i for i in orcamento.itens if i.get("tipo", "").lower() == "servico"]
        materiais = [i for i in orcamento.itens if i.get("tipo", "").lower() == "material"]

        if servicos:
            self.ln(4)
            self.set_font("Arial", "B", 12)
            self.set_text_color(0, 51, 102)
            self.cell(0, 10, "Serviços", ln=True, align="L")
            self.draw_table(servicos)
            
        if materiais:
            # --- LÓGICA DE VERIFICAÇÃO DE ESPAÇO ---
            # Calcula o espaço mínimo necessário para o título, o cabeçalho e uma linha.
            # 4 (ln) + 10 (título) + 8 (cabeçalho da tabela) + 7 (altura mínima de uma linha) = 29
            espaco_necessario = 29 
            
            # Se o espaço restante na página for menor que o necessário...
            if self.get_y() + espaco_necessario > self.page_break_trigger:
                self.add_page() # ...força uma nova página ANTES de desenhar o título.
            # --- FIM DA VERIFICAÇÃO ---

            # Agora sim, desenha o título e a tabela com a certeza de que há espaço
            self.ln(4)
            self.set_font("Arial", "B", 12)
            self.set_text_color(0, 51, 102)
            self.cell(0, 10, "Materiais", ln=True, align="L")
            self.draw_table(materiais)


        self.ln(4); self.set_font("Arial", "B", 10); self.set_fill_color(255, 204, 0); self.set_text_color(0, 51, 102)
        label_w = sum(TABLE_COL_WIDTHS[:-1])
        self.set_x(10)
        self.cell(label_w, 8, "TOTAL GERAL:", 0, 0, 'R', fill=True)
        self.cell(TABLE_COL_WIDTHS[-1], 8, format_brl(orcamento.total_geral), 0, 1, "R", fill=True)
        
        self.ln(5)

        condicao_pagamento_str = orcamento.condicao_pagamento
        condicao_formatada = condicao_pagamento_str # Usa o texto original como padrão

        # Verifica se o texto parece ser um JSON de lista
        if condicao_pagamento_str and condicao_pagamento_str.strip().startswith('['):
            try:
                # Tenta decodificar o JSON para uma lista Python
                parcelas = json.loads(condicao_pagamento_str)
                if isinstance(parcelas, list) and parcelas:
                    # Formata a lista de parcelas em uma string legível
                    partes = []
                    for p in parcelas:
                        descricao = p.get('descricao', 'Parcela')
                        valor = float(p.get('valor', 0))
                        partes.append(f"{descricao}: {format_brl(valor)}") # Usa a função format_brl que já existe
                    
                    # Junta tudo em uma única linha
                    condicao_formatada = " + ".join(partes)
            except (json.JSONDecodeError, TypeError):
                # Se não for um JSON válido ou der erro, usa o texto original sem quebrar o programa
                condicao_formatada = condicao_pagamento_str

        self.draw_info_line("Condição de Pagamento", condicao_formatada)        
        self.draw_info_line("Prazo de Entrega", orcamento.prazo_entrega)
        self.draw_info_line("Garantia", orcamento.garantia)
        self.draw_info_line("Observações", orcamento.observacoes, is_italic=True)

        self.set_y(-30); self.set_font("Arial", "B", 10); self.set_text_color(0, 51, 102)
        self.cell(0, 7, "VALIDADE DO DOCUMENTO:", ln=True)
        self.set_font("Arial", "B", 10); self.cell(0, 7, orcamento.data_validade, ln=True)

# --- FUNÇÃO GERADORA PRINCIPAL (A ÚNICA QUE O APP.PY CHAMA) ---
def gerar_pdf_joao(file_path, orcamento: Orcamento):
    
    def clean_text(text: str) -> str:
        if not text:
            return ""

        s = str(text)

        # (1) Converte sequências ESCAPADAS tipo \u00a0 para o caractere real
        s = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)

        # (2) Troca NBSP e variações por espaço normal
        s = (s.replace("\u00A0", " ")
            .replace("\u202F", " ")
            .replace("\u2007", " ")
            .replace("\u2009", " "))

        # (3) Normaliza aspas/traços “especiais”
        s = (s.replace("“", '"').replace("”", '"')
            .replace("‘", "'").replace("’", "'")
            .replace("–", "-").replace("—", "-"))

        # (4) Colapsa espaços extras
        s = re.sub(r"[ \t]+", " ", s)

        # (5) Remove controles fora do intervalo imprimível e força latin-1
        s = re.sub(r"[^\x09\x0A\x0D\x20-\xFF]", "", s)
        return s.encode("latin-1", "replace").decode("latin-1")

    # Limpa todos os campos de texto relevantes do orçamento ANTES de passá-los para o PDF
    orcamento.condicao_pagamento = clean_text(orcamento.condicao_pagamento)
    orcamento.prazo_entrega = clean_text(orcamento.prazo_entrega)
    orcamento.garantia = clean_text(orcamento.garantia)
    orcamento.observacoes = clean_text(orcamento.observacoes)
    orcamento.descricao_servico = clean_text(orcamento.descricao_servico)
    if orcamento.cliente:
        orcamento.cliente.nome = clean_text(orcamento.cliente.nome)
        # Continue para outros campos do cliente se necessário
    else:
        orcamento.nome_cliente = clean_text(orcamento.nome_cliente)

    # Limpa a descrição dos itens
    for item in orcamento.itens:
        item['nome'] = clean_text(item.get('nome', ''))
        
    # --- FIM DA ETAPA DE LIMPEZA ---


    # 1. Cria a instância da classe, agora com os dados já limpos
    pdf = JoaoPDF(format="A4", orcamento=orcamento)
    
    # 2. Adiciona a página
    pdf.add_page()
    
    # 3. Desenha o conteúdo
    pdf.draw_content()
    
    # 4. Salva o resultado
    # O pdf.output() já lida com a codificação, agora que os textos estão limpos
    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    file_path.write(pdf_bytes)