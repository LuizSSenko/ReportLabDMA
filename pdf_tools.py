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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("pdf_tools.log"),
        logging.StreamHandler()
    ]
)

# Mapeamento de cores para os estados (não precisa ser alterado)
STATUS_COLORS = {
    "Concluído": (0.90, 1.0, 0.90),      # verde claro
    "Parcial": (1.0, 1.0, 0.85),         # amarelo claro
    "Não Concluído": (1.0, 0.90, 0.90)    # vermelho claro
}

def load_pdf_config():
    user_config_path = Path(__file__).parent / "pdf_config_user.json"
    default_config_path = Path(__file__).parent / "pdf_config_default.json"
    
    # Tenta carregar o arquivo de configuração do usuário
    if user_config_path.exists():
        try:
            with user_config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            logging.info(f"Configuração do usuário carregada de {user_config_path}.")
            return config
        except Exception as e:
            logging.error(f"Erro ao carregar a configuração do usuário: {e}", exc_info=True)
    
    # Se não existir ou der erro, carrega a configuração padrão
    if default_config_path.exists():
        try:
            with default_config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            logging.info("Configuração padrão carregada.")
            return config
        except Exception as e:
            logging.error(f"Erro ao carregar a configuração padrão: {e}", exc_info=True)
    
    # Caso nenhum arquivo seja encontrado, retorna um dicionário com valores padrão
    logging.warning("Nenhum arquivo de configuração encontrado. Usando valores padrão.")
    return {
        "header_1": "DAV - DIRETORIA DE ÁREAS VERDES / DMA - DIVISÃO DE MEIO AMBIENTE",
        "header_2": "UNICAMP - UNIVERSIDADE ESTADUAL DE CAMPINAS",
        "title": "RELATÓRIO DE VISTORIA - SERVIÇOS PROVAC",
        "date_prefix": "DATA DO RELATÓRIO:",
        "reference_number": "CONTRATO Nº: 039/2019 - PROVAC TERCEIRIZAÇÃO DE MÃO DE OBRA LTDA",
        "description": "Vistoria de campo realizada pelos técnicos da DAV/DMA,",
        "address": "Rua 5 de Junho, 251 - Cidade Universitária Zeferino Vaz - Campinas - SP",
        "postal_code": "CEP: 13083-877",
        "contact_phone": "Tel: (19) 3521-7010",
        "contact_fax": "Fax: (19) 3521-7835",
        "contact_email": "mascerct@unicamp.br"
    }

def save_temp_image(image_data):
    """
    Salva os dados da imagem em um arquivo temporário e retorna o caminho.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
        img = Image.open(BytesIO(image_data))
        img.save(temp_file, format='PNG')
        temp_file_path = temp_file.name
    logging.debug(f"Saved temporary image: {temp_file_path}")
    return temp_file_path

def draw_first_page(c, width, height, report_date, config):
    """
    Desenha a primeira página do PDF com cabeçalho, informações do relatório e rodapé.
    """
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 30 * mm, config["header_1"])
    c.drawCentredString(width / 2, height - 40 * mm, config["header_2"])

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 60 * mm, config["title"])

    c.setFont("Helvetica", 12)
    c.drawString(40 * mm, height - 80 * mm, f"{config['date_prefix']} {report_date}")
    c.drawString(40 * mm, height - 90 * mm, config["reference_number"])
    c.drawString(40 * mm, height - 110 * mm, config["description"])

    # Footer (desenhado aqui, para não duplicar)
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 20 * mm, config["address"])
    c.drawCentredString(width / 2, 15 * mm, f"{config['postal_code']} - {config['contact_phone']} - {config['contact_fax']}")
    c.drawCentredString(width / 2, 10 * mm, config["contact_email"])

def draw_header(c, width, height, text_objects):
    """
    Desenha o cabeçalho das páginas subsequentes.
    """
    y_position = height - 20 * mm
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
    Desenha o rodapé em cada página (incluindo numeração).
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
    Desenha a página de assinatura na última página.
    """
    left_x = width / 4
    right_x = (3 * width) / 4
    y_position = height / 4
    c.setFont("Helvetica", 10)
    c.drawRightString(width - 40 * mm, 25 * mm, f"{text_objects['location_date']}")
    c.setFont("Helvetica", 10)
    c.drawCentredString(left_x, y_position + 20, text_objects.get("sign1", "PREPOSTO CONTRATANTE"))
    c.drawCentredString(left_x, y_position + 10, text_objects.get("sign1_name", ""))
    c.drawCentredString(left_x, y_position, "Data: ........./........../...........")
    c.setFont("Helvetica", 10)
    c.drawCentredString(right_x, y_position + 20, text_objects.get("sign2", "PREPOSTO CONTRATADA"))
    c.drawCentredString(right_x, y_position + 10, text_objects.get("sign2_name", "Laércio P. Oliveira"))
    c.drawCentredString(right_x, y_position, "Data: .........../.........../...........")

###############################################
# FUNÇÕES PARA A PÁGINA 2 (TABELAS DINÂMICAS)
###############################################


def compute_sigla_first_occurrence(entries: List[dict], table_pages: int) -> dict:
    """
    Calcula um dicionário que mapeia cada sigla para o número da página onde ela
    aparece pela primeira vez nos registros (entries). Considera que as páginas de entries
    começam após a capa e as páginas de tabelas.
    Cada página de entries contém 2 registros.
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
    Desenha uma tabela simples usando o canvas.
    
    Se 'sigla_mapping' for fornecido, a célula da coluna "Sigla" se tornará clicável,
    apontando para o destino interno "sigla_<valor>".
    """
    num_cols = len(headers)
    num_rows = len(data) + 1  # +1 para o cabeçalho
    table_width = sum(col_widths)
    table_height = num_rows * row_height

    # Cabeçalho com fundo cinza
    c.saveState()
    c.setFillColorRGB(0.8, 0.8, 0.8)
    c.rect(x, y - row_height, table_width, row_height, fill=1, stroke=0)
    c.restoreState()
    
    c.setFillColorRGB(0, 0, 0)
    col_x = x
    for i, header in enumerate(headers):
        c.setFont("Helvetica-Bold", 10)
        c.drawString(col_x + 2 * mm, y - row_height + 2 * mm, header)
        col_x += col_widths[i]
    
    for row_index, row in enumerate(data):
        current_y = y - (row_index + 2) * row_height
        col_x = x
        for col_index, cell in enumerate(row):
            if headers[col_index] == "Estado":
                status = cell
                color = STATUS_COLORS.get(status, (1, 1, 1))
                c.saveState()
                c.setFillColorRGB(*color)
                c.rect(col_x, current_y, col_widths[col_index], row_height, fill=1, stroke=0)
                c.restoreState()
            c.setFont("Helvetica", 10)
            c.drawString(col_x + 2 * mm, current_y + 2 * mm, str(cell))
            if headers[col_index] == "Sigla" and sigla_mapping is not None:
                # Cria uma área clicável que aponta para o destino "sigla_<valor>"
                link_rect = (col_x, current_y, col_x + col_widths[col_index], current_y + row_height)
                c.linkRect("", "sigla_" + str(cell), link_rect, relative=0, thickness=0)
            col_x += col_widths[col_index]
    
    for i in range(num_rows + 1):
        c.line(x, y - i * row_height, x + table_width, y - i * row_height)
    col_x = x
    for width_i in col_widths:
        c.line(col_x, y, col_x, y - table_height)
        col_x += width_i
    c.line(x + table_width, y, x + table_width, y - table_height)

def draw_split_table(c, x, y, headers, data, col_widths, row_height, gap, available_width, sigla_mapping=None):
    """
    Desenha uma tabela dividida em duas colunas lado a lado, cada coluna com até 15 linhas.
    Se o número de linhas for <=15, desenha uma única tabela.
    Se >15, divide os dados em:
       left_data = data[:15]
       right_data = data[15:30]
    O parâmetro 'available_width' indica a largura total disponível.
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

def create_pdf(entries, pdf_path, text_objects, report_date, reference_number, config):
    logging.info(f"Criando PDF em: {pdf_path}")
    c = canvas.Canvas(pdf_path, pagesize=landscape(A4))
    width, height = landscape(A4)

    # Separa os dados para as tabelas com base em 'tipo_area'
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
    # Agrega os registros repetidos
    def aggregate_data(data_list: List[List[str]]) -> List[List[str]]:
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

    # Cálculo do total de páginas:
    # Página 1: Capa
    # 1 página para tabela de Quadra (se houver)
    # 1 página para tabela de Canteiro (se houver)
    # Páginas para entries (2 por página)
    # Opcional: página de assinatura
    table_pages = 0
    if aggregated_quadra_data:
        table_pages += 1
    if aggregated_canteiro_data:
        table_pages += 1
    entry_pages = (len(entries) + 1) // 2
    include_last_page = text_objects.get("include_last_page", False)
    total_pages = 1 + table_pages + entry_pages + (1 if include_last_page else 0)

    # Calcula o mapeamento de siglas para a página de sua primeira ocorrência (para links internos)
    sigla_to_page = compute_sigla_first_occurrence(entries, table_pages)

    current_page = 1

    # Página 1: Capa (draw_first_page já inclui o footer)
    draw_first_page(c, width, height, report_date, config)
    c.showPage()
    current_page += 1

    # Página para tabela de Quadra
    if aggregated_quadra_data:
        margin = 40 * mm
        available_width = width - 2 * margin
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, height - 30 * mm, "Tabela: Quadra")
        table_y = height - 30 * mm - 10 * mm
        headers_quadra = ["Quadra", "Sigla", "Estado"]
        col_widths_quadra = [20 * mm, 50 * mm, 40 * mm]
        row_height = 6 * mm
        gap = 5 * mm
        # Passa o mapeamento para que a coluna "Sigla" fique clicável
        if len(aggregated_quadra_data) > 15:
            draw_split_table(c, margin, table_y, headers_quadra, aggregated_quadra_data, col_widths_quadra, row_height, gap, available_width, sigla_mapping=sigla_to_page)
        else:
            draw_table(c, margin, table_y, headers_quadra, aggregated_quadra_data, col_widths_quadra, row_height, sigla_mapping=sigla_to_page)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1

    # Página para tabela de Canteiro
    if aggregated_canteiro_data:
        margin = 40 * mm
        available_width = width - 2 * margin
        c.setFont("Helvetica-Bold", 12)
        c.drawString(margin, height - 30 * mm, "Tabela: Canteiro")
        table_y = height - 30 * mm - 10 * mm
        headers_canteiro = ["Canteiro", "Sigla", "Estado"]
        col_widths_canteiro = [20 * mm, 50 * mm, 40 * mm]
        row_height = 6 * mm
        gap = 5 * mm
        if len(aggregated_canteiro_data) > 15:
            draw_split_table(c, margin, table_y, headers_canteiro, aggregated_canteiro_data, col_widths_canteiro, row_height, gap, available_width, sigla_mapping=sigla_to_page)
        else:
            draw_table(c, margin, table_y, headers_canteiro, aggregated_canteiro_data, col_widths_canteiro, row_height, sigla_mapping=sigla_to_page)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1

    # Páginas para as entries (2 por página)
    margin = 40 * mm
    usable_width = width - 2 * margin
    horizontal_spacing = 5 * mm
    max_image_width = (usable_width / 2) - 5 * mm
    max_image_height = 76 * mm

    for i in range(0, len(entries), 2):
        draw_header(c, width, height, text_objects)
        # Adiciona bookmarks para a primeira ocorrência de siglas nesta página de entries
        current_entries = entries[i:i+2]
        # A página de entries tem índice = table_pages + 1 + (i//2)
        current_page_entries = table_pages + 1 + (i // 2)
        for entry in current_entries:
            sigla = entry.get('sigla')
            if sigla and sigla_to_page.get(sigla) == current_page_entries:
                c.bookmarkPage("sigla_" + str(sigla))
        for j in range(2):
            if i + j >= len(entries):
                break
            entry = entries[i + j]
            x_position = margin if j == 0 else margin + (usable_width / 2) + (horizontal_spacing / 2)
            y_position = height - 40 * mm
            description_height = 65 * mm
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
            paragraph = Paragraph(description_text, style)
            frame = Frame(description_x, description_y - description_height, description_width, description_height, showBoundary=0)
            frame.addFromList([paragraph], c)
        draw_footer(c, width, height, text_objects, table_pages + 1 + (i // 2), total_pages)
        c.showPage()
        current_page += 1

    # Página de assinatura (se selecionada)
    if include_last_page:
        draw_signature_section(c, width, height, text_objects)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
    c.save()
    logging.info("PDF criado com sucesso.")

def convert_data_to_pdf(report_date, contract_number, entries, pdf_path, include_last_page=False):
    config = load_pdf_config()
    if not contract_number:
        contract_number = config.get("reference_number", "")
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
        'sign1': config.get("sign1", "PREPOSTO CONTRATANTE"),
        'sign1_name': config.get("sign1_name", ""),
        'sign2': config.get("sign2", "PREPOSTO CONTRATADA"),
        'sign2_name': config.get("sign2_name", "NOME: Laércio P. Oliveira"),
        'include_last_page': include_last_page
    }
    create_pdf(entries, pdf_path, text_objects, report_date, contract_number, config)
