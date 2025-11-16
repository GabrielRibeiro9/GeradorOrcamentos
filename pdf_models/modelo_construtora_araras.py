import os, qrcode, tempfile, json, re
from fpdf import FPDF
from models import Orcamento
from io import BytesIO
from pixqrcode import PixQrCode



# --- Constantes de layout que sua classe usa ---
MODEL_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(MODEL_DIR, '..', 'static', 'construtora_araras')
FULL_PAGE_BACKGROUND_IMAGE = os.path.join(STATIC_DIR, 'fundo_construtora.png')
LOGO_PATH = os.path.join(STATIC_DIR, 'logo_construtora.png')
FIXED_RECT_HEIGHT = 10
PADDING_RECT_VERTICAL = 1
LINE_HEIGHT = 5
TABLE_COL_WIDTHS = [20, 70, 20, 40, 40]
TABLE_TOTAL_WIDTH = sum(TABLE_COL_WIDTHS)
COR_AZUL = (44, 54, 133)
COR_LINHA_TABELA = (204, 219, 232)
COR_LARANJA_CLARO = (254, 234, 215)
COR_LARANJA_VIVO = (243, 145, 43)

def format_brl_construtora_araras(value): # Renomeado para evitar conflitos se você importar ambos no mesmo lugar
    if not isinstance(value, (int, float)):
        return "R$ 0,00"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

class Construtora_ArarasPDF(FPDF):
    def __init__(self, *args, orcamento: Orcamento, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_font("DejaVu", "", "fonts/DejaVuSans.ttf", uni=True)
        self.add_font("DejaVu", "B", "fonts/DejaVuSans-Bold.ttf", uni=True)
        self.add_font("DejaVu", "I", "fonts/DejaVuSans-Oblique.ttf", uni=True)
        self.add_font("DejaVu", "BI", "fonts/DejaVuSans-BoldOblique.ttf", uni=True)
        self.orcamento = orcamento
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        if os.path.exists(FULL_PAGE_BACKGROUND_IMAGE):
            self.image(FULL_PAGE_BACKGROUND_IMAGE, 0, 0, self.w, self.h)
        #if os.path.exists(LOGO_PATH):
            #self.image(LOGO_PATH, x=0, y=-3, w=70)
        
        title_y = 55 # Ajuste este valor se precisar de mais/menos espaço do topo
        self.set_y(title_y)

        # 1. Escreve "ORÇAMENTO" à esquerda
        self.set_font("Arial", "B", 26) # Fonte grande e em negrito
        self.set_text_color(*COR_AZUL)  # Usa a cor azul que definimos
        titulo_documento = self.orcamento.status.upper() if self.orcamento.status else "ORÇAMENTO"
        self.cell(100, 10, f"{titulo_documento} {self.orcamento.numero}", 0, 0, 'L') # Alinhado à esquerda ('L')

        # 2. Escreve "DATA:" e a data à direita, na mesma linha
        self.set_font("Arial", "B", 11)
    
        # Monta o texto completo para calcular a largura total
        texto_data_completo = f"DATA: {self.orcamento.data_emissao}"
        largura_texto_data = self.get_string_width(texto_data_completo)
        
        # Calcula a posição X inicial para que o texto termine alinhado
        posicao_final_retangulo = 10 + TABLE_TOTAL_WIDTH
        posicao_x_data = posicao_final_retangulo - largura_texto_data # Fonte menor e normal

        self.set_xy(posicao_x_data, title_y + 2)
        self.cell(largura_texto_data, 10, texto_data_completo, 0, 0, 'L')

        # Pula para a próxima linha e reseta as cores/fontes para o conteúdo
        if self.page_no() > 1:
            # Para a segunda página em diante, não adiciona espaço extra, só reseta a cor/fonte
            self.set_y(75) # Garante que o cursor comece no topo
        else:
            # Na primeira página, mantém um espaço para separar do título
            self.ln(20)

        self.set_text_color(0, 0, 0)
        self.set_font("Arial", "", 10)

    def footer(self):
        # Vai para 1.5 cm do final da página
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.set_text_color(128) # Cor cinza
        # Usa page_no() para o número atual e o alias '{nb}' para o total
        self.cell(0, 10, f"Página {self.page_no()}/{{nb}}", 0, 0, 'C')

# FIM DA CLASSE MyPDF
# A função abaixo começa SEM INDENTAÇÃO

def gerar_pdf_construtora_araras(file_path, orcamento: Orcamento):

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

    pdf = Construtora_ArarasPDF(format='A4', orcamento=orcamento)
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
    tem_ncm = any(item.get('ncm') for item in materiais)

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

        # Desenha o retângulo de fundo (AQUI ESTÁ A MUDANÇA)
        pdf.set_fill_color(*COR_LARANJA_CLARO) # <--- MUDAMOS A COR AQUI
        pdf.rect(start_x, current_y, TABLE_TOTAL_WIDTH, rect_h, 'F')

        # Escreve o rótulo
        pdf.set_xy(start_x + PADDING_RECT_VERTICAL, current_y + 1.5)
        pdf.set_font("Arial", "B", 10)
        pdf.set_text_color(*COR_AZUL)
        pdf.cell(label_w, 4, label)

        # Posição X onde o valor começa
        value_x_start = pdf.get_x()

        # Escreve o valor com quebra de linha inteligente
        pdf.set_font("Arial", "", 10)
        pdf.set_text_color(0, 0, 0)

        # Largura disponível para a primeira linha e as seguintes
        first_line_width = TABLE_TOTAL_WIDTH - label_w - (2 * PADDING_RECT_VERTICAL)
        subsequent_lines_width = TABLE_TOTAL_WIDTH - (2 * PADDING_RECT_VERTICAL)
        
        # Pega as linhas sem desenhá-las
        lines = pdf.multi_cell(first_line_width, 4, str(value), split_only=True)

        if lines:
            # Desenha a primeira linha
            pdf.set_xy(value_x_start, current_y + 1.5)
            pdf.cell(first_line_width, 4, lines[0], 0, 1, 'L')

            # Junta o resto do texto
            remaining_text = " ".join(lines[1:])
            
            if remaining_text:
                # Desenha o resto do texto alinhado à esquerda do retângulo
                pdf.set_x(start_x + PADDING_RECT_VERTICAL)
                pdf.multi_cell(subsequent_lines_width, 4, remaining_text, 0, 'L')

        # Atualiza a posição Y para o próximo bloco
        current_y += rect_h + 2

    # Define a posição Y para o que vem depois
    pdf.set_y(current_y)

    if tem_ncm:
        # Layout COM a coluna NCM
        headers_materiais = ["ITEM", "DESCRIÇÃO", "NCM", "QUANT.", "UNITÁRIO", "TOTAL"]
        # Reduzimos 'DESCRIÇÃO' para dar espaço a 'NCM'
        widths_materiais = [20, 45, 25, 20, 40, 40] 
    else:
        # Layout SEM a coluna NCM (o original)
        headers_materiais = ["ITEM", "DESCRIÇÃO", "QUANT.", "UNITÁRIO", "TOTAL"]
        widths_materiais = [20, 70, 20, 40, 40]
    
    # --- Funções para desenhar a tabela ---
    def draw_header(headers, col_widths):
        pdf.set_font("Arial", "B", 9)
        pdf.set_fill_color(*COR_AZUL)
        pdf.set_text_color(255, 255, 255)
        pdf.set_x(10)

        # Usamos as variáveis recebidas em vez das constantes globais
        for w, title in zip(col_widths, headers):
            pdf.cell(w, 8, title, 0, align='C', fill=True)
        pdf.ln()


    def draw_row(n, it, has_ncm_column, headers, col_widths):
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("DejaVu", "", 9) # Fonte já trocada aqui

        start_y = pdf.get_y()
        
        # --- LÓGICA DE TÓPICOS ---
        nome_item = str(it.get('nome', ''))
        topicos = it.get("topicos", [])

        if not topicos:
            descricao_completa = nome_item
        else:
            linhas_da_lista = [f"  •  {nome_item}"]
            for topico in topicos:
                linhas_da_lista.append(f"  •  {str(topico)}")
            descricao_completa = "\n".join(linhas_da_lista)

        qtd_item = it.get('quantidade', 0)
        valor_item = float(it.get('valor', 0.0))
        total_linha = qtd_item * valor_item
        ncm_valor = it.get('ncm') or ''

        # Calcula altura usando a descricao_completa
        lines = pdf.multi_cell(col_widths[1] - 3, 4, descricao_completa, split_only=True)
        text_height = len(lines) * 4
        row_height = max(7, text_height + 3)
        # --- FIM DA LÓGICA ---

        # Correção na quebra de página
        altura_cabecalho_tabela = 8
        if pdf.get_y() + row_height + altura_cabecalho_tabela > pdf.page_break_trigger:
            pdf.add_page()
            draw_header(headers, col_widths)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("DejaVu", "", 9)  
            start_y = pdf.get_y()

        pdf.set_y(start_y)
        pdf.set_x(10)

        # Célula do item
        pdf.cell(col_widths[0], row_height, str(n).zfill(2), 0, align='C')

        # --- Lógica de desenho da descrição ---
        x_after_item = pdf.get_x()
        y_text_pos = start_y + (row_height - text_height) / 2
        pdf.set_xy(x_after_item + 2, y_text_pos)
        pdf.multi_cell(col_widths[1] - 3, 4, descricao_completa, 0, align='L')
        # --- Fim ---
        
        pdf.set_y(start_y)
        pdf.set_x(x_after_item + col_widths[1])

        if has_ncm_column:
            pdf.cell(col_widths[2], row_height, ncm_valor, 0, align='C')
            pdf.cell(col_widths[3], row_height, str(qtd_item), 0, align='C')
            pdf.cell(col_widths[4], row_height, format_brl_construtora_araras(valor_item), 0, align='C')
            pdf.cell(col_widths[5], row_height, format_brl_construtora_araras(total_linha), 0, align='C')
        else:
            pdf.cell(col_widths[2], row_height, str(qtd_item), 0, align='C')
            pdf.cell(col_widths[3], row_height, format_brl_construtora_araras(valor_item), 0, align='C')
            pdf.cell(col_widths[4], row_height, format_brl_construtora_araras(total_linha), 0, align='C')

        y_line = start_y + row_height
        pdf.set_draw_color(*COR_LINHA_TABELA)
        pdf.set_line_width(0.2)
        pdf.line(10, y_line, 10 + sum(col_widths), y_line)
        pdf.set_y(y_line)

    if servicos:
        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Serviços", ln=True, align="L")
        
        headers_servicos = ["ITEM", "DESCRIÇÃO", "QUANT.", "UNITÁRIO", "TOTAL"]
        widths_servicos = [20, 70, 20, 40, 40]
        
        draw_header(headers_servicos, widths_servicos)
        for i, it in enumerate(servicos, start=1):
            # Passamos os headers corretos para a função
            draw_row(i, it, False, headers_servicos, widths_servicos)

    if materiais:
        # Espaço para: Título da Seção (10) + Cabeçalho da Tabela (8) + Altura Mínima de 1 linha (7)
        espaco_necessario_para_nova_secao = 10 + 8 + 7 
        if pdf.get_y() + espaco_necessario_para_nova_secao > pdf.page_break_trigger:
            pdf.add_page()

        pdf.ln(4)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Materiais", ln=True, align="L")
        
        draw_header(headers_materiais, widths_materiais)
        for i, it in enumerate(materiais, start=1):
            # Passamos os headers corretos para a função
            draw_row(i, it, tem_ncm, headers_materiais, widths_materiais)           

    # --- Bloco final ---
    pdf.ln(5)
    total_formatado = format_brl_construtora_araras(total_geral)
    total_text = f"TOTAL: {total_formatado}"
    pdf.set_font("Arial", "B", 12)
    total_width = pdf.get_string_width(total_text) + 12
    start_x = pdf.w - pdf.r_margin - total_width
    pdf.set_xy(start_x, pdf.get_y())

    # 1. Caixa do Total com fundo AZUL
    pdf.set_fill_color(*COR_AZUL)
    pdf.set_text_color(255, 255, 255) # Texto branco
    pdf.cell(total_width, 10, total_text, 0, 1, 'C', fill=True)

    # 2. Linha de destaque com a cor LARANJA VIVO
    pdf.set_xy(start_x, pdf.get_y())
    pdf.set_fill_color(*COR_LARANJA_VIVO)
    pdf.rect(start_x, pdf.get_y(), total_width, 1.5, 'F') # Desenha um retângulo fino

    pdf.ln(5)

    # 3. Título "TERMOS E CONDIÇÕES" em AZUL
    pdf.set_font("Arial", "B", 10)
    pdf.set_text_color(*COR_AZUL) # <--- MUDANÇA DE COR
    pdf.set_x(start_x)
    pdf.cell(total_width, 7, "TERMOS E CONDIÇÕES", 0, 1, 'C')

    # Resto do texto volta a ser preto
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", "", 9)
    pdf.set_x(start_x)
    pdf.cell(total_width, 5, f"Orçamento válido até {data_validade}", 0, 1, 'C')

    pdf.ln(2)

    def draw_term_line(label, value):
        """
        Função adaptada do modelo_cacador para desenhar uma linha de termo
        com quebra de linha do valor recuada corretamente.
        """
        if not value: # Não faz nada se não houver valor
            return

        # Posição X inicial dos rótulos (alinhado com o início do bloco de termos)
        initial_x_pos = start_x 

        # --- Desenha o Rótulo ---
        pdf.set_x(initial_x_pos)
        pdf.set_font("Arial", "B", 9)
        pdf.set_text_color(*COR_AZUL) # Usa a cor azul do seu modelo
        label_with_space = f"{label}: "
        pdf.cell(pdf.get_string_width(label_with_space), 5, label_with_space, 0, 0, 'L')
        
        # --- Lógica de Quebra de Linha ---
        # Salva a posição X onde o valor deve começar a ser escrito
        value_x_start = pdf.get_x()
        
        # Calcula a largura disponível para a PRIMEIRA linha do valor
        first_line_width = pdf.w - pdf.r_margin - value_x_start
        
        # Calcula a largura disponível para as linhas SUBSEQUENTES
        subsequent_lines_width = pdf.w - pdf.r_margin - initial_x_pos
        
        text = str(value).replace("\n", " ")
        
        pdf.set_font("Arial", "", 9)
        pdf.set_text_color(0, 0, 0) # Texto do valor em preto
        
        # Quebra o texto em linhas usando a largura da primeira linha como base
        lines = pdf.multi_cell(first_line_width, 5, text, split_only=True)
        
        if lines:
            # Salva a posição Y atual antes de começar a escrever
            current_y = pdf.get_y()
            
            # Posiciona o cursor e escreve a PRIMEIRA linha
            pdf.set_xy(value_x_start, current_y)
            pdf.cell(first_line_width, 5, lines[0], 0, 1, 'L')
            
            # Pega o texto restante para as próximas linhas
            remaining_text = " ".join(lines[1:])
            
            # Se houver texto restante, usa multi_cell para escrevê-lo com recuo
            if remaining_text:
                # Reposiciona o cursor X no início da linha (alinhado com o rótulo)
                pdf.set_x(initial_x_pos) 
                pdf.multi_cell(subsequent_lines_width, 5, remaining_text, 0, 'L')
        else:
            # Se não houver texto, apenas pula a linha para o próximo termo
            pdf.ln()

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
                            partes_grupo.append(f"{p.get('descricao', 'Parcela')}: {format_brl_construtora_araras(float(p.get('valor', 0)))}")
                        
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

    pdf_bytes = pdf.output(dest='S').encode('latin-1')
    file_path.write(pdf_bytes)