import os, qrcode, tempfile, json, re
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
        # Vai para 1.5 cm do final da página
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128) # Cor cinza
        # Usa page_no() para o número atual e o alias '{nb}' para o total
        self.cell(0, 10, f"Página {self.page_no()}/{{nb}}", 0, 0, 'C')

# FIM DA CLASSE MyPDF
# A função abaixo começa SEM INDENTAÇÃO

def gerar_pdf_cacador(file_path, orcamento: Orcamento):

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

    def draw_term_line(label, value):
        """
        Função para desenhar uma linha de termo com rótulo e valor,
        com quebra de linha do valor recuada para a posição do rótulo.
        """
        if not value: # Não faz nada se não houver valor
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


    condicao_pagamento_str = orcamento.condicao_pagamento
    condicao_formatada = ""  # Começamos com uma string vazia

    if condicao_pagamento_str and condicao_pagamento_str.strip().startswith('[['):
        # NOVO CENÁRIO: É UM JSON de Grupos de Pagamento
        try:
            grupos = json.loads(condicao_pagamento_str)
            if isinstance(grupos, list) and all(isinstance(g, list) for g in grupos):
                opcoes_formatadas = []
                for i, grupo in enumerate(grupos):
                        partes_grupo = []
                        desconto_total_grupo = sum(float(p.get('desconto', 0)) for p in grupo)

                        for p in grupo:
                            partes_grupo.append(f"{p.get('descricao', 'Parcela')}: {format_brl_cacador(float(p.get('valor', 0)))}")
                        
                        texto_grupo_formatado = " + ".join(partes_grupo)

                        # Se houve desconto NESTE grupo, adiciona a informação
                        if desconto_total_grupo > 0:
                            valor_bruto_grupo = sum(float(p.get('valor', 0)) + float(p.get('desconto', 0)) for p in grupo)
                            # Previne divisão por zero se o valor bruto for 0
                            if valor_bruto_grupo > 0:
                                percentual_desconto = (desconto_total_grupo / valor_bruto_grupo) * 100
                                desconto_str = f" ({percentual_desconto:g}% de desconto)"
                                texto_grupo_formatado += desconto_str

                        prefixo = f"Opção {i+1}: " if len(grupos) > 1 else ""
                        opcoes_formatadas.append(prefixo + texto_grupo_formatado)
                
                # Junta cada opção com uma quebra de linha para exibir no PDF
                condicao_formatada = "\n".join(opcoes_formatadas)
        except (json.JSONDecodeError, TypeError):
            # Se falhar o parse, apenas limpa
            condicao_formatada = re.sub(r'\s*R\$\s*[\d.,]+$', '', condicao_pagamento_str.strip())
    
    elif condicao_pagamento_str:
        # COMPATIBILIDADE: Se for um texto antigo, apenas limpa
        condicao_formatada = re.sub(r'\s*R\$\s*[\d.,]+$', '', condicao_pagamento_str.strip())
        
    # Garante que, se for '[]', não exiba nada
    if condicao_formatada == '[]':
        condicao_formatada = 'A combinar'

    # --- USO DA FUNÇÃO PARA TODOS OS CAMPOS ---
    draw_term_line("Pagamento", condicao_formatada)
    draw_term_line("Prazo", orcamento.prazo_entrega)
    draw_term_line("Garantia", orcamento.garantia)
    draw_term_line("Observações", orcamento.observacoes)

    pdf.ln(1) # Espaçamento final geral


    if orcamento.status == "Nota de Serviço":    

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