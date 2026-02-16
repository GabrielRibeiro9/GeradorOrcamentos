import os, qrcode, tempfile, json, re, html
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

def clean_text(text):
    if not text: return ""
    # Retorna o texto puro, sem tentar converter para latin-1
    return str(text)

class CacadorPDF(FPDF):
    def __init__(self, *args, orcamento: Orcamento, **kwargs):
        super().__init__(*args, **kwargs)
        self.orcamento = orcamento
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        if os.path.exists(FULL_PAGE_BACKGROUND_IMAGE):
            self.image(FULL_PAGE_BACKGROUND_IMAGE, 0, 0, self.w, self.h)
        if os.path.exists(LOGO_PATH):
            self.image(LOGO_PATH, x=0, y=-4, w=70) # Logo subida para -4
        
        bar_y = 62 
        self.set_fill_color(0, 0, 0)
        self.set_text_color(255, 255, 255)
        self.set_font("Arial", "B", 9)

        # Monta o título completo (Ex: DATA | RECIBO DE SERVIÇO #0037)
        titulo = self.orcamento.status.upper() if self.orcamento.status else "ORÇAMENTO"
        header_text = f"DATA: {self.orcamento.data_emissao}    |    {titulo} #{self.orcamento.numero}"
        
        # AJUSTE: Calcula largura baseada no texto para não cortar
        bar_width = self.get_string_width(clean_text(header_text)) + 20

        self.set_xy(0, bar_y) 
        self.cell(bar_width, 8, "", 0, 0, 'L', fill=True) # Fundo preto
        self.set_xy(5, bar_y) 
        self.cell(bar_width, 8, clean_text(header_text), 0, 1, 'L') # Texto
        self.set_text_color(0, 0, 0)

    def footer(self):
        # Vai para 1.5 cm do final da página
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128) # Cor cinza
        # Usa page_no() para o número atual e o alias '{nb}' para o total
        self.cell(0, 10, f"Página {self.page_no()}/{{nb}}", 0, 0, 'C')

        # 2. Marca d'água (Canto Direito)
        logo_app = os.path.join(MODEL_DIR, '..', 'static', 'logo_full.png') # Caminho da sua logo
        if os.path.exists(logo_app):
            self.set_text_color(180, 180, 180)
            self.set_font("Arial", "B", 6)
            self.set_xy(-35, -18) 
            self.cell(30, 3, "Gerado por:", 0, 1, 'C')
            self.image(logo_app, x=self.w - 33, y=self.h - 15, w=26)
            self.set_xy(-35, -7)
            self.cell(30, 3, "www.geraorcamentos.com.br", 0, 0, 'C')

# FIM DA CLASSE MyPDF
# A função abaixo começa SEM INDENTAÇÃO

def gerar_pdf_cacador(file_path, orcamento: Orcamento):

    def draw_term_line(label, value):
        if not value or value == "[]": return
        # Fixa o bloco na direita conforme Imagem 1
        bx_largura = 95
        bx_x = pdf.w - pdf.r_margin - bx_largura
        pdf.set_x(bx_x)
        pdf.set_font("Arial", "B", 8)
        pdf.cell(pdf.get_string_width(f"{label}: "), 4, f"{label}: ")
        pdf.set_font("Arial", "", 8)
        # O 'R' garante o alinhamento à direita do texto
        pdf.multi_cell(bx_largura - pdf.get_string_width(label), 4, clean_text(str(value)), 0, 'R')

    if orcamento.cliente:
        nome = orcamento.cliente.nome
        telefone = orcamento.cliente.telefone
        logradouro = orcamento.cliente.logradouro
        numero_casa = orcamento.cliente.numero_casa
        complemento = orcamento.cliente.complemento
        bairro = orcamento.cliente.bairro
    else: # Fallback para clientes não salvos no formulário
        nome = orcamento.nome_cliente
        telefone = orcamento.telefone_cliente
        logradouro = orcamento.logradouro_cliente
        numero_casa = orcamento.numero_casa_cliente
        complemento = orcamento.complemento_cliente
        bairro = orcamento.bairro_cliente

    pdf = CacadorPDF(format='A4', orcamento=orcamento)
    pdf.add_font("DejaVu", "", "fonts/DejaVuSans.ttf", uni=True)
    pdf.add_font("DejaVu", "B", "fonts/DejaVuSans-Bold.ttf", uni=True)
    pdf.add_font("DejaVu", "I", "fonts/DejaVuSans-Oblique.ttf", uni=True)
    pdf.add_font("DejaVu", "BI", "fonts/DejaVuSans-BoldOblique.ttf", uni=True)
    pdf.alias_nb_pages()
    pdf.add_page()

    # Bloco 2: Montagem das Variáveis para o PDF
    endereco_base = f"{logradouro}, {numero_casa}"
    if complemento and complemento.strip():
        endereco_completo = f"{endereco_base} - {complemento} - {bairro}"
    else:
        endereco_completo = f"{endereco_base} - {bairro}"

    descricao_servico = orcamento.descricao_servico

    # GARANTE que o total_geral seja sempre um número para evitar erros
    try:
        total_geral = float(orcamento.total_geral)
    except (ValueError, TypeError):
        total_geral = 0.0

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
        pdf.set_font("DejaVu", "", 9)
        pdf.set_text_color(0, 0, 0)
        start_y = pdf.get_y()

        # --- LÓGICA DE TÓPICOS CORRIGIDA ---
        nome_item = str(it.get('nome', ''))
        topicos = it.get("topicos", [])

        if not topicos:
            descricao_completa = nome_item
        else:
            # Usamos o caractere Unicode real da bolinha (\u2022)
            linhas_da_lista = [f" \u2022 {nome_item}"]
            for topico in topicos:
                linhas_da_lista.append(f" \u2022 {str(topico)}")
            descricao_completa = "\n".join(linhas_da_lista)

        qtd_item = it.get('quantidade', 0)
        valor_item = it.get('valor', 0.0)
        total_linha = qtd_item * valor_item

        # Calcula a altura da linha usando a descricao_completa
        lines = pdf.multi_cell(TABLE_COL_WIDTHS[1], 4, descricao_completa, split_only=True)
        text_height = len(lines) * 4
        row_height = max(7, text_height + 3)
        # --- FIM DA LÓGICA ---

        if pdf.get_y() + row_height > pdf.page_break_trigger:
            pdf.add_page()
            draw_header()
            start_y = pdf.get_y()

        # Desenha a célula do número do item
        pdf.set_y(start_y)
        pdf.set_x(10)
        pdf.cell(TABLE_COL_WIDTHS[0], row_height, str(n), border=1, align='C', fill=True)
        
        x_after_item = pdf.get_x()
        
        # Desenha o fundo e a borda da célula
        pdf.rect(x=x_after_item, y=start_y, w=TABLE_COL_WIDTHS[1], h=row_height, style='DF')
        
        # Posiciona o cursor e desenha o texto completo
        y_text_pos = start_y + (row_height - text_height) / 2
        pdf.set_xy(x_after_item + 1, y_text_pos)
        pdf.multi_cell(TABLE_COL_WIDTHS[1] - 2, 4, descricao_completa, border=0, align='L')
        
        pdf.set_y(start_y)
        pdf.set_x(x_after_item + TABLE_COL_WIDTHS[1])
        
        q_val = float(it.get('quantidade', 1))
        u_med = it.get('unidade', 'un').lower().replace('m2', 'm²').replace('m3', 'm³')
        txt_q = f"{int(q_val) if q_val.is_integer() else q_val}{u_med}"
        
        pdf.cell(TABLE_COL_WIDTHS[2], row_height, clean_text(txt_q), border=1, align='C', fill=True)
        pdf.cell(TABLE_COL_WIDTHS[3], row_height, format_brl_cacador(valor_item), border=1, align="R", fill=True)
        pdf.cell(TABLE_COL_WIDTHS[4], row_height, format_brl_cacador(total_linha), border=1, align="R", fill=True, ln=1)

    if servicos:
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Serviços", ln=True, align="L")
        draw_header()
        for i, it in enumerate(servicos, start=1):
            draw_row(i, it) 

    if materiais:
        # --- LÓGICA DE VERIFICAÇÃO DE ESPAÇO ---
        # 10 (título) + 8 (cabeçalho da tabela) + 7 (altura mínima da linha) = 25
        espaco_necessario = 25 
        if pdf.get_y() + espaco_necessario > pdf.page_break_trigger:
            pdf.add_page()
        # --- FIM DA VERIFICAÇÃO ---

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

    txt_pagamento = orcamento.condicao_pagamento or ""
    
    # Se o texto for um JSON do novo app (começa com [[ ), ele transforma em texto bonito
    if txt_pagamento.startswith("[["):
        try:
            grupos = json.loads(txt_pagamento)
            # Transforma [[{desc:Sinal, valor:100}]] em "Sinal: R$ 100,00"
            txt_pagamento = " / ".join([" + ".join([f"{p['descricao']}: {format_brl_cacador(p['valor'])}" for p in g]) for g in grupos])
        except: 
            pass

    def draw_term_line(label, value):
        """
        Função para desenhar uma linha de termo com rótulo e valor,
        com quebra de linha do valor recuada para a posição do rótulo.
        """
        if not value or value == "[]": 
            return
         

        pdf.set_x(start_x)
        pdf.set_font("Arial", "B", 9)
        label_with_space = f"{label}: " # Adiciona os dois pontos e o espaço
        pdf.cell(pdf.get_string_width(label_with_space), 5, label_with_space, 0, 0, 'L')
        
        # Lógica de quebra de linha que você já tem para as observações
        value_x_start = pdf.get_x()
        first_line_width = pdf.w - pdf.r_margin - value_x_start
        subsequent_lines_width = pdf.w - pdf.r_margin - start_x
        text = str(value).replace("\n", " ") # Garante que o valor é uma string
        
        pdf.set_font("Arial", "", 9)
        lines = pdf.multi_cell(first_line_width, 5, text, split_only=True)
        
        if lines:
            current_y = pdf.get_y()
            pdf.set_xy(value_x_start, current_y)
            pdf.cell(first_line_width, 5, lines[0], 0, 1, 'L')
            
            remaining_text = " ".join(lines[1:])
            if remaining_text:
                pdf.set_x(start_x)
                pdf.multi_cell(subsequent_lines_width, 5, remaining_text, 0, 'L')
        else:
             pdf.ln() # Se não tiver linhas (valor vazio), só pula a linha


    condicao_pagamento_raw = orcamento.condicao_pagamento or ""
    
    # 1. Limpeza de HTML repetitivo
    if condicao_pagamento_raw:
        while "&" in condicao_pagamento_raw:
            old_val = condicao_pagamento_raw
            condicao_pagamento_raw = html.unescape(condicao_pagamento_raw)
            if old_val == condicao_pagamento_raw:
                break

    condicao_formatada = ""

    # 2. Processa se for o novo formato (JSON)
    if condicao_pagamento_raw.strip().startswith('[['):
        try:
            grupos = json.loads(condicao_pagamento_raw)
            if isinstance(grupos, list):
                opcoes_formatadas = []
                for i, grupo in enumerate(grupos):
                    partes_grupo = []
                    items_do_grupo = grupo if isinstance(grupo, list) else [grupo]
                    for p in items_do_grupo:
                        desc = p.get('descricao', 'Parcela')
                        valor = float(p.get('valor', 0))
                        partes_grupo.append(f"{desc}: {format_brl_cacador(valor)}")
                    texto_final = " + ".join(partes_grupo)
                    prefixo = f"Opção {i+1}: " if len(grupos) > 1 else ""
                    opcoes_formatadas.append(prefixo + texto_final)
                condicao_formatada = "\n".join(opcoes_formatadas)
        except:
            condicao_formatada = re.sub(r'[\[\]{}"\']', '', condicao_pagamento_raw)
    else:
        condicao_formatada = condicao_pagamento_raw

    if not condicao_formatada or condicao_formatada == "[]":
        condicao_formatada = "A combinar"

    # --- DESENHO DOS TERMOS ---
    draw_term_line("Pagamento", condicao_formatada)
    draw_term_line("Prazo", orcamento.prazo_entrega)
    draw_term_line("Garantia", orcamento.garantia)
    draw_term_line("Observações", orcamento.observacoes)

    pdf.ln(1) # Espaçamento final geral


    if orcamento.status and "recibo de serviço prestado" in orcamento.status.lower():      

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

        REQUIRED_PIX_HEIGHT = 75 

        if pdf.get_y() + REQUIRED_PIX_HEIGHT > pdf.page_break_trigger:
            pdf.add_page()    

        # Adiciona ao PDF (em uma nova página, ou abaixo do total)
        pdf.ln(5)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(0, 8, "Pague por Pix usando o QR Code:", ln=1, align="C")

        # Coordenadas (ajuste conforme layout)
        x_qr = (pdf.w - 40) / 2
        y_pos_before_image = pdf.get_y()
        pdf.image(tmp_qr_path, x=x_qr, y=y_pos_before_image, w=40, h=40)

        os.unlink(tmp_qr_path)

        pdf.set_y(y_pos_before_image + 40 + 5)

        pdf.set_font("Arial", "", 9)
        pdf.multi_cell(0, 6, f"Chave Pix Copia e Cola:\n{payload_pix}", align="C")

    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    file_path.write(pdf_bytes)
