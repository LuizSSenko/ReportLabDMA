# main.py
import os
import json
import re
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, List, Dict, Callable, Any
from shapely.geometry import Point, shape
from PIL import Image, ImageOps
from io import BytesIO
import base64

# Dicionário global para armazenar as thumbnails geradas
thumbnail_cache = {}

# Configuração do logger para este módulo
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# Desabilita a propagação para evitar que os logs sejam também tratados pelo logger pai
logger.propagate = False

if not logger.hasHandlers():
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler = logging.FileHandler("main.log")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

# Constantes
IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".heic"]

def load_config() -> dict:
    """
    Carrega o arquivo JSON de configuração com os textos para o HTML e PDF.
    Se ocorrer algum erro, retorna um dicionário com valores padrão.
    """
    config_path = Path(__file__).parent / "pdf_config_default.json"
    try:
        with config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)
        logger.info(f"Configuração carregada com sucesso de {config_path}")
        return config
    except Exception as e:
        logger.error(f"Erro ao carregar a configuração: {e}", exc_info=True)
        # Valores padrão caso o arquivo não seja encontrado ou ocorra erro
        return {
            "header_1": "DAV - DIRETORIA DE ÁREAS VERDES / DMA - DIVISÃO DE MEIO AMBIENTE",
            "header_2": "UNICAMP - UNIVERSIDADE ESTADUAL DE CAMPINAS",
            "title": "RELATÓRIO DE VISTORIA - SERVIÇOS PROVAC",
            "date_prefix": "DATA DO RELATÓRIO:",
            "reference_number": "CONTRATO Nº: Contrato Exemplo",
            "description": "Vistoria de campo realizada pelos técnicos da DAV/DMA,",
            "address": "Rua 5 de Junho, 251 - Cidade Universitária Zeferino Vaz - Campinas - SP",
            "postal_code": "CEP: 13083-877",
            "contact_phone": "Tel: (19) 3521-7010",
            "contact_fax": "Fax: (19) 3521-7835",
            "contact_email": "mascerct@unicamp.br"
        }

def sanitize_sigla(sigla: str) -> str:
    """
    Substitui caracteres inválidos para nomes de arquivos por hífens.
    """
    invalid_chars = '<>:"/\\|?*'
    for c in invalid_chars:
        sigla = sigla.replace(c, '-')
    return sigla

def load_geojson() -> Dict[str, Any]:
    """
    Carrega o arquivo GeoJSON contendo as informações de quadras.
    """
    geojson_path = Path(__file__).parent / "map.geojson"
    try:
        with geojson_path.open('r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except Exception as e:
        logger.critical(f"Falha ao carregar GeoJSON: {e}", exc_info=True)
        raise

def get_exif_and_image(image_file: Path) -> Tuple[Dict[Any, Any], Optional[Image.Image]]:
    """
    Abre a imagem, extrai os metadados EXIF e corrige a orientação.
    """
    try:
        with Image.open(image_file) as img:
            exif_data = img._getexif() or {}
            # Corrige a orientação utilizando os metadados EXIF
            img_corrected = ImageOps.exif_transpose(img)
            return exif_data, img_corrected.copy()  # Usa copy para manter a imagem após o fechamento do contexto
    except Exception as e:
        logger.error(f"Erro ao abrir {image_file}: {e}", exc_info=True)
        return {}, None

def get_coordinates(gps_info: Optional[Dict[Any, Any]]) -> Tuple[str, str]:
    """
    Converte as informações de GPS do EXIF em coordenadas decimais e gera o link do Google Maps.
    """
    if not gps_info or not isinstance(gps_info, dict):
        return "Sem localização", "Sem localização"

    def convert_to_degrees(value: Any) -> Optional[float]:
        try:
            def rational_to_float(rational: Any) -> float:
                if isinstance(rational, tuple):
                    return float(rational[0]) / float(rational[1])
                return float(rational)
            d = rational_to_float(value[0])
            m = rational_to_float(value[1])
            s = rational_to_float(value[2])
            return d + (m / 60.0) + (s / 3600.0)
        except Exception as e:
            logger.error(f"Erro na conversão de coordenadas: {e}", exc_info=True)
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

def extract_image_datetime(image_path: Path) -> Optional[str]:
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
        logger.error(f"Erro ao extrair EXIF de {image_path}: {e}", exc_info=True)
    try:
        timestamp = image_path.stat().st_mtime
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d_%H-%M-%S")
    except Exception as e:
        logger.error(f"Erro ao obter data de modificação de {image_path}: {e}", exc_info=True)
        return None

def find_nearest_geometry(features: List[Dict[str, Any]], lat: float, lon: float) -> Tuple[str, str, str, float]:
    """
    Retorna o tipo de área ("Quadra" ou "Canteiro"), o identificador dessa área (valor da propriedade),
    a sigla e a distância até o polígono. Se o ponto estiver contido em um polígono, a distância é 0.
    """
    point = Point(lon, lat)
    
    # Primeiro, verifica se o ponto está dentro de algum polígono.
    for feature in features:
        try:
            geom = shape(feature.get('geometry'))
            if geom.contains(point):
                props = feature.get('properties', {})
                if 'Quadra' in props and props['Quadra']:
                    tipo_area = "Quadra"
                    id_area = props['Quadra']
                elif 'Canteiro' in props and props['Canteiro']:
                    tipo_area = "Canteiro"
                    id_area = props['Canteiro']
                else:
                    tipo_area = "Desconhecida"
                    id_area = "Desconhecida"
                return tipo_area, id_area, props.get('Sigla', 'Desconhecida'), 0.0
        except Exception as e:
            logger.error(f"Erro ao verificar contenção na feature: {e}", exc_info=True)
    
    # Se o ponto não estiver dentro de nenhum polígono, procura o polígono mais próximo.
    min_distance = float('inf')
    nearest_tipo = "Desconhecida"
    nearest_id = "Desconhecida"
    nearest_sigla = "Desconhecida"
    for feature in features:
        try:
            geom = shape(feature.get('geometry'))
            distance = point.distance(geom)
            if distance < min_distance:
                min_distance = distance
                props = feature.get('properties', {})
                if 'Quadra' in props and props['Quadra']:
                    nearest_tipo = "Quadra"
                    nearest_id = props['Quadra']
                elif 'Canteiro' in props and props['Canteiro']:
                    nearest_tipo = "Canteiro"
                    nearest_id = props['Canteiro']
                else:
                    nearest_tipo = "Desconhecida"
                    nearest_id = "Desconhecida"
                nearest_sigla = props.get('Sigla', 'Desconhecida')
        except Exception as e:
            logger.error(f"Erro ao processar feature para distância: {e}", exc_info=True)
    
    return nearest_tipo, nearest_id, nearest_sigla, min_distance



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

def generate_thumbnail_base64(
    img: Image.Image,
    max_size: Tuple[int, int] = (600, 600),
    fmt: str = 'JPEG'
) -> Tuple[str, Tuple[int, int]]:
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
        logger.error(f"Erro ao gerar thumbnail: {e}", exc_info=True)
        return "", (0, 0)

def generate_thumbnail_from_file(
    image_file: Path,
    max_size: Tuple[int, int] = (600, 600),
    fmt: str = 'JPEG'
) -> Tuple[str, Tuple[int, int]]:
    """
    Gera a thumbnail para um arquivo de imagem e armazena no cache.
    Se a thumbnail já foi gerada, ela é retornada diretamente do cache.
    """
    key = str(image_file.resolve())
    if key in thumbnail_cache:
        return thumbnail_cache[key]

    exif_data, img = get_exif_and_image(image_file)
    if img is None:
        return "", (0, 0)
    
    base64_thumb, thumb_size = generate_thumbnail_base64(img, max_size, fmt)
    thumbnail_cache[key] = (base64_thumb, thumb_size)
    return (base64_thumb, thumb_size)

def rename_images(directory: Path, selected_images=None):
    """
    Renomeia os arquivos de imagem no diretório utilizando informações do EXIF e GeoJSON,
    agrupando-os por sigla e, dentro de cada grupo, ordenando-os em ordem crescente de data/hora.
    Se o arquivo já possui um nome amigável (ex: "001 - Descrição.ext"), ele não é renomeado.
    """
    geojson_data = load_geojson()
    
    # Obtém a lista de arquivos de imagem
    if selected_images is not None:
        image_files = sorted(
            [directory / f for f in selected_images if (directory / f).suffix.lower() in IMAGE_EXTENSIONS]
        )
    else:
        image_files = sorted(
            [f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS]
        )
    
    renamed_files = []
    
    # Separa os arquivos que já estão com nome amigável e os que precisam ser renomeados
    friendly_files = [f for f in image_files if is_friendly_name(f.name)]
    non_friendly_files = [f for f in image_files if not is_friendly_name(f.name)]
    
    # Para os arquivos com nome amigável, apenas os adicionamos à lista final
    for f in friendly_files:
        logging.info(f"Processando imagem: {f.name}...")
        logging.info(f" -> Já está no formato amigável: {f.name}")
        renamed_files.append(f.name)
    
    # Cria uma lista de tuplas (arquivo, sigla, data/hora) para os arquivos que serão renomeados
    items = []
    for image_file in non_friendly_files:
        logging.info(f"Processando imagem: {image_file.name}...")
        try:
            exif_data, _ = get_exif_and_image(image_file)
        except Exception as e:
            logging.error(f"Erro ao ler EXIF de {image_file.name}: {e}", exc_info=True)
            exif_data = {}
        
        gps_info = exif_data.get(34853) if exif_data else None
        coordinates, _ = get_coordinates(gps_info)
        if coordinates != "Sem localização":
            try:
                lat, lon = map(float, coordinates.split(", "))
                # Busca a quadra e sigla mais próxima
                _, _, sigla, _ = find_nearest_geometry(geojson_data['features'], lat, lon)
            except Exception as conv_err:
                logging.error(f"Erro ao converter coordenadas de {image_file.name}: {conv_err}")
                sigla = "Desconhecida"
        else:
            sigla = "Desconhecida"
        
        if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
            sigla = "Desconhecida"
        
        # Extrai a data/hora da imagem; se não conseguir, usa um valor alto para ordená-la por último
        date_str = extract_image_datetime(image_file)
        try:
            capture_dt = datetime.strptime(date_str, "%Y-%m-%d_%H-%M-%S") if date_str else datetime.max
        except Exception:
            capture_dt = datetime.max

        items.append((image_file, sigla, capture_dt))
    
    # Ordena os itens pela sigla (para agrupar) e, dentro de cada grupo, pela data/hora (em ordem crescente)
    items.sort(key=lambda x: (x[1].upper(), x[2]))
    
    # Utiliza um contador separado para cada sigla
    sigla_counters = {}
    for image_file, sigla, _ in items:
        if sigla not in sigla_counters:
            sigla_counters[sigla] = 1
        else:
            sigla_counters[sigla] += 1
        new_index = sigla_counters[sigla]
        new_filename = generate_new_filename(new_index, sigla, image_file.suffix)
        new_path = directory / new_filename
        
        # Evita conflitos de nomes, incrementando o contador se necessário
        while new_path.exists():
            sigla_counters[sigla] += 1
            new_index = sigla_counters[sigla]
            new_filename = generate_new_filename(new_index, sigla, image_file.suffix)
            new_path = directory / new_filename
        
        try:
            image_file.rename(new_path)
            logging.info(f" -> Renomeado {image_file.name} para {new_filename}")
            renamed_files.append(new_filename)
        except OSError as os_err:
            logging.error(f"Erro ao renomear {image_file.name}: {os_err}")
    
    return renamed_files




def process_images_with_progress(
    directory: Path, 
    comments_dict: Optional[Dict[str, str]] = None, 
    selected_images: Optional[List[str]] = None,
    report_date: str = "", 
    fiscal_name: str = "", 
    contract_number: str = "",
    status_dict: Optional[Dict[str, str]] = None, 
    progress_callback: Optional[Callable[[int, int], None]] = None, 
    disable_states: bool = False
) -> None:
    if status_dict is None:
        status_dict = {}
    
    # Carrega a configuração para os textos
    config = load_config()

    # Converte a data informada (dd/mm/yyyy) para yyMMdd
    try:
        dt = datetime.strptime(report_date, "%d/%m/%Y")
        date_slug = dt.strftime("%y%m%d")
    except ValueError:
        # Se a data for inválida ou vazia, cai no fallback (data do sistema)
        date_slug = datetime.now().strftime("%y%m%d")

    # Ajusta o nome do HTML usando a data do usuário
    output_file = directory / f"{date_slug}_Relatorio.html"
    
    geojson_data = load_geojson()
    if selected_images is not None:
        image_files = sorted([directory / f for f in selected_images if (directory / f).suffix.lower() in IMAGE_EXTENSIONS])
    else:
        image_files = sorted([f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS])
    if not image_files:
        logger.warning("Nenhuma imagem selecionada para processar.")
        return
    total = len(image_files)
    logger.info(f"Encontradas {total} imagens para processar em: {directory}")
    try:
        with output_file.open("w", encoding="utf-8") as html_file:
            html_file.write("<html><head><meta charset='UTF-8'></head><body>")
            # Utiliza os valores do JSON para os cabeçalhos
            header_line1 = f"{config.get('header_1', '')}<br>{config.get('header_2', '')}"
            html_file.write(f"<p style='text-align: center; text-transform: uppercase; margin: 0;'>{header_line1}</p>")
            header_line2 = config.get("title", "RELATÓRIO DE VISTORIA - SERVIÇOS PROVAC")
            html_file.write(f"<p style='text-align: center; text-transform: uppercase; font-weight: bold; margin: 10px 0 20px 0;'>{header_line2}</p>")
            if report_date:
                html_file.write(f"<p style='text-align: center; margin: 0;'>{config.get('date_prefix', 'DATA DO RELATÓRIO:')} {report_date}</p>")
            if contract_number:
                html_file.write(f"<p style='text-align: center; margin: 0;'>{config.get('reference_number', contract_number)}</p>")
            if fiscal_name:
                html_file.write(f"<p><strong>Nome do Fiscal:</strong> {fiscal_name}</p>")
            html_file.write("<ul style='list-style-type: none; padding: 0;'>")
            for idx, image_file in enumerate(image_files, start=1):
                if progress_callback:
                    progress_callback(idx, total)
                logger.info(f"Processando imagem: {image_file.name}...")
                try:
                    if not is_friendly_name(image_file.name):
                        logger.warning(f" -> O nome '{image_file.name}' não está no formato amigável.")
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
                            tipo_area, id_area, sigla, distance = find_nearest_geometry(geojson_data['features'], lat, lon)
                        except Exception as conv_err:
                            logger.error(f"Erro ao converter coordenadas: {conv_err}", exc_info=True)
                            tipo_area, id_area, sigla, distance = "Sem área", "Sem área", "Desconhecida", float('inf')
                    else:
                        tipo_area, id_area, sigla, distance = "Sem área", "Sem área", "Desconhecida", float('inf')

                    if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
                        sigla = "Desconhecida"
                    base64_thumb, (thumb_width, thumb_height) = generate_thumbnail_from_file(image_file)
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
                        html_file.write(f"<strong>{tipo_area}:</strong> {id_area}, <strong>Sigla:</strong> {sigla}<br>")
                    else:
                        html_file.write(f"<strong>Próximo de:</strong> {tipo_area} {id_area}, <strong>Sigla:</strong> {sigla}<br>")

                    html_file.write("<strong>Localização:</strong> ")
                    if gmaps_link != "Sem localização":
                        html_file.write(f'<a href="{gmaps_link}" target="_blank">{gmaps_link}</a>')
                    else:
                        html_file.write("Sem localização")
    
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
                    logger.info(f" -> Processed {image_file.name}")
                except Exception as e:
                    logger.error(f"Erro ao processar {image_file.name}: {e}", exc_info=True)
            html_file.write("</ul></body></html>")
            logger.info(f"Arquivo HTML gerado: {output_file}")
    except Exception as e:
        logger.critical(f"Falha ao gerar HTML: {e}", exc_info=True)
        raise

def collect_entries(
    directory: Path, 
    comments_dict: Dict[str, str], 
    status_dict: Dict[str, str] = {}, 
    disable_states: bool = False, 
    selected_images: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Coleta os dados necessários de cada imagem para a geração de relatórios (HTML e PDF).

    Observações importantes:
    - Se 'selected_images' for fornecida, ela contém a ordem definida pelo usuário na interface.
      Por esse motivo, NÃO aplicamos 'sorted()' nessa lista, de modo que a ordem personalizada seja mantida.
    - Se 'selected_images' não for fornecida, a função coleta todos os arquivos de imagem no diretório
      (filtrando pelas extensões suportadas) e os ordena (com sorted()) para garantir uma ordem consistente.
    
    Para cada imagem, a função realiza os seguintes passos:
      1. Extrai os dados EXIF e a imagem (usando get_exif_and_image).
      2. Obtém informações de localização (GPS) e gera um link do Google Maps, além de determinar a área mais próxima
         a partir de um arquivo GeoJSON.
      3. Extrai a data e hora de captura da imagem, formatando-a para exibição.
      4. Gera uma miniatura da imagem (em base64) e a decodifica para os dados binários.
      5. Constrói uma string 'description' com informações como data/hora, área, sigla, link de localização,
         status (quando não se tem 'disable_states') e comentários (se existirem).
      6. Cria um dicionário (entry) com os dados extraídos: imagem, descrição, status, área, sigla e comentários.
    
    Em caso de erro durante o processamento de uma imagem, o erro é logado e a imagem é ignorada.

    Retorna:
      Uma lista de dicionários, onde cada dicionário contém os dados necessários para a geração do relatório.
    """
    if selected_images is not None:
        image_files =[
            directory / f
            for f in selected_images
            if (directory / f).suffix.lower() in IMAGE_EXTENSIONS
        ]
    else:
        image_files = sorted([
            f for f in directory.iterdir()
            if f.suffix.lower() in IMAGE_EXTENSIONS
        ])
    
    entries: List[Dict[str, Any]] = []
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
                    tipo_area, id_area, sigla, distance = find_nearest_geometry(geojson_data['features'], lat, lon)
                except Exception as conv_err:
                    logger.error(f"Erro ao converter coordenadas: {conv_err}", exc_info=True)
                    tipo_area, id_area, sigla, distance = "Sem área", "Sem área", "Desconhecida", float('inf')
            else:
                tipo_area, id_area, sigla, distance = "Sem área", "Sem área", "Desconhecida", float('inf')
            
            if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
                sigla = "Desconhecida"
            
            base64_thumb, _ = generate_thumbnail_from_file(image_file)

            
            description = (
                f"<strong>{idx:03}</strong><br/>"
                f"<strong>Data e hora:</strong> {date_time_formatted}<br/>"
                f"<strong>{tipo_area}:</strong> {id_area}, <strong>Sigla:</strong> {sigla}<br/>"
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
            entry = {
                'image': image_data,
                'description': description,
                'status': status,
                'tipo_area': tipo_area,
                'id_area': id_area,
                'sigla': sigla,
                'comment': comment  # novo campo para facilitar a agregação
            }
            entries.append(entry)
        except Exception as e:
            logger.error(f"Erro ao coletar dados para {image_file.name}: {e}", exc_info=True)
            continue
    return entries

def compute_image_hash(img: Image.Image, quality: int = 85) -> Optional[str]:
    """
    Calcula um hash MD5 da imagem após salvá-la num buffer com qualidade reduzida.
    """
    buffer = BytesIO()
    try:
        img.save(buffer, format="JPEG", quality=quality)
    except Exception as e:
        logger.error(f"Erro ao salvar imagem para computar hash: {e}", exc_info=True)
        return None
    data = buffer.getvalue()
    return hashlib.md5(data).hexdigest()

def load_image_status_db(directory: Path) -> Dict[str, str]:
    """
    Carrega o arquivo JSON de banco de dados (imagens_db.json) e monta um dicionário
    mapeando o nome do arquivo para o status salvo.
    """
    db_path = directory / "imagens_db.json"
    status_dict = {}
    if db_path.exists():
        try:
            with db_path.open("r", encoding="utf-8") as f:
                db = json.load(f)
            for file in directory.iterdir():
                if file.suffix.lower() in IMAGE_EXTENSIONS:
                    exif_data, img = get_exif_and_image(file)
                    if img:
                        image_hash = compute_image_hash(img)
                        if image_hash and image_hash in db:
                            status_dict[file.name] = db[image_hash].get("status", "Não Concluído")
        except Exception as e:
            logger.error(f"Erro ao carregar o banco de dados: {e}", exc_info=True)
    return status_dict

def main() -> None:
    """
    Função principal que realiza:
      - Renomeação das imagens,
      - Geração do relatório HTML,
      - Coleta dos dados e criação do relatório PDF.
    """
    directory = Path.cwd()
    
    logger.info("Renomeando imagens...")
    renamed = rename_images(directory)
    logger.info(f"Imagens renomeadas: {renamed}")
    
    # Carrega a configuração para obter os textos
    config = load_config()
    
    # Define os dados do relatório
    report_date = datetime.now().strftime("%d/%m/%Y")
    contract_number = config.get("reference_number", "Contrato Exemplo")
    
    # Carrega o dicionário de status a partir do banco de dados (imagens_db.json)
    status_dict = load_image_status_db(directory)
    
    # Gera o relatório HTML
    logger.info("Gerando relatório HTML...")
    process_images_with_progress(
        directory,
        comments_dict={},
        report_date=report_date,
        contract_number=contract_number,
        status_dict=status_dict
    )
    
    # Coleta os dados para o PDF
    logger.info("Coletando dados para o PDF...")
    entries = collect_entries(directory, {}, status_dict)
    
    pdf_path = directory / "Relatorio.pdf"
    from pdf_tools import convert_data_to_pdf  # Import local para evitar dependência cíclica
    logger.info(f"Criando PDF em: {pdf_path}")
    try:
        convert_data_to_pdf(report_date, contract_number, entries, str(pdf_path), include_last_page=False)
        logger.info("PDF criado com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao gerar PDF: {e}", exc_info=True)

if __name__ == "__main__":
    main()
