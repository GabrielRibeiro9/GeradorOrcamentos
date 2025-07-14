import os
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

    def header(self):
        if os.path.exists(FULL_PAGE_BACKGROUND_IMAGE):
            self.image(FULL_PAGE_BACKGROUND_IMAGE, 0, 0, self.w, self.h)
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=145, y=5, w=60)
        
        self.set_xy(0, 50)
        self.set_font("Arial", "B", 24)
        self.set_text_color(0, 51, 102)
        self.cell(self.w, 10, "ORÇAMENTO", align='C', ln=True)
        
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
        pass

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
            lines = self.multi_cell(TABLE_COL_WIDTHS[1], 5, it.get("nome", ""), split_only=True)
            text_height = len(lines) * 5
            row_height = max(10, text_height + 4)
            if self.get_y() + row_height > self.page_break_trigger:
                self.add_page()
            
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

    # A função agora não recebe mais 'orcamento' como parâmetro, pois já o tem
    def draw_content(self):
        orcamento = self.orcamento
        if orcamento.cliente:
            nome = orcamento.cliente.nome
            telefone = orcamento.cliente.telefone
            logradouro = orcamento.cliente.logradouro
            numero_casa = orcamento.cliente.numero_casa
            bairro = orcamento.cliente.bairro
            cidade_uf = orcamento.cliente.cidade_uf
        else:
            nome = orcamento.nome_cliente
            telefone = orcamento.telefone_cliente
            logradouro = orcamento.logradouro_cliente
            numero_casa = orcamento.numero_casa_cliente
            bairro = orcamento.bairro_cliente
            cidade_uf = orcamento.cidade_uf_cliente

        endereco_completo = f"{logradouro}, {numero_casa} - {bairro} - {cidade_uf}"
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
            self.ln(4); self.set_font("Arial", "B", 12); self.set_text_color(0, 51, 102)
            self.cell(0, 10, "Serviços", ln=True, align="L"); self.draw_table(servicos)
        if materiais:
            self.ln(4); self.set_font("Arial", "B", 12); self.set_text_color(0, 51, 102)
            self.cell(0, 10, "Materiais", ln=True, align="L"); self.draw_table(materiais)

        self.ln(4); self.set_font("Arial", "B", 10); self.set_fill_color(255, 204, 0); self.set_text_color(0, 51, 102)
        label_w = sum(TABLE_COL_WIDTHS[:-1])
        self.set_x(10)
        self.cell(label_w, 8, "TOTAL GERAL:", 0, 0, 'R', fill=True)
        self.cell(TABLE_COL_WIDTHS[-1], 8, format_brl(orcamento.total_geral), 0, 1, "R", fill=True)
        self.set_y(230) 
        
        # --- Condição de Pagamento ---
        if orcamento.condicao_pagamento:
            self.set_x(10)
            self.set_font("Arial", "B", 9)
            self.set_text_color(0, 51, 102)
            self.cell(40, 5, "Condição de Pagamento:")
            self.set_font("Arial", "", 9)
            self.set_text_color(0, 0, 0)
            self.cell(0, 5, orcamento.condicao_pagamento, ln=True)

        # --- Prazo de Entrega ---
        if orcamento.prazo_entrega:
            self.set_x(10)
            self.set_font("Arial", "B", 9)
            self.set_text_color(0, 51, 102)
            self.cell(40, 5, "Prazo de Entrega:")
            self.set_font("Arial", "", 9)
            self.set_text_color(0, 0, 0)
            self.cell(0, 5, orcamento.prazo_entrega, ln=True)

        # --- Garantia ---
        if orcamento.garantia:
            self.set_x(10)
            self.set_font("Arial", "B", 9)
            self.set_text_color(0, 51, 102)
            self.cell(40, 5, "Garantia:")
            self.set_font("Arial", "", 9)
            self.set_text_color(0, 0, 0)
            self.cell(0, 5, orcamento.garantia, ln=True)

        if orcamento.observacoes:
            self.set_x(10)
            self.set_font("Arial", "B", 9)
            self.set_text_color(0, 51, 102)
            self.cell(40, 5, "Observações:")
            self.set_font("Arial", "I", 9) # 'I' para Itálico, para diferenciar
            self.set_text_color(0, 0, 0)
            # Usamos multi_cell para que o texto quebre a linha automaticamente
            self.multi_cell(0, 5, orcamento.observacoes, align='L')    


        self.set_y(-30); self.set_font("Arial", "B", 10); self.set_text_color(0, 51, 102)
        self.cell(0, 7, "VALIDADE DO DOCUMENTO:", ln=True)
        self.set_font("Arial", "B", 10); self.cell(0, 7, orcamento.data_validade, ln=True)

# --- FUNÇÃO GERADORA PRINCIPAL (A ÚNICA QUE O APP.PY CHAMA) ---
def gerar_pdf_joao(file_path, orcamento: Orcamento):
    # 1. Cria a instância da classe específica deste modelo, passando o orçamento
    pdf = JoaoPDF(format="A4", orcamento=orcamento)
    
    # 2. Adiciona a página (o header será chamado automaticamente)
    pdf.add_page()
    
    # 3. Desenha o conteúdo principal (a função agora não precisa de parâmetros)
    pdf.draw_content()
    
    # 4. Salva o resultado
    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    file_path.write(pdf_bytes)