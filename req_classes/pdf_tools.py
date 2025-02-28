# pdf_tools.py
import os
import json
import base64
import tempfile
import logging
from pathlib import Path
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from PIL import Image
from io import BytesIO
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, Frame
from reportlab.lib.enums import TA_LEFT
from typing import List
import re
from req_classes.settingsClass import Settings

# Cria a instância de configurações e carrega o arquivo de configuração
settings = Settings()
config = settings.config

# Configuração do logging: os logs serão gravados em "pdf_tools.log" e também exibidos no console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("pdf_tools.log"),
        logging.StreamHandler()
    ]
)

# Mapeamento de cores para os estados (utilizado para pintar as células de acordo com o status)
STATUS_COLORS = {
    "Concluído": (0.90, 1.0, 0.90),      # verde claro
    "Parcial": (1.0, 1.0, 0.85),         # amarelo claro
    "Não Concluído": (1.0, 0.90, 0.90)    # vermelho claro
}

def save_temp_image(image_data):
    """
    Salva os dados binários de uma imagem em um arquivo temporário no formato PNG e retorna o caminho do arquivo.
    
    Parâmetros:
      - image_data: dados binários da imagem.
      
    Retorna:
      - Caminho do arquivo temporário criado.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
        # Abre a imagem a partir dos dados binários e a salva em formato PNG
        img = Image.open(BytesIO(image_data))
        img.save(temp_file, format='PNG')
        temp_file_path = temp_file.name
    logging.debug(f"Saved temporary image: {temp_file_path}")
    return temp_file_path

def draw_first_page(c, width, height, report_date, config):
    """
    Desenha a primeira página (capa) do PDF, contendo cabeçalho, informações do relatório e rodapé.
    
    Parâmetros:
      - c: objeto canvas do ReportLab.
      - width, height: dimensões da página.
      - report_date: data do relatório a ser exibida.
      - config: dicionário de configurações com textos para cabeçalho, título, rodapé, etc.
    """
    # Cabeçalho principal
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 30 * mm, config["header_1"])
    c.drawCentredString(width / 2, height - 40 * mm, config["header_2"])

    # Título do relatório
    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 60 * mm, config["title"])

    # Informações adicionais: data, número de referência e descrição
    c.setFont("Helvetica", 12)
    c.drawString(40 * mm, height - 80 * mm, f"{config['date_prefix']} {report_date}")
    c.drawString(40 * mm, height - 90 * mm, config["reference_number"])
    c.drawString(40 * mm, height - 110 * mm, config["description"])

    # Rodapé com endereço, código postal, telefones, fax e e-mail
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 20 * mm, config["address"])
    c.drawCentredString(width / 2, 15 * mm, f"{config['postal_code']} - {config['contact_phone']} - {config['contact_fax']}")
    c.drawCentredString(width / 2, 10 * mm, config["contact_email"])

def draw_header(c, width, height, text_objects):
    """
    Desenha o cabeçalho das páginas subsequentes do PDF.
    
    Parâmetros:
      - c: objeto canvas.
      - width, height: dimensões da página.
      - text_objects: dicionário contendo textos para as seções do cabeçalho (ex.: section1, section2, section3).
    """
    y_position = height - 15 * mm
    c.setFont("Helvetica", 12)
    c.drawCentredString(width / 2, y_position, text_objects['section1'])
    y_position -= 6 * mm
    c.setFont("Helvetica", 12)
    c.drawCentredString(width / 2, y_position, text_objects['section2'])
    y_position -= 8 * mm
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, y_position, text_objects['section3'])

def draw_footer(c, width, height, text_objects, current_page, total_pages):
    """
    Desenha o rodapé em cada página do PDF, incluindo uma linha separadora e numeração de páginas.
    
    Parâmetros:
      - c: objeto canvas.
      - width, height: dimensões da página.
      - text_objects: dicionário contendo linhas de rodapé.
      - current_page: número da página atual.
      - total_pages: número total de páginas.
    """
    margin = 40 * mm
    line_y = 20 * mm
    c.setLineWidth(1)
    c.setStrokeColorRGB(0, 0, 0)
    c.line(margin, line_y, width - margin, line_y)
    c.setFont("Helvetica", 8)
    y_position = 15 * mm
    for line in text_objects['footer_lines']:
        c.drawCentredString(width / 2, y_position, line)
        y_position -= 4 * mm
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, y_position - 0.5 * mm, f"Página {current_page} de {total_pages}")

def draw_signature_section(c, width, height, text_objects):
    """
    Desenha a página de assinatura (última página) do PDF.
    
    Parâmetros:
      - c: objeto canvas.
      - width, height: dimensões da página.
      - text_objects: dicionário com textos para os campos de assinatura e data.
    """
    left_x = width / 4
    right_x = (3 * width) / 4
    y_position = height / 4
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 40 * mm, 25 * mm, f"{text_objects['location_date']}")
    c.setFont("Helvetica", 10)
    c.drawCentredString(left_x, y_position + 20, text_objects.get("sign1"))
    c.drawCentredString(left_x, y_position + 10, text_objects.get("sign1_name"))
    c.drawCentredString(left_x, y_position, "Data: ........./........../...........")
    c.setFont("Helvetica", 10)
    c.drawCentredString(right_x, y_position + 20, text_objects.get("sign2"))
    c.drawCentredString(right_x, y_position + 10, text_objects.get("sign2_name"))
    c.drawCentredString(right_x, y_position, "Data: .........../.........../...........")

###############################################
# FUNÇÕES PARA A PÁGINA 2 (TABELAS DINÂMICAS)
###############################################


def compute_sigla_first_occurrence(entries: List[dict], table_pages: int) -> dict:
    """
    Calcula um dicionário que mapeia cada "sigla" para o número da página onde ela aparece
    pela primeira vez nos registros (entries). Considera que as páginas de registros começam
    após a capa e as páginas de tabelas. Cada página de entries contém 2 registros.
    
    Parâmetros:
      - entries: lista de dicionários com os dados de cada registro.
      - table_pages: número total de páginas já utilizadas para tabelas.
      
    Retorna:
      - Dicionário com cada sigla mapeada para o número da página onde ocorre a primeira vez.
    """
    offset = 1 + table_pages  # 1 para a capa + número de páginas de tabela
    sigla_to_page = {}
    for idx, entry in enumerate(entries):
        sigla = entry.get('sigla')
        page = offset + (idx // 2)
        if sigla and sigla not in sigla_to_page:
            sigla_to_page[sigla] = page
    return sigla_to_page


def draw_table(c, x, y, headers, data, col_widths, row_height, sigla_mapping=None):
    """
    Desenha uma tabela simples no canvas.
    
    Parâmetros:
      - c: objeto canvas.
      - x, y: posição inicial da tabela.
      - headers: lista de cabeçalhos da tabela.
      - data: lista de linhas (cada linha é uma lista de células).
      - col_widths: lista com a largura de cada coluna.
      - row_height: altura de cada linha.
      - sigla_mapping (opcional): se fornecido, a célula da coluna "Sigla" será transformada em link
        interno apontando para o destino "sigla_<valor>".
    """
    num_cols = len(headers)
    num_rows = len(data) + 1  # +1 para o cabeçalho
    table_width = sum(col_widths)
    table_height = num_rows * row_height

    # Desenha o fundo do cabeçalho (em cinza claro)
    c.saveState()
    c.setFillColorRGB(0.8, 0.8, 0.8)
    c.rect(x, y - row_height, table_width, row_height, fill=1, stroke=0)
    c.restoreState()
    
    # Desenha os cabeçalhos
    c.setFillColorRGB(0, 0, 0)
    col_x = x
    for i, header in enumerate(headers):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(col_x + 2 * mm, y - row_height + 2 * mm, header)
        col_x += col_widths[i]
    
    # Desenha os dados das linhas
    for row_index, row in enumerate(data):
        current_y = y - (row_index + 2) * row_height
        col_x = x
        for col_index, cell in enumerate(row):
            # Se a coluna for "Estado", pinta o fundo de acordo com o status
            if headers[col_index] == "Estado":
                status = cell
                color = STATUS_COLORS.get(status, (1, 1, 1))
                c.saveState()
                c.setFillColorRGB(*color)
                c.rect(col_x, current_y, col_widths[col_index], row_height, fill=1, stroke=0)
                c.restoreState()
            c.setFont("Helvetica", 10)
            c.drawString(col_x + 2 * mm, current_y + 2 * mm, str(cell))
            # Se a coluna for "Sigla" e houver mapeamento, cria uma área clicável
            if headers[col_index] == "Sigla" and sigla_mapping is not None:
                link_rect = (col_x, current_y, col_x + col_widths[col_index], current_y + row_height)
                c.linkRect("", "sigla_" + str(cell), link_rect, relative=0, thickness=0)
            col_x += col_widths[col_index]
    
    # Desenha linhas horizontais e verticais para a tabela
    for i in range(num_rows + 1):
        c.line(x, y - i * row_height, x + table_width, y - i * row_height)
    col_x = x
    for width_i in col_widths:
        c.line(col_x, y, col_x, y - table_height)
        col_x += width_i
    c.line(x + table_width, y, x + table_width, y - table_height)

def draw_paginated_table(c, title, headers, data, col_widths, row_height, gap, available_width, sigla_mapping, text_objects, width, height, current_page, total_pages):
    """
    Desenha uma tabela paginada, dividindo os dados em blocos de até 30 linhas.
    
    Para cada bloco:
      - Se houver mais de 15 linhas, utiliza a função draw_split_table (dividindo em duas colunas);
      - Caso contrário, utiliza draw_table.
    Desenha o título com indicação de página e o rodapé.
    
    Retorna o número da próxima página.
    """
    import math
    pages_needed = math.ceil(len(data) / 30)
    margin = 40 * mm  # mesma margem utilizada no restante do PDF
    for p in range(pages_needed):
        c.setFont("Helvetica-Bold", 12)
        if pages_needed > 1:
            c.drawString(margin, height - 30 * mm, f"{title} - Página {p+1} de {pages_needed}")
        else:
            c.drawString(margin, height - 30 * mm, title)
        table_y = height - 30 * mm - 10 * mm
        page_data = data[p*30:(p+1)*30]
        if len(page_data) > 15:
            draw_split_table(c, margin, table_y, headers, page_data, col_widths, row_height, gap, available_width, sigla_mapping)
        else:
            draw_table(c, margin, table_y, headers, page_data, col_widths, row_height, sigla_mapping)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1
    return current_page

def draw_split_table(c, x, y, headers, data, col_widths, row_height, gap, available_width, sigla_mapping=None):
    """
    Desenha uma tabela dividida em duas colunas lado a lado, onde cada coluna comporta até 15 linhas.
    
    Se o número de linhas for menor ou igual a 15, chama draw_table normalmente.
    Caso contrário, divide os dados em:
       - left_data = data[:15]
       - right_data = data[15:30]
       
    Parâmetro:
      - available_width: largura total disponível para a tabela.
    """
    if len(data) <= 15:
        draw_table(c, x, y, headers, data, col_widths, row_height, sigla_mapping)
    else:
        left_data = data[:15]
        right_data = data[15:30]
        table_width = (available_width - gap) / 2
        W = sum(col_widths)
        scale = table_width / W
        scaled_widths = [w * scale for w in col_widths]
        draw_table(c, x, y, headers, left_data, scaled_widths, row_height, sigla_mapping)
        if right_data:
            right_x = x + table_width + gap
            draw_table(c, right_x, y, headers, right_data, scaled_widths, row_height, sigla_mapping)

###############################################
# FUNÇÃO QUE CRIA O PDF
###############################################

def draw_dynamic_table(
    c, x, y, headers, data, col_widths, header_style, cell_style,
    padding=2*mm, bottom_margin=25*mm,
    footer_drawer=None, page=1, total_pages=1, width=None, height=None, text_objects=None
):
    """
    Desenha uma tabela com células de altura dinâmica utilizando Paragraphs.
    Realiza a quebra de página quando o espaço disponível acabar e desenha linhas internas.
    
    Parâmetros:
      - c: objeto canvas.
      - x, y: posição inicial da tabela.
      - headers: cabeçalhos da tabela.
      - data: dados da tabela (lista de linhas).
      - col_widths: larguras das colunas.
      - header_style, cell_style: estilos de Paragraph para cabeçalho e células.
      - padding: espaçamento interno de cada célula.
      - bottom_margin: margem inferior reservada para rodapé.
      - footer_drawer: função para desenhar o rodapé.
      - page, total_pages: controle de numeração de páginas.
      - width, height, text_objects: dimensões da página e textos para o rodapé.
    
    Retorna:
      - Dicionário com a altura total desenhada e o último número de página utilizado.
    """

    from reportlab.platypus import Paragraph
    from reportlab.lib.enums import TA_LEFT, TA_CENTER
    from reportlab.lib.styles import ParagraphStyle

    table_width = sum(col_widths)
    num_cols = len(headers)

    # Definimos um mapeamento de alinhamentos para cada coluna
    # (ex.: centralizar "Quadra", "Sigla", "Canteiro"; alinhar à esquerda o resto)
    def get_alignment_for_column(header_text):
        if header_text in ["Quadra", "Sigla", "Canteiro"]:
            return TA_CENTER
        return TA_LEFT

    # -------------------------------------------------------------------------
    # FUNÇÃO AUXILIAR: DESENHAR O CABEÇALHO DA TABELA
    # -------------------------------------------------------------------------
    def draw_header(current_y):
        """Desenha o cabeçalho da tabela na página atual e retorna sua altura."""
        # Cria Paragraphs do cabeçalho
        header_cells = []
        header_heights = []
        for i, h in enumerate(headers):
            # Ajusta o alignment dinamicamente
            col_alignment = get_alignment_for_column(h)
            custom_header_style = ParagraphStyle(
                'CustomHeaderStyle',
                parent=header_style,
                alignment=col_alignment  # centraliza se for "Quadra", "Sigla", etc.
            )
            para = Paragraph(str(h), custom_header_style)
            w, h_para = para.wrap(col_widths[i] - 2 * padding, 1000)
            header_heights.append(h_para + 2 * padding)
            header_cells.append(para)

        header_height = max(header_heights)

        # Desenha o fundo do cabeçalho (cinza claro)
        c.saveState()
        c.setFillColorRGB(0.8, 0.8, 0.8)
        c.rect(x, current_y - header_height, table_width, header_height, fill=1, stroke=0)
        c.restoreState()

        # Desenha cada célula do cabeçalho
        curr_x = x
        for i, para in enumerate(header_cells):
            para.drawOn(c, curr_x + padding, current_y - header_height + padding)
            curr_x += col_widths[i]

        # Desenha as linhas verticais do cabeçalho
        row_top = current_y
        row_bottom = current_y - header_height
        line_x = x
        for col_i in range(num_cols + 1):
            c.line(line_x, row_top, line_x, row_bottom)
            if col_i < num_cols:
                line_x += col_widths[col_i]

        # Linha horizontal abaixo do cabeçalho
        c.line(x, row_bottom, x + table_width, row_bottom)

        return header_height

    # -------------------------------------------------------------------------
    # VARIÁVEIS DE CONTROLE PARA O DESENHO DA TABELA
    # -------------------------------------------------------------------------

    total_drawn_height = 0
    current_y = y
    header_height = draw_header(current_y)
    total_drawn_height += header_height
    current_y -= header_height

    # -------------------------------------------------------------------------
    # DESENHA AS LINHAS DE DADOS
    # -------------------------------------------------------------------------
    for row in data:
        # Cria Paragraphs e calcula altura
        cell_paragraphs = []
        cell_heights = []

        for col_i, cell_text in enumerate(row):
            col_alignment = get_alignment_for_column(headers[col_i])
            custom_cell_style = ParagraphStyle(
                'CustomCellStyle',
                parent=cell_style,
                alignment=col_alignment  # centraliza se for "Quadra", "Sigla", etc.
            )
            para = Paragraph(str(cell_text).replace('\n', '<br/>'), custom_cell_style)
            w, h = para.wrap(col_widths[col_i] - 2 * padding, 1000)
            cell_paragraphs.append(para)
            cell_heights.append(h + 2 * padding)

        row_height = max(cell_heights)

        # Se não houver espaço suficiente na página, realiza a quebra de página
        if current_y - row_height < bottom_margin:
            # Fecha a borda inferior da tabela na página atual
            c.rect(x, current_y, table_width, y - current_y, stroke=1, fill=0)

            # Se houver função de rodapé, desenha o rodapé
            if footer_drawer and width and height and text_objects:
                footer_drawer(c, width, height, text_objects, page, total_pages)

            c.showPage()
            page += 1

            # Nova página, redesenha cabeçalho
            current_y = y
            header_height = draw_header(current_y)
            total_drawn_height += header_height
            current_y -= header_height

        # Desenha as células da linha
        row_top = current_y
        row_bottom = current_y - row_height
        curr_x = x

        for col_i, para in enumerate(cell_paragraphs):
            para.drawOn(c, curr_x + padding, row_bottom + padding)
            curr_x += col_widths[col_i]

        # Desenha linhas verticais para cada coluna (dentro da linha atual)
        line_x = x
        for col_i in range(num_cols + 1):
            c.line(line_x, row_top, line_x, row_bottom)
            if col_i < num_cols:
                line_x += col_widths[col_i]

        # Linha horizontal inferior da linha
        c.line(x, row_bottom, x + table_width, row_bottom)

        current_y -= row_height
        total_drawn_height += row_height

    # -------------------------------------------------------------------------
    # BORDA FINAL DA TABELA NA ÚLTIMA PÁGINA
    # -------------------------------------------------------------------------
    c.rect(x, current_y, table_width, y - current_y, stroke=1, fill=0)

    return {
        'drawn_height': total_drawn_height,
        'last_page': page
    }

def create_pdf(entries, pdf_path, text_objects, report_date, reference_number, config, general_comments=""):
    """
    Cria o arquivo PDF utilizando os dados fornecidos.
    
    Processa os dados de entradas (entries), agrupa informações para as tabelas de estado e comentários,
    calcula o total de páginas, gera cada seção do PDF (capa, tabelas, entries, página de assinatura) e salva o PDF.
    
    Parâmetros:
      - entries: lista de registros com dados de cada área.
      - pdf_path: caminho onde o PDF será salvo.
      - text_objects: dicionário com textos para cabeçalhos, rodapés e demais seções.
      - report_date: data do relatório.
      - reference_number: número de referência/contrato.
      - config: configurações do documento (cabeçalho, rodapé, etc).
      - general_comments (opcional): comentários gerais para serem incluídos.
    """
    import os
    import logging
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import Paragraph, Frame
    from reportlab.lib.enums import TA_LEFT, TA_CENTER

    logging.info(f"Criando PDF em: {pdf_path}")
    c = canvas.Canvas(pdf_path, pagesize=landscape(A4))
    width, height = landscape(A4)

    # -------------------------------------------------------------------------
    # 1. Separação dos dados para as tabelas de estado (Quadra e Canteiro)
    # -------------------------------------------------------------------------
    quadra_data = []
    canteiro_data = []
    for entry in entries:
        tipo = entry.get('tipo_area', '').strip().lower()
        if tipo == "quadra":
            quadra_data.append([
                entry.get('id_area', 'Desconhecida'),
                entry.get('sigla', 'Desconhecida'),
                entry.get('status', 'Não Concluído')
            ])
        elif tipo == "canteiro":
            canteiro_data.append([
                entry.get('id_area', 'Desconhecida'),
                entry.get('sigla', 'Desconhecida'),
                entry.get('status', 'Não Concluído')
            ])

    def aggregate_data(data_list):
        """
        Agrupa os dados por área e sigla, contando as ocorrências de cada status.
        Em seguida, determina o status majoritário para cada agrupamento.
        """
        aggregated = {}
        for area, sigla, status in data_list:
            key = (area, sigla)
            if key not in aggregated:
                aggregated[key] = {}
            aggregated[key][status] = aggregated[key].get(status, 0) + 1
        result = []
        for key, status_counts in aggregated.items():
            majority_state = max(status_counts.items(), key=lambda x: x[1])[0]
            result.append([key[0], key[1], majority_state])
        return result

    aggregated_quadra_data = aggregate_data(quadra_data)
    aggregated_canteiro_data = aggregate_data(canteiro_data)

    # -------------------------------------------------------------------------
    # 2. Agrega os comentários por área (removendo duplicatas)
    # -------------------------------------------------------------------------
    aggregated_comments_quadra = {}
    aggregated_comments_canteiro = {}

    for entry in entries:
        comment = entry.get('comment', '').strip()
        if comment:
            # Separa o comentário em linhas, removendo linhas vazias
            lines = [line.strip() for line in comment.splitlines() if line.strip()]
            area_type = entry.get('tipo_area', '').strip().lower()
            key = (entry.get('id_area', 'Desconhecida'), entry.get('sigla', 'Desconhecida'))
            if area_type == 'quadra':
                # Atualiza o conjunto com as linhas, garantindo que cada linha apareça apenas uma vez
                aggregated_comments_quadra.setdefault(key, set()).update(lines)
            elif area_type == 'canteiro':
                aggregated_comments_canteiro.setdefault(key, set()).update(lines)

    aggregated_comments_quadra_list = [
        [area, sigla, "\n".join(sorted(comments))]
        for (area, sigla), comments in aggregated_comments_quadra.items()
    ]
    aggregated_comments_canteiro_list = [
        [area, sigla, "\n".join(sorted(comments))]
        for (area, sigla), comments in aggregated_comments_canteiro.items()
    ]

    # -------------------------------------------------------------------------
    # 3. Cálculo da numeração total de páginas
    # -------------------------------------------------------------------------
    disable_states = text_objects.get("disable_states", False)
    table_pages = 0
    if not disable_states:
        if aggregated_quadra_data:
            table_pages += 1
        if aggregated_canteiro_data:
            table_pages += 1
    comment_table_pages = 0
    if aggregated_comments_quadra_list:
        comment_table_pages += 1
    if aggregated_comments_canteiro_list:
        comment_table_pages += 1
    entry_pages = (len(entries) + 1) // 2
    include_last_page = text_objects.get("include_last_page", False)
    total_pages = 1 + table_pages + comment_table_pages + entry_pages + (1 if include_last_page else 0)

    # Mapeia cada sigla para a página onde aparece pela primeira vez (para links internos)
    sigla_to_page = compute_sigla_first_occurrence(entries, table_pages + comment_table_pages)

    current_page = 1

    # Preparação de estilos para as tabelas dinâmicas
    sample_styles = getSampleStyleSheet()
    header_style = ParagraphStyle(
        'headerStyle',
        parent=sample_styles['Heading4'],
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
        fontSize=10,
        textColor='black'
    )
    cell_style = ParagraphStyle(
        'cellStyle',
        parent=sample_styles['Normal'],
        alignment=TA_LEFT,
        fontName='Helvetica',
        fontSize=9,
        leading=11
    )

    # -------------------------------------------------------------------------
    # 4. Página 1: Capa
    # -------------------------------------------------------------------------
    draw_first_page(c, width, height, report_date, config)
    c.showPage()
    current_page += 1

    # -------------------------------------------------------------------------
    # 5. Tabela: Quadra (se houver)
    # -------------------------------------------------------------------------
    if not disable_states and aggregated_quadra_data:
        margin = 40 * mm
        available_width = width - 2 * margin
        headers_quadra = ["Quadra", "Sigla", "Estado"]
        col_widths_quadra = [20 * mm, 50 * mm, 40 * mm]
        row_height = 6 * mm
        gap = 5 * mm
        # Se houver mais de 30 registros, usa a função de paginação:
        if len(aggregated_quadra_data) > 30:
            current_page = draw_paginated_table(
                c,
                "Tabela: Quadra",
                headers_quadra,
                aggregated_quadra_data,
                col_widths_quadra,
                row_height,
                gap,
                available_width,
                sigla_mapping=sigla_to_page,
                text_objects=text_objects,
                width=width,
                height=height,
                current_page=current_page,
                total_pages=total_pages
            )
        else:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(margin, height - 30 * mm, "Tabela: Quadra")
            table_y = height - 30 * mm - 10 * mm
            if len(aggregated_quadra_data) > 15:
                draw_split_table(c, margin, table_y, headers_quadra, aggregated_quadra_data, col_widths_quadra, row_height, gap, available_width, sigla_mapping=sigla_to_page)
            else:
                draw_table(c, margin, table_y, headers_quadra, aggregated_quadra_data, col_widths_quadra, row_height, sigla_mapping=sigla_to_page)
            draw_footer(c, width, height, text_objects, current_page, total_pages)
            c.showPage()
            current_page += 1

    # -------------------------------------------------------------------------
    # 6. Tabela: Canteiro (se houver)
    # -------------------------------------------------------------------------
    if not disable_states and aggregated_canteiro_data:
        margin = 40 * mm
        available_width = width - 2 * margin
        headers_canteiro = ["Canteiro", "Sigla", "Estado"]
        col_widths_canteiro = [20 * mm, 50 * mm, 40 * mm]
        row_height = 6 * mm
        gap = 5 * mm
        # Se houver mais de 30 registros, utiliza a paginação:
        if len(aggregated_canteiro_data) > 30:
            current_page = draw_paginated_table(
                c,
                "Tabela: Canteiro",
                headers_canteiro,
                aggregated_canteiro_data,
                col_widths_canteiro,
                row_height,
                gap,
                available_width,
                sigla_mapping=sigla_to_page,
                text_objects=text_objects,
                width=width,
                height=height,
                current_page=current_page,
                total_pages=total_pages
            )
        else:
            c.setFont("Helvetica-Bold", 12)
            c.drawString(margin, height - 30 * mm, "Tabela: Canteiro")
            table_y = height - 30 * mm - 10 * mm
            if len(aggregated_canteiro_data) > 15:
                draw_split_table(c, margin, table_y, headers_canteiro, aggregated_canteiro_data, col_widths_canteiro, row_height, gap, available_width, sigla_mapping=sigla_to_page)
            else:
                draw_table(c, margin, table_y, headers_canteiro, aggregated_canteiro_data, col_widths_canteiro, row_height, sigla_mapping=sigla_to_page)
            draw_footer(c, width, height, text_objects, current_page, total_pages)
            c.showPage()
            current_page += 1

    # -------------------------------------------------------------------------
    # 7. Tabela: Comentários das Quadras (se houver) – usando célula dinâmica
    # -------------------------------------------------------------------------
    # Tabela: Comentários das Quadras (se houver)
    if not text_objects.get("disable_comments_table", False) and aggregated_comments_quadra_list:
        margin = 40 * mm
        available_width = width - 2 * margin
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, height - 30 * mm, "Tabela: Comentários das Quadras")
        table_y = height - 30 * mm - 10 * mm
        headers_comments = ["Quadra", "Sigla", "Comentários"]
        col_widths_comments = [30 * mm, 30 * mm, available_width - 60 * mm]
        result = draw_dynamic_table(c, margin, table_y, headers_comments, aggregated_comments_quadra_list,
                                    col_widths_comments, header_style, cell_style,
                                    bottom_margin=20*mm, padding=2*mm,
                                    footer_drawer=draw_footer, page=current_page,
                                    total_pages=total_pages, width=width, height=height, text_objects=text_objects)
        # Atualiza o número de página usado pela tabela
        current_page = result['last_page']
        # Após a tabela, desenha o rodapé na página final da tabela (caso não tenha sido já desenhado)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1

    # -------------------------------------------------------------------------
    # 8. Tabela: Comentários dos Canteiros (se houver) – usando células dinâmicas
    # -------------------------------------------------------------------------
    if not text_objects.get("disable_comments_table", False) and aggregated_comments_canteiro_list:
        margin = 40 * mm
        available_width = width - 2 * margin
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, height - 30 * mm, "Tabela: Comentários dos Canteiros")
        table_y = height - 30 * mm - 10 * mm
        headers_comments = ["Canteiro", "Sigla", "Comentários"]
        col_widths_comments = [30 * mm, 30 * mm, available_width - 60 * mm]
        result = draw_dynamic_table(
            c, margin, table_y, headers_comments, aggregated_comments_canteiro_list,
            col_widths_comments, header_style, cell_style,
            bottom_margin=20*mm, padding=2*mm,
            footer_drawer=draw_footer, page=current_page,
            total_pages=total_pages, width=width, height=height, text_objects=text_objects
        )
        # Atualiza o número da página conforme o retorno da função
        current_page = result['last_page']
        # Desenha o rodapé na página final da tabela (caso ainda não tenha sido desenhado)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1


    # --- NOVA PÁGINA: Comentários Gerais ---
    if text_objects.get('general_comments'):
        margin = 40 * mm
        bottom_margin = 20 * mm  # Espaço reservado para o rodapé

        # Título da seção de comentários gerais
        c.setFont("Helvetica-Bold", 16)
        title_y = height - 30 * mm
        c.drawCentredString(width / 2, title_y, "Comentários Gerais")
        
        # O texto começa, por exemplo, 5 mm abaixo do título
        current_y = title_y - 5 * mm
        max_width = width - 2 * margin

        # Define o estilo para os parágrafos dos comentários gerais
        styles = getSampleStyleSheet()
        general_style = ParagraphStyle(
            'GeneralComments',
            parent=styles['Normal'],
            fontSize=12,
            leading=14,      # Espaçamento de linha
            spaceBefore=0,
            spaceAfter=0
        )

        # Separa os comentários por linha
        # Trata cada quebra de linha como um parágrafo
        paragraphs = text_objects['general_comments'].split("\n")

        spacing = 2  # Sem espaçamento extra entre parágrafos

        for para_text in paragraphs:
            # Se houver espaços iniciais, substitui por non-breaking spaces
            match = re.match(r"^( +)", para_text)
            if match:
                leading = match.group(1).replace(" ", "&nbsp;")
                para_text = leading + para_text[len(match.group(1)):]
            
            # Se o parágrafo estiver vazio, substitua por um non-breaking space para manter a altura
            if para_text == "":
                para_text = u'\u00A0'
            
            para_obj = Paragraph(para_text, general_style)
            available_space = current_y - bottom_margin
            w_para, h_para = para_obj.wrap(max_width, available_space)
            
            if h_para > available_space:
                draw_footer(c, width, height, text_objects, current_page, total_pages)
                c.showPage()
                current_page += 1
                current_y = height - bottom_margin
                available_space = current_y - bottom_margin
                w_para, h_para = para_obj.wrap(max_width, available_space)
            
            para_obj.drawOn(c, margin, current_y - h_para)
            current_y -= (h_para + spacing)
            
            if current_y - bottom_margin < 10 * mm:
                draw_footer(c, width, height, text_objects, current_page, total_pages)
                c.showPage()
                current_page += 1
                current_y = height - bottom_margin


        # Desenha o rodapé na última página de comentários gerais
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1






    # -------------------------------------------------------------------------
    # 9. Páginas de Entries (2 por página)
    # -------------------------------------------------------------------------
    margin = 40 * mm
    usable_width = width - 2 * margin
    horizontal_spacing = 5 * mm
    max_image_width = (usable_width / 2) - 5 * mm
    max_image_height = 76 * mm

    for i in range(0, len(entries), 2):
        draw_header(c, width, height, text_objects)
        # Adiciona bookmarks para a primeira ocorrência de siglas nesta página de entries
        current_entries = entries[i:i+2]
        current_page_entries = table_pages + comment_table_pages + 1 + (i // 2)
        for entry in current_entries:
            sigla = entry.get('sigla')
            if sigla and sigla_to_page.get(sigla) == current_page_entries:
                c.bookmarkPage("sigla_" + str(sigla))
        for j in range(2):
            if i + j >= len(entries):
                break
            entry = entries[i + j]
            x_position = margin if j == 0 else margin + (usable_width / 2) + (horizontal_spacing / 2)
            y_position = height - 35 * mm
            description_height = 70 * mm
            block_height = max_image_height + description_height + 5 * mm
            block_width = (usable_width / 2) - (horizontal_spacing / 2)
            status = entry.get('status', "Não Concluído")
            color = STATUS_COLORS.get(status, (1, 1, 1))
            block_x = x_position - 2 * mm
            block_y = y_position - block_height - 2 * mm
            block_width_adjusted = block_width + 4 * mm
            block_height_adjusted = block_height + 4 * mm
            c.saveState()
            c.setFillColorRGB(*color)
            c.rect(block_x, block_y, block_width_adjusted, block_height_adjusted, fill=1, stroke=0)
            c.restoreState()
            if entry.get('image'):
                temp_image_path = save_temp_image(entry['image'])
                try:
                    from PIL import Image as PILImage
                    with PILImage.open(temp_image_path) as img:
                        img_width, img_height = img.size
                    scale = min(max_image_width / img_width, max_image_height / img_height)
                    img_draw_width = img_width * scale
                    img_draw_height = img_height * scale
                    center_x = block_x + (block_width_adjusted / 2)
                    img_draw_x = center_x - (img_draw_width / 2)
                    img_y_position = y_position - img_draw_height
                    c.drawImage(temp_image_path, img_draw_x, img_y_position, width=img_draw_width, height=img_draw_height)
                    description_x = x_position
                    description_y = img_y_position - 1 * mm
                finally:
                    try:
                        os.remove(temp_image_path)
                    except Exception as e:
                        logging.warning(f"Não foi possível remover o arquivo temporário {temp_image_path}: {e}")
            else:
                description_x = x_position
                description_y = y_position
            description_width = block_width - 5 * mm
            styles = getSampleStyleSheet()
            style = styles['Normal']
            style.fontName = 'Helvetica'
            style.fontSize = 10
            style.alignment = TA_LEFT
            description_text = entry.get('description', '').replace("target='_blank'", "")
            from reportlab.platypus import Paragraph
            paragraph = Paragraph(description_text, style)
            from reportlab.platypus import Frame
            frame = Frame(description_x, description_y - description_height, description_width, description_height, showBoundary=0)
            frame.addFromList([paragraph], c)
        draw_footer(c, width, height, text_objects, table_pages + comment_table_pages + 1 + (i // 2), total_pages)
        c.showPage()
        current_page += 1

    # -------------------------------------------------------------------------
    # 10. Página opcional de assinatura
    # -------------------------------------------------------------------------
    if include_last_page:
        draw_signature_section(c, width, height, text_objects)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
    c.save()
    logging.info("PDF criado com sucesso.")



def convert_data_to_pdf(report_date, contract_number, entries, pdf_path, include_last_page=False, disable_states=False, general_comments="", disable_comments_table=False):
    """
    Função principal que converte os dados fornecidos em um PDF.
    
    Parâmetros:
      - report_date: data do relatório.
      - contract_number: número do contrato.
      - entries: lista de registros com os dados de cada imagem/área.
      - pdf_path: caminho para salvar o PDF.
      - include_last_page: flag para incluir a página de assinatura.
      - disable_states: flag para desabilitar as tabelas de estados.
      - general_comments: comentários gerais a serem incluídos.
      - disable_comments_table: flag para desabilitar as tabelas de comentários.
    """
    settings = Settings()
    config = settings.config
    if not contract_number:
        contract_number = config.get("reference_number", "")
    # Cria o dicionário de textos utilizado nas diversas seções do PDF
    text_objects = {
        'section1': config["header_1"],
        'section2': config["header_2"],
        'section3': config["title"],
        'footer_lines': [
            config["address"],
            f"{config['postal_code']} - {config['contact_phone']} - {config['contact_fax']}",
            config["contact_email"]
        ],
        'location_date': f"{config['address']}, {report_date}",
        'sign1': config["sign1"],
        'sign1_name': config["sign1_name"],
        'sign2': config["sign2"],
        'sign2_name': config["sign2_name"],
        'include_last_page': include_last_page,
        'disable_states': disable_states,                   # repassa o parâmetro para criar condicionalmente as páginas de estados
        'disable_comments_table': disable_comments_table    # repassa o estado para desabilitar as tabelas de comentários
    }

     # Se os comentários gerais tiverem mais de 10 caracteres, são incluídos; caso contrário, fica vazio
    text_objects['general_comments'] = general_comments if len(general_comments.strip()) > 10 else ""

    # Chama a função que efetivamente cria o PDF com os dados processados
    create_pdf(entries, pdf_path, text_objects, report_date, contract_number, config, general_comments)

