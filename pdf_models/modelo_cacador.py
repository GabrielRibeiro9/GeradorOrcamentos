import os, qrcode, tempfile
from fpdf import FPDF
from models import Orcamento
from io import BytesIO
from pixqrcode import PixQrCode



# --- Constantes de layout que sua classe usa ---
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(MODEL_DIR, '..', 'static', 'cacador')
FULL_PAGE_BACKGROUND_IMAGE = os.path.join(STATIC_DIR, 'fundo_fermec.png')
LOGO_PATH = os.path.join(STATIC_DIR, 'logo_fermec.png')
FIXED_RECT_HEIGHT = 10
PADDING_RECT_VERTICAL = 1
LINE_HEIGHT = 5
TABLE_COL_WIDTHS = [20, 70, 20, 40, 40]
TABLE_TOTAL_WIDTH = sum(TABLE_COL_WIDTHS)

def format_brl_cacador(value): # Renomeado para evitar conflitos se você importar ambos no mesmo lugar
    if not isinstance(value, (int, float)):
        return "R$ 0,00"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

class CacadorPDF(FPDF):
    def __init__(self, *args, orcamento: Orcamento, **kwargs):
        super().__init__(*args, **kwargs)
        self.orcamento = orcamento
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        if os.path.exists(FULL_PAGE_BACKGROUND_IMAGE):
            self.image(FULL_PAGE_BACKGROUND_IMAGE, 0, 0, self.w, self.h)
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=0, y=-3, w=70)
        
        bar_y = 62 
        self.set_xy(0, bar_y) 
        self.set_fill_color(0, 0, 0)
        self.set_text_color(255, 255, 255)
        self.set_font("Arial", "B", 9)
        # Usa self.orcamento diretamente
        titulo_documento = self.orcamento.status.capitalize() if self.orcamento.status else "Orçamento"
        header_text = f"Data: {self.orcamento.data_emissao}    |    {titulo_documento} #{self.orcamento.numero}"
        bar_width = 80
        self.cell(bar_width, 8, "", 0, 1, 'L', fill=True) 
        self.set_xy(5, bar_y) 
        self.cell(0, 8, header_text, 0, 1, 'L')
        self.set_text_color(0, 0, 0)

    def footer(self):
        pass

# FIM DA CLASSE MyPDF
# A função abaixo começa SEM INDENTAÇÃO

def gerar_pdf_cacador(file_path, orcamento: Orcamento):

    if orcamento.cliente:
        nome = orcamento.cliente.nome
        telefone = orcamento.cliente.telefone
        # ... outros campos
    else:
        nome = orcamento.nome_cliente
        telefone = orcamento.telefone_cliente

    pdf = CacadorPDF(format='A4', orcamento=orcamento)
    pdf.add_page()

    # --- Extrai dados do objeto orcamento ---
    nome = orcamento.cliente.nome
    endereco_base = f"{orcamento.logradouro_cliente}, {orcamento.numero_casa_cliente}"

    # Adiciona o complemento APENAS se ele existir e não estiver vazio
    if orcamento.complemento_cliente and orcamento.complemento_cliente.strip():
        endereco_completo = f"{endereco_base} - {orcamento.complemento_cliente} - {orcamento.bairro_cliente}"
    else:
        endereco_completo = f"{endereco_base} - {orcamento.bairro_cliente}"

    telefone = orcamento.cliente.telefone
    descricao_servico = orcamento.descricao_servico
    servicos = [item for item in orcamento.itens if item.get("tipo") == "servico"]
    total_geral = orcamento.total_geral
    data_validade = orcamento.data_validade
    servicos = [item for item in orcamento.itens if item.get("tipo") == "servico"]
    materiais = [item for item in orcamento.itens if item.get("tipo") == "material"]

    # --- Desenha retângulos com dados do cliente ---
    campos = [("CLIENTE: ", nome), ("ENDEREÇO: ", endereco_completo), ("TELEFONE: ", telefone), ("DESCRIÇÃO SERVIÇO: ", descricao_servico)]
    start_x = 10
    current_y = 75 # Posição inicial
    for label, value in campos:
        is_desc = label.startswith("DESCRIÇÃO")
        
        # Define a fonte e calcula as larguras
        pdf.set_font("Arial", "B", 10)
        label_w = pdf.get_string_width(label)
        val_w = TABLE_TOTAL_WIDTH - label_w - 2 * PADDING_RECT_VERTICAL

        # LÓGICA DE ALTURA DINÂMICA
        if not is_desc:
            rect_h = 7 # Altura fixa para campos normais
        else:
            pdf.set_font("Arial", "", 10)
            lines = pdf.multi_cell(w=val_w, h=4, txt=str(value), split_only=True)
            text_height = len(lines) * 4 # 4 é a altura da linha de texto
            rect_h = max(7, text_height + 3) # Altura mínima de 7, com padding

        # Desenha o retângulo de fundo
        pdf.set_fill_color(240, 240, 240)
        pdf.rect(start_x, current_y, TABLE_TOTAL_WIDTH, rect_h, 'F')

        # Escreve o rótulo
        pdf.set_xy(start_x + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(label_w, 4, label, ln=0)

        # Escreve o valor
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", "", 10)
        pdf.set_xy(start_x + label_w + PADDING_RECT_VERTICAL, current_y + PADDING_RECT_VERTICAL)
        pdf.multi_cell(val_w, 4, txt=str(value))

        # Atualiza a posição Y para o próximo bloco
        current_y += rect_h + 2

    # Define a posição Y para o que vem depois
    pdf.set_y(current_y)
    
    # --- Funções para desenhar a tabela ---
    def draw_header():
        headers = ["ITEM", "DESCRIÇÃO", "QUANT.", "UNITÁRIO", "TOTAL"]
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(0, 0, 0)
        pdf.set_text_color(255, 255, 255)
        pdf.set_x(10)
        for w, title in zip(TABLE_COL_WIDTHS, headers):
            pdf.cell(w, 8, title, 1, align='C', fill=True)
        pdf.ln()

    def draw_row(n, it):
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(0, 0, 0)
        start_y = pdf.get_y()

        # Pega os valores com segurança
        nome_item = it.get('nome', '')
        qtd_item = it.get('quantidade', 0)
        valor_item = it.get('valor', 0.0)

        # CALCULA O TOTAL DA LINHA AQUI
        total_linha = qtd_item * valor_item

        # Calcula a altura da linha dinamicamente
        lines = pdf.multi_cell(TABLE_COL_WIDTHS[1], 4, nome_item, split_only=True)
        text_height = len(lines) * 4
        row_height = max(7, text_height + 3)

        if pdf.get_y() + row_height > pdf.page_break_trigger:
            pdf.add_page()
            draw_header()
            start_y = pdf.get_y()

        # Desenha as células com os valores corretos
        pdf.set_y(start_y)
        pdf.set_x(10)
        pdf.cell(TABLE_COL_WIDTHS[0], row_height, str(n), border=1, align='C', fill=True)
        
        x_after_item = pdf.get_x()
        y_text_pos = start_y + (row_height - text_height) / 2
        pdf.rect(x=x_after_item, y=start_y, w=TABLE_COL_WIDTHS[1], h=row_height, style='DF')
        pdf.set_xy(x_after_item, y_text_pos)
        pdf.multi_cell(TABLE_COL_WIDTHS[1], 4, nome_item, border=0, align='L')
        
        pdf.set_y(start_y)
        pdf.set_x(x_after_item + TABLE_COL_WIDTHS[1])
        
        pdf.cell(TABLE_COL_WIDTHS[2], row_height, str(qtd_item), border=1, align='C', fill=True)
        pdf.cell(TABLE_COL_WIDTHS[3], row_height, format_brl_cacador(valor_item), border=1, align="R", fill=True)
        
        # USA O TOTAL DA LINHA CALCULADO
        pdf.cell(TABLE_COL_WIDTHS[4], row_height, format_brl_cacador(total_linha), border=1, align="R", fill=True, ln=1)

    if servicos:
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 0, 0) # Cor do título da seção
        pdf.cell(0, 10, "Serviços", ln=True, align="L")
        draw_header()
        for i, it in enumerate(servicos, start=1):
            draw_row(i, it) 

    if materiais:
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Materiais", ln=True, align="L")
        draw_header()
        for i, it in enumerate(materiais, start=1):
            draw_row(i, it)           

    # --- Bloco final ---
    pdf.ln(5)
    total_formatado = f"R$ {total_geral:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    total_text = f"TOTAL: {total_formatado}"
    pdf.set_font("Arial", "B", 12)
    total_width = pdf.get_string_width(total_text) + 12
    start_x = pdf.w - pdf.r_margin - total_width
    pdf.set_xy(start_x, pdf.get_y())
    pdf.set_fill_color(0, 0, 0)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(total_width, 8, total_text, 0, 1, 'C', fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)
    line_width = 50
    line_x = start_x + (total_width - line_width) / 2
    pdf.set_draw_color(0, 0, 0)
    pdf.set_line_width(0.5)
    pdf.line(x1=line_x, y1=pdf.get_y(), x2=line_x + line_width, y2=pdf.get_y())
    pdf.ln(5)
    pdf.set_font("Arial", "B", 10)
    pdf.set_x(start_x)
    pdf.cell(total_width, 7, "TERMOS E CONDIÇÕES", 0, 1, 'C')
    pdf.set_font("Arial", "", 9)
    pdf.set_x(start_x)
    pdf.cell(total_width, 5, f"Orçamento válido até {data_validade}", 0, 1, 'C')

    pdf.ln(2)

    if orcamento.condicao_pagamento:
        pdf.set_x(start_x)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(total_width, 5, "Pagamento:", 0, 1, 'C')
        pdf.set_font("Arial", "", 9)
        pdf.set_x(start_x)
        pdf.multi_cell(total_width, 5, orcamento.condicao_pagamento, 0, 'C')
        pdf.ln(1)

    # --- Prazo de Entrega ---
    if orcamento.prazo_entrega:
        pdf.set_x(start_x)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(total_width, 5, "Prazo:", 0, 1, 'C')
        pdf.set_font("Arial", "", 9)
        pdf.set_x(start_x)
        pdf.multi_cell(total_width, 5, orcamento.prazo_entrega, 0, 'C')
        pdf.ln(1)

    # --- Garantia ---
    if orcamento.garantia:
        pdf.set_x(start_x)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(total_width, 5, "Garantia:", 0, 1, 'C')
        pdf.set_font("Arial", "", 9)
        pdf.set_x(start_x)
        pdf.multi_cell(total_width, 5, orcamento.garantia, 0, 'C')
        pdf.ln(1)

    if orcamento.observacoes:
        pdf.set_x(start_x)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(total_width, 5, "Observações:", 0, 1, 'C')
        pdf.set_font("Arial", "I", 9) # Usando Itálico aqui também
        pdf.set_x(start_x)
        pdf.multi_cell(total_width, 5, orcamento.observacoes, 0, 'C')
        pdf.ln(1) 

    def montar_payload_pix(chave_pix, nome_recebedor, cidade_recebedor, valor, descricao=""):
        # Remove caracteres especiais e limita o tamanho dos campos
        nome_recebedor = ''.join(e for e in nome_recebedor if e.isalnum() or e.isspace())[:25]
        cidade_recebedor = ''.join(e for e in cidade_recebedor if e.isalnum() or e.isspace())[:15]
        
        # Formata o valor corretamente
        valor_formatado = f"{float(valor):.2f}"
        
        # Monta os campos (IDs do BR Code)
        payload_format = '000201'
        merchant_account_info = f"0014BR.GOV.BCB.PIX01{len(chave_pix):02}{chave_pix}"
        merchant_category_code = '52040000' # Código para "Ponto de Venda" (padrão)
        transaction_currency = '5303986' # 986 = Real Brasileiro
        transaction_amount = f'54{len(valor_formatado):02}{valor_formatado}'
        country_code = '5802BR'
        merchant_name = f'59{len(nome_recebedor):02}{nome_recebedor}'
        merchant_city = f'60{len(cidade_recebedor):02}{cidade_recebedor}'
        additional_data = f'62{len(descricao)+4:02}05{len(descricao):02}{descricao}'
        
        payload = f"{payload_format}26{len(merchant_account_info):02}{merchant_account_info}{merchant_category_code}{transaction_currency}{transaction_amount}{country_code}{merchant_name}{merchant_city}{additional_data}6304"

        # Calcula o CRC16 (código de verificação final)
        import crcmod.predefined
        crc16 = crcmod.predefined.Crc('crc-ccitt-false')
        crc16.update(payload.encode('utf-8'))
        crc_hex = f'{crc16.crcValue:04X}'

        return f"{payload}{crc_hex}"

    chave_pix = "57373871000178"
    nome_recebedor = "WELLINGTON FERNANDO DE LIMA"
    cidade_recebedor = "ARARAS"
    descricao = f"***" # Padrão para PIX estático
    valor_pix = float(orcamento.total_geral)

    payload_pix = montar_payload_pix(
        chave_pix=chave_pix,
        nome_recebedor=nome_recebedor,
        cidade_recebedor=cidade_recebedor,
        valor=valor_pix,
        descricao=descricao
    )


    # Gera a imagem do QR Code
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(payload_pix)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_qr_file:
        img.save(tmp_qr_file, format="PNG")
        tmp_qr_path = tmp_qr_file.name

    # Adiciona ao PDF (em uma nova página, ou abaixo do total)
    pdf.ln(5)
    pdf.set_font("Arial", "B", 11)
    pdf.cell(0, 8, "Pague por Pix usando o QR Code:", ln=1, align="C")

    # Coordenadas (ajuste conforme layout)
    x_qr = (pdf.w - 40) / 2
    y_qr = pdf.get_y()
    pdf.image(tmp_qr_path, x=x_qr, y=y_qr, w=40, h=40)

    os.unlink(tmp_qr_path)

    pdf.ln(45)
    pdf.set_font("Arial", "", 9)
    pdf.multi_cell(0, 6, f"Chave Pix Copia e Cola:\n{payload_pix}", align="C")

    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    file_path.write(pdf_bytes)