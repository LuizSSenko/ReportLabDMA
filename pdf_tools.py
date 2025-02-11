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
    """
    Carrega o arquivo de configuração JSON contendo os textos do PDF.
    Caso o arquivo não seja encontrado, retorna um dicionário com valores padrão.
    """
    config_path = Path(__file__).parent / "pdf_config.json"
    if config_path.exists():
        try:
            with config_path.open("r", encoding="utf-8") as f:
                config = json.load(f)
            logging.info(f"Arquivo de configuração '{config_path}' carregado com sucesso.")
            return config
        except Exception as e:
            logging.error(f"Erro ao carregar o arquivo de configuração: {e}", exc_info=True)
    else:
        logging.warning(f"Arquivo de configuração '{config_path}' não encontrado. Usando valores padrão.")
    
    # Valores padrão (caso o JSON não exista ou ocorra algum erro)
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
    Desenha a primeira página do PDF com cabeçalho e informações do relatório,
    usando os textos do arquivo de configuração.
    """
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, height - 30 * mm, config["header_1"])
    c.drawCentredString(width / 2, height - 40 * mm, config["header_2"])

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(width / 2, height - 60 * mm, config["title"])

    c.setFont("Helvetica", 12)
    # Usa o prefixo definido no JSON e a data fornecida
    c.drawString(40 * mm, height - 80 * mm, f"{config['date_prefix']} {report_date}")
    c.drawString(40 * mm, height - 90 * mm, config["reference_number"])
    c.drawString(40 * mm, height - 110 * mm, config["description"])

    # Footer
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
    Desenha o rodapé em cada página.
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

    # Número da página
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
    # Utiliza sign1 e sign1_name para o lado esquerdo
    c.drawCentredString(left_x, y_position + 20, text_objects.get("sign1", "PREPOSTO CONTRATANTE")) #Caso não tenha sido definido no JSON o valor padrão é "PREPOSTO CONTRATANTE"
    c.drawCentredString(left_x, y_position + 10, text_objects.get("sign1_name", "")) #Caso não tenha sido definido no JSON o valor padrão é "" (vazio)
    c.drawCentredString(left_x, y_position, "Data: ........./........../...........")

    c.setFont("Helvetica", 10)
    # Utiliza sign2 e sign2_name para o lado direito
    c.drawCentredString(right_x, y_position + 20, text_objects.get("sign2", "PREPOSTO CONTRATADA")) #Caso não tenha sido definido no JSON o valor padrão é "PREPOSTO CONTRATADA"
    c.drawCentredString(right_x, y_position + 10, text_objects.get("sign2_name", "Laércio P. Oliveira")) #Caso não tenha sido definido no JSON o valor padrão é "Laércio P. Oliveira"
    c.drawCentredString(right_x, y_position, "Data: .........../.........../...........")

def create_pdf(entries, pdf_path, text_objects, report_date, reference_number, config):
    """
    Cria o PDF a partir das entradas fornecidas.
    
    Parâmetros:
      - entries (list): Lista de dicionários com as entradas (cada entrada deve ter 'image', 'description' e 'status').
      - pdf_path (str): Caminho para salvar o PDF.
      - text_objects (dict): Elementos textuais para cabeçalho, rodapé, etc.
      - report_date (str): Data do relatório.
      - reference_number (str): Número do contrato (obtido da configuração).
      - config (dict): Dicionário com os textos carregados do JSON.
    """
    logging.info(f"Criando PDF em: {pdf_path}")
    c = canvas.Canvas(pdf_path, pagesize=landscape(A4))
    width, height = landscape(A4)

    # Calcula o total de páginas (exemplo: 1 página de capa + 1 página para cada 2 entradas)
    total_pages = (len(entries) + 1) // 2 + 1  # +1 para a primeira página

    # Verifica se a página de assinatura será incluída
    include_last_page = text_objects.get("include_last_page", False)
    if include_last_page:
        total_pages += 1

    # Primeira página (capa)
    draw_first_page(c, width, height, report_date, config)
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 5 * mm, f"Página 1 de {total_pages}")
    c.showPage()

    # Páginas subsequentes para as entradas (2 por página)
    margin = 40 * mm
    usable_width = width - 2 * margin
    horizontal_spacing = 5 * mm

    max_image_width = (usable_width / 2) - 5 * mm
    max_image_height = 76 * mm

    current_page = 2

    for i in range(0, len(entries), 2):
        draw_header(c, width, height, text_objects)
    
        for j in range(2):
            if i + j >= len(entries):
                break
            entry = entries[i + j]
            if j == 0:
                x_position = margin
            else:
                x_position = margin + (usable_width / 2) + (horizontal_spacing / 2)
    
            y_position = height - 40 * mm
            # Definindo as dimensões do bloco que abrange imagem + descrição + uma margem extra
            description_height = 65 * mm
            block_height = max_image_height + description_height + 5 * mm
            block_width = (usable_width / 2) - (horizontal_spacing / 2)
    
            # Obtém a cor de fundo de acordo com o estado
            status = entry.get('status', "Não Concluído")
            color = STATUS_COLORS.get(status, (1, 1, 1))
    
            # Calcula as coordenadas do retângulo de fundo com uma margem extra
            block_x = x_position - 2 * mm
            block_y = y_position - block_height - 2 * mm
            block_width_adjusted = block_width + 4 * mm
            block_height_adjusted = block_height + 4 * mm
    
            # Desenha o retângulo de fundo com a cor definida
            c.saveState()
            c.setFillColorRGB(*color)
            c.rect(block_x, block_y, block_width_adjusted, block_height_adjusted, fill=1, stroke=0)
            c.restoreState()
    
            # Desenha a imagem centralizada dentro do bloco
            if entry.get('image'):
                temp_image_path = save_temp_image(entry['image'])
                try:
                    with Image.open(temp_image_path) as img:
                        img_width, img_height = img.size
                    scale = min(max_image_width / img_width, max_image_height / img_height)
                    img_draw_width = img_width * scale
                    img_draw_height = img_height * scale
                    # Calcula a posição horizontal para centralizar a imagem no bloco:
                    center_x = block_x + (block_width_adjusted / 2)
                    img_draw_x = center_x - (img_draw_width / 2)
                    # A posição vertical permanece baseada em y_position:
                    img_y_position = y_position - img_draw_height
                    c.drawImage(temp_image_path, img_draw_x, img_y_position, width=img_draw_width, height=img_draw_height)
                    description_x = x_position  # Pode ajustar se desejar centralizar o texto também
                    description_y = img_y_position - 1 * mm  # Espaço entre a imagem e o texto
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
    
            # Remover o atributo target="_blank" do texto, pois o ReportLab não o suporta
            description_text = entry.get('description', '').replace("target='_blank'", "")
            paragraph = Paragraph(description_text, style)
            frame = Frame(description_x, description_y - description_height, description_width, description_height, showBoundary=0)
            frame.addFromList([paragraph], c)
    
        draw_footer(c, width, height, text_objects, current_page, total_pages)
        c.showPage()
        current_page += 1
    
    # Página de assinatura (se selecionada)
    if include_last_page:
        draw_signature_section(c, width, height, text_objects)
        draw_footer(c, width, height, text_objects, current_page, total_pages)
    
    c.save()
    logging.info("PDF criado com sucesso.")

def convert_data_to_pdf(report_date, contract_number, entries, pdf_path, include_last_page=False):
    # Carrega a configuração a partir do arquivo JSON
    config = load_pdf_config()
    
    # Se desejar que o valor de 'contract_number' venha da configuração, pode fazer:
    if not contract_number:
        contract_number = config.get("reference_number", "")
    
    # Cria o dicionário de textos para o PDF, incluindo as novas chaves:
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
