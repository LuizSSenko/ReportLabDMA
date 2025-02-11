# main.py
import os
import json
import re
import logging
from pathlib import Path
from datetime import datetime
from shapely.geometry import Point, shape
from PIL import Image, ImageOps
from io import BytesIO
import base64

# Configuração do logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler()
    ]
)

# Constantes
IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".heic"]

# =============================================================================
# Funções Auxiliares
# =============================================================================

def sanitize_sigla(sigla: str) -> str:
    """
    Substitui caracteres inválidos para nomes de arquivos por hífens.
    """
    invalid_chars = '<>:"/\\|?*'
    for c in invalid_chars:
        sigla = sigla.replace(c, '-')
    return sigla

def load_geojson():
    """
    Carrega o arquivo GeoJSON contendo as informações de quadras.
    """
    geojson_path = Path(__file__).parent / "quadras2024_wgs84.geojson"
    try:
        with geojson_path.open('r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except Exception as e:
        logging.critical(f"Falha ao carregar GeoJSON: {e}")
        raise

def get_exif_and_image(image_file: Path):
    """
    Abre a imagem, extrai os metadados EXIF e corrige a orientação.
    """
    try:
        with Image.open(image_file) as img:
            exif_data = img._getexif() or {}
            img_corrected = ImageOps.exif_transpose(img)
            return exif_data, img_corrected
    except Exception as e:
        logging.error(f"Erro ao abrir {image_file}: {e}")
        return {}, None

def get_coordinates(gps_info):
    """
    Converte as informações de GPS do EXIF em coordenadas decimais.
    """
    if not gps_info or not isinstance(gps_info, dict):
        return "Sem localização", "Sem localização"

    def convert_to_degrees(value):
        try:
            def rational_to_float(rational):
                if isinstance(rational, tuple):
                    return float(rational[0]) / float(rational[1])
                return float(rational)
            d = rational_to_float(value[0])
            m = rational_to_float(value[1])
            s = rational_to_float(value[2])
            return d + (m / 60.0) + (s / 3600.0)
        except Exception as e:
            logging.error(f"Erro na conversão de coordenadas: {e}")
            return None

    lat = convert_to_degrees(gps_info.get(2)) if 2 in gps_info else None
    lon = convert_to_degrees(gps_info.get(4)) if 4 in gps_info else None

    if lat is None or lon is None:
        return "Sem localização", "Sem localização"

    if gps_info.get(1) == 'S':
        lat = -lat
    if gps_info.get(3) == 'W':
        lon = -lon

    gmaps_link = f"https://www.google.com/maps?q={lat},{lon}"
    coordinates_str = f"{lat}, {lon}"
    return coordinates_str, gmaps_link

def extract_image_datetime(image_path: Path):
    """
    Extrai a data/hora da imagem utilizando os metadados EXIF ou a data de modificação do arquivo.
    """
    try:
        exif_data, _ = get_exif_and_image(image_path)
        if exif_data and isinstance(exif_data, dict):
            for tag in [36867, 36868, 306]:
                if tag in exif_data:
                    date_str = exif_data[tag]
                    dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                    return dt.strftime("%Y-%m-%d_%H-%M-%S")
    except Exception as e:
        logging.error(f"Erro ao extrair EXIF de {image_path}: {e}")
    try:
        timestamp = image_path.stat().st_mtime
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d_%H-%M-%S")
    except Exception as e:
        logging.error(f"Erro ao obter data de modificação de {image_path}: {e}")
        return None

def find_nearest_geometry(features, lat, lon):
    """
    Encontra a feature mais próxima das coordenadas fornecidas.
    """
    point = Point(lon, lat)
    min_distance = float('inf')
    nearest_quad = None

    for feature in features:
        try:
            geom = shape(feature.get('geometry'))
            distance = point.distance(geom)
            if distance < min_distance:
                min_distance = distance
                nearest_quad = feature.get('properties')
        except Exception as e:
            logging.error(f"Erro ao processar feature: {e}")
            continue

    if nearest_quad:
        quadra = nearest_quad.get('Quadra', 'Desconhecida')
        sigla = nearest_quad.get('Sigla', 'Desconhecida')
        return quadra, sigla, min_distance

    return "Sem quadra", "Sem sigla", float('inf')

def is_friendly_name(filename: str) -> bool:
    """
    Verifica se o nome do arquivo está no formato "001 - Descrição.ext".
    """
    pattern = r"^\d{3}\s*-\s*.+\.\w+$"
    return re.match(pattern, filename) is not None

def generate_new_filename(index: int, sigla: str, ext: str) -> str:
    """
    Gera um novo nome de arquivo no formato "Índice - SIGLA.ext".
    """
    sigla_sanitizada = sanitize_sigla(sigla)
    return f"{index:03} - {sigla_sanitizada}{ext}"

def generate_thumbnail_base64(img, max_size=(500, 500), fmt='JPEG'):
    """
    Gera uma miniatura da imagem e a converte para uma string Base64.
    """
    try:
        thumb = img.copy()
        thumb.thumbnail(max_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        thumb.save(buffer, format=fmt)
        base64_thumb = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return base64_thumb, thumb.size
    except Exception as e:
        logging.error(f"Erro ao gerar thumbnail: {e}")
        return "", (0, 0)

# =============================================================================
# Funções Principais
# =============================================================================

def rename_images(directory: Path, selected_images=None):
    """
    Renomeia os arquivos de imagem no diretório utilizando informações do EXIF e GeoJSON.
    """
    geojson_data = load_geojson()
    if selected_images is not None:
        image_files = sorted([directory / f for f in selected_images if (directory / f).suffix.lower() in IMAGE_EXTENSIONS])
    else:
        image_files = sorted([f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS])
    renamed_files = []
    existing_friendly = [f for f in image_files if is_friendly_name(f.name)]
    existing_indices = []
    for f in existing_friendly:
        match = re.match(r"^(\d{3})\s*-\s*.+\.\w+$", f.name)
        if match:
            existing_indices.append(int(match.group(1)))
    max_index = max(existing_indices) if existing_indices else 0
    next_index = max_index + 1

    for image_file in image_files:
        logging.info(f"Processando imagem: {image_file.name}...")
        try:
            if is_friendly_name(image_file.name):
                logging.info(f" -> Já está no formato amigável: {image_file.name}")
                renamed_files.append(image_file.name)
                continue
            exif_data, img = get_exif_and_image(image_file)
            gps_info = exif_data.get(34853) if exif_data else None
            coordinates, gmaps_link = get_coordinates(gps_info)
            capture_datetime = extract_image_datetime(image_file)
            date_time_formatted = capture_datetime if capture_datetime else "DataDesconhecida"
            if coordinates != "Sem localização":
                try:
                    lat, lon = map(float, coordinates.split(", "))
                    quadra, sigla, distance = find_nearest_geometry(geojson_data['features'], lat, lon)
                except Exception as conv_err:
                    logging.error(f"Erro ao converter coordenadas: {conv_err}")
                    quadra, sigla, distance = "Sem quadra", "Sem sigla", float('inf')
            else:
                quadra, sigla, distance = "Sem quadra", "Sem sigla", float('inf')
            if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
                sigla = "Desconhecida"
            ext = image_file.suffix
            new_filename = generate_new_filename(next_index, sigla, ext)
            new_path = directory / new_filename
            while new_path.exists():
                logging.warning(f" -> O arquivo {new_filename} já existe. Incrementando o índice.")
                next_index += 1
                new_filename = generate_new_filename(next_index, sigla, ext)
                new_path = directory / new_filename
            try:
                image_file.rename(new_path)
                logging.info(f" -> Renomeado para {new_filename}")
                renamed_files.append(new_filename)
                next_index += 1
            except OSError as os_err:
                logging.error(f"Erro ao renomear {image_file.name}: {os_err}")
        except Exception as e:
            logging.error(f"Erro ao processar {image_file.name}: {e}")
    return renamed_files

def process_images_with_progress(directory: Path, comments_dict=None, selected_images=None,
                                 report_date="", fiscal_name="", contract_number="",
                                 status_dict=None, progress_callback=None, disable_states=False):
    """
    Processa as imagens renomeadas e gera um relatório HTML incorporando miniaturas, data/hora, localização, status e comentários.
    """
    if status_dict is None:
        status_dict = {}
    geojson_data = load_geojson()
    if selected_images is not None:
        image_files = sorted([directory / f for f in selected_images if (directory / f).suffix.lower() in IMAGE_EXTENSIONS])
    else:
        image_files = sorted([f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS])
    if not image_files:
        logging.warning("Nenhuma imagem selecionada para processar.")
        return
    total = len(image_files)
    logging.info(f"Encontradas {total} imagens para processar em: {directory}")
    output_file = directory / "PYGeoDMA.html"
    try:
        with output_file.open("w", encoding="utf-8") as html_file:
            html_file.write("<html><head><meta charset='UTF-8'></head><body>")
            header_line1 = ("DAV - DIRETORIA DE ÁREAS VERDES / DMA - DIVISÃO DE MEIO AMBIENTE / PREFEITURA UNIVERSITÁRIA<br>"
                            "UNICAMP - UNIVERSIDADE ESTADUAL DE CAMPINAS")
            html_file.write(f"<p style='text-align: center; text-transform: uppercase; margin: 0;'>{header_line1}</p>")
            header_line2 = "RELATÓRIO DE VISTORIA - SERVIÇOS PROVAC"
            html_file.write(f"<p style='text-align: center; text-transform: uppercase; font-weight: bold; margin: 10px 0 20px 0;'>{header_line2}</p>")
            if report_date:
                html_file.write(f"<p style='text-align: center; margin: 0;'>Data do Relatório: {report_date}</p>")
            if contract_number:
                html_file.write(f"<p style='text-align: center; margin: 0;'>Contrato No: {contract_number}</p>")
            if fiscal_name:
                html_file.write(f"<p><strong>Nome do Fiscal:</strong> {fiscal_name}</p>")
            html_file.write("<ul style='list-style-type: none; padding: 0;'>")
            for idx, image_file in enumerate(image_files, start=1):
                if progress_callback:
                    progress_callback(idx, total)
                logging.info(f"Processando imagem: {image_file.name}...")
                try:
                    if not is_friendly_name(image_file.name):
                        logging.warning(f" -> O nome '{image_file.name}' não está no formato amigável.")
                    exif_data, img = get_exif_and_image(image_file)
                    gps_info = exif_data.get(34853) if exif_data else None
                    coordinates, gmaps_link = get_coordinates(gps_info)
                    date_time_str = extract_image_datetime(image_file)
                    if date_time_str:
                        try:
                            date_time_obj = datetime.strptime(date_time_str, "%Y-%m-%d_%H-%M-%S")
                            date_time_formatted = date_time_obj.strftime("%d/%m/%Y %H:%M:%S")
                        except ValueError:
                            date_time_formatted = "Data/Hora inválida"
                    else:
                        date_time_formatted = "Data/Hora desconhecida"
                    if coordinates != "Sem localização":
                        try:
                            lat, lon = map(float, coordinates.split(", "))
                            quadra, sigla, distance = find_nearest_geometry(geojson_data['features'], lat, lon)
                        except Exception as conv_err:
                            logging.error(f"Erro ao converter coordenadas: {conv_err}")
                            quadra, sigla, distance = "Sem quadra", "Sem sigla", float('inf')
                    else:
                        quadra, sigla, distance = "Sem quadra", "Sem sigla", float('inf')
                    if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
                        sigla = "Desconhecida"
                    base64_thumb, (thumb_width, thumb_height) = generate_thumbnail_base64(img)
                    html_file.write("<li style='margin-bottom:40px;'>")
                    html_file.write(
                        f"<a href='{image_file.name}' target='_blank'>"
                        f"<img src='data:image/jpeg;base64,{base64_thumb}' "
                        f"width='{thumb_width}' height='{thumb_height}' "
                        f"style='float:left; margin-right:20px; margin-bottom:10px;' "
                        f"alt='Thumbnail'>"
                        "</a>"
                    )
                    html_file.write("<hr style='border: 0; height: 1px; background-color: #cccccc; margin: 20px 0;'><br>")
                    title_number = image_file.stem.split(" - ")[0]
                    html_file.write(f"<strong>{title_number}</strong><br>")
                    html_file.write(f"<strong>Data e hora da imagem:</strong> {date_time_formatted}<br>")
                    if distance == 0:
                        html_file.write(f"<strong>Quadra:</strong> {quadra}, <strong>Sigla:</strong> {sigla}<br>")
                    else:
                        html_file.write(f"<strong>Próximo de:</strong> Quadra {quadra}, <strong>Sigla:</strong> {sigla}<br>")
                    html_file.write("<strong>Localização:</strong> ")
                    if gmaps_link != "Sem localização":
                        html_file.write(f'<a href="{gmaps_link}" target="_blank">{gmaps_link}</a>')
                    else:
                        html_file.write("Sem localização")

                    # Insere informações do status
                    default_status = "Não Concluído"
                    status = status_dict.get(image_file.name, default_status) if status_dict is not None else default_status
                    if not disable_states:
                        html_file.write(f"<br/><strong>Estado:</strong> {status}<br/>")
                    user_comment = comments_dict.get(image_file.name, "") if comments_dict else ""
                    if user_comment:
                        formatted_comment = user_comment.replace('\n', '<br/>')
                        html_file.write(f"<p><strong>Comentário:</strong> {formatted_comment}</p>")
                    html_file.write("<div style='clear:both;'></div>")
                    html_file.write("</li>")
                    logging.info(f" -> Processed {image_file.name}")
                except Exception as e:
                    logging.error(f"Erro ao processar {image_file.name}: {e}")
            html_file.write("</ul></body></html>")
            logging.info(f"Arquivo HTML gerado: {output_file}")
    except Exception as e:
        logging.critical(f"Falha ao gerar HTML: {e}")
        raise

# =============================================================================
# Função de Coleta de Dados para Relatórios (HTML e PDF)
# =============================================================================

def collect_entries(directory: Path, comments_dict: dict, status_dict: dict = {}, disable_states=False, selected_images=None):
    """
    Coleta os dados das imagens para geração de relatórios (HTML e PDF).

    Se 'selected_images' for fornecido (lista de nomes de arquivos), somente esses arquivos serão processados.
    """
    if selected_images is not None:
        # Usa os arquivos filtrados pela lista passada
        image_files = sorted([
            directory / f
            for f in selected_images
            if (directory / f).suffix.lower() in IMAGE_EXTENSIONS
        ])
    else:
        image_files = sorted([
            f for f in directory.iterdir()
            if f.suffix.lower() in IMAGE_EXTENSIONS
        ])
    
    entries = []
    geojson_data = load_geojson()
    
    for idx, image_file in enumerate(image_files, start=1):
        try:
            exif_data, img = get_exif_and_image(image_file)
            gps_info = exif_data.get(34853) if exif_data else None
            coordinates, gmaps_link = get_coordinates(gps_info)
            capture_datetime = extract_image_datetime(image_file)
            
            if capture_datetime:
                try:
                    dt_obj = datetime.strptime(capture_datetime, "%Y-%m-%d_%H-%M-%S")
                    date_time_formatted = dt_obj.strftime("%d/%m/%Y %H:%M:%S")
                except ValueError:
                    date_time_formatted = "Data/Hora inválida"
            else:
                date_time_formatted = "Data/Hora desconhecida"
            
            if coordinates != "Sem localização":
                try:
                    lat, lon = map(float, coordinates.split(", "))
                    quadra, sigla, distance = find_nearest_geometry(geojson_data['features'], lat, lon)
                except Exception as conv_err:
                    logging.error(f"Erro ao converter coordenadas: {conv_err}")
                    quadra, sigla, distance = "Sem quadra", "Sem sigla", float('inf')
            else:
                quadra, sigla, distance = "Sem quadra", "Sem sigla", float('inf')
            
            if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
                sigla = "Desconhecida"
            
            base64_thumb, _ = generate_thumbnail_base64(img)
            
            description = (
                f"<strong>{idx:03}</strong><br/>"
                f"<strong>Data e hora:</strong> {date_time_formatted}<br/>"
                f"<strong>Quadra:</strong> {quadra}, <strong>Sigla:</strong> {sigla}<br/>"
                f"<strong>Localização:</strong> <a href='{gmaps_link}' target='_blank'>{gmaps_link}</a><br/>"
            )
            
            default_status = "Não Concluído"
            status = status_dict.get(image_file.name, default_status)
            if not disable_states:
                description += f"<strong>Estado:</strong> {status}<br/>"
            else:
                status = ""
            
            comment = comments_dict.get(image_file.name, "")
            if comment:
                formatted_comment = comment.replace("\n", "<br/>")
                description += f"<u><b>Comentários</b></u><br/>{formatted_comment}<br/>"
            
            image_data = base64.b64decode(base64_thumb)
            entry = {'image': image_data, 'description': description, 'status': status}
            entries.append(entry)
        except Exception as e:
            logging.error(f"Erro ao coletar dados para {image_file.name}: {e}")
            continue
    return entries

# =============================================================================
# Função Principal
# =============================================================================

def main():
    """
    Função principal que realiza:
      - Renomeação das imagens,
      - Geração do relatório HTML,
      - Coleta dos dados e criação do relatório PDF.
    """
    directory = Path.cwd()
    
    logging.info("Renomeando imagens...")
    renamed = rename_images(directory)
    logging.info(f"Imagens renomeadas: {renamed}")
    
    # Define dados do relatório (estes valores podem ser alterados conforme necessário)
    report_date = datetime.now().strftime("%d/%m/%Y")
    contract_number = "Contrato Exemplo"
    
    # Gera o relatório HTML
    logging.info("Gerando relatório HTML...")
    # Para a versão de linha de comando, passamos dicionários vazios para comentários e status.
    process_images_with_progress(directory, comments_dict={}, report_date=report_date, contract_number=contract_number, status_dict={})
    
    # Coleta os dados para o PDF
    logging.info("Coletando dados para o PDF...")
    entries = collect_entries(directory, {}, {})  # Dicionários vazios para comentários e status
    
    pdf_path = directory / "Relatorio.pdf"
    from html_to_pdf import convert_data_to_pdf
    logging.info(f"Criando PDF em: {pdf_path}")
    try:
        convert_data_to_pdf(report_date, contract_number, entries, str(pdf_path), include_last_page=False)
        logging.info("PDF criado com sucesso.")
    except Exception as e:
        logging.error(f"Erro ao gerar PDF: {e}")

if __name__ == "__main__":
    main()
