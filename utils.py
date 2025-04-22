# utils.py

import os
import json
import re
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Tuple, Optional, List, Dict, Any
from shapely.geometry import Point, shape
from PIL import Image, ImageOps
from io import BytesIO
import base64
from req_classes.settingsClass import Settings  # Importa a classe de configuração
import random  # Importado para gerar nomes aleatórios



# -----------------------------------------------------------------------------
# Cache Global para Thumbnails
# -----------------------------------------------------------------------------
# Dicionário que armazena as miniaturas geradas para evitar regeneração desnecessária.

thumbnail_cache = {}



# -----------------------------------------------------------------------------
# Configuração do Logger
# -----------------------------------------------------------------------------
# Configura o logger para este módulo, definindo nível de log e handlers (arquivo e console)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler = logging.FileHandler("utils.log")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


def load_config() -> dict:
    """
    Carrega as configurações do sistema através da classe Settings.

    Retorna:
        dict: Dicionário contendo as configurações do sistema.
    """
    settings = Settings()
    return settings.config

def compute_image_hash(img: Image.Image, quality: int = 85) -> Optional[str]:
    """
    Calcula um hash MD5 da imagem após salvá-la em um buffer com qualidade reduzida.

    Args:
        img (Image.Image): Imagem a ser processada.
        quality (int, optional): Qualidade do JPEG. Default é 85.

    Returns:
        Optional[str]: Hash MD5 da imagem ou None em caso de erro.
    """
    buffer = BytesIO()
    try:
        # Salva a imagem em formato JPEG com a qualidade especificada
        img.save(buffer, format="JPEG", quality=quality)
    except Exception as e:
        logger.error(f"Erro ao salvar imagem para computar hash: {e}", exc_info=True)
        return None
    data = buffer.getvalue()
    return hashlib.md5(data).hexdigest()

def get_exif_and_image(image_file: Path) -> Tuple[Dict[Any, Any], Optional[Image.Image]]:
    """
    Abre a imagem, extrai os metadados EXIF e corrige a orientação.

    Parâmetros:
        image_file (Path): Caminho do arquivo de imagem.

    Retorna:
        Tuple[Dict[Any, Any], Optional[Image.Image]]:
            - dicionário com os metadados EXIF;
            - imagem corrigida (caso seja possível abri-la) ou None se ocorrer erro.
    """
    try:
        with Image.open(image_file) as img:
            # Obtém os metadados EXIF, se disponíveis
            exif_data = img._getexif() or {}
            # Corrige a orientação da imagem utilizando os metadados EXIF
            img_corrected = ImageOps.exif_transpose(img)
            # Retorna uma cópia da imagem para que ela permaneça após o fechamento do contexto
            return exif_data, img_corrected.copy()  # Usa copy para manter a imagem após o fechamento do contexto
    except Exception as e:
        logger.error(f"Erro ao abrir {image_file}: {e}", exc_info=True)
        return {}, None

def generate_thumbnail_base64(
    img: Image.Image,
    max_size: Tuple[int, int] = (600, 600),
    fmt: str = 'JPEG'
) -> Tuple[str, Tuple[int, int]]:
    """
    Gera uma miniatura da imagem e a converte para uma string codificada em Base64.

    Args:
        img (Image.Image): Imagem original.
        max_size (Tuple[int, int], optional): Tamanho máximo da miniatura. Default é (600, 600).
        fmt (str, optional): Formato da miniatura. Default é 'JPEG'.

    Returns:
        Tuple[str, Tuple[int, int]]:
            - String com a miniatura codificada em Base64;
            - Tamanho (largura, altura) da miniatura.
    """
    try:
        thumb = img.copy()
        # Redimensiona a imagem para o tamanho máximo definido
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
    Gera a miniatura para um arquivo de imagem e armazena o resultado no cache.
    Caso a miniatura já tenha sido gerada anteriormente, retorna-a diretamente do cache.

    Args:
        image_file (Path): Caminho do arquivo de imagem.
        max_size (Tuple[int, int], optional): Tamanho máximo da miniatura. Default é (600, 600).
        fmt (str, optional): Formato da miniatura. Default é 'JPEG'.

    Returns:
        Tuple[str, Tuple[int, int]]:
            - Miniatura em Base64;
            - Tamanho (largura, altura) da miniatura.
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

def sanitize_sigla(sigla: str) -> str:
    """
    Substitui caracteres inválidos para nomes de arquivos por hífens.

    Args:
        sigla (str): String original que poderá conter caracteres inválidos.

    Returns:
        str: Sigla "sanitizada" com caracteres inválidos substituídos por hífens.
    """
    invalid_chars = '<>:"/\\|?*'
    for c in invalid_chars:
        sigla = sigla.replace(c, '-')
    return sigla

def load_geojson() -> Dict[str, Any]:
    """
    Carrega o arquivo GeoJSON que contém as informações de quadras e áreas.

    Retorna:
        Dict[str, Any]: Dados carregados do arquivo GeoJSON.

    Em caso de erro, registra uma mensagem crítica e lança a exceção.
    """
    geojson_path = Path(__file__).parent / "map.geojson"
    try:
        with geojson_path.open('r', encoding='utf-8') as file:
            data = json.load(file)
        return data
    except Exception as e:
        logger.critical(f"Falha ao carregar GeoJSON: {e}", exc_info=True)
        raise

def get_coordinates(gps_info: Optional[Dict[Any, Any]]) -> Tuple[str, str]:
    """
    Converte as informações de GPS obtidas dos metadados EXIF em coordenadas decimais
    e gera um link para visualização no Google Maps.

    Args:
        gps_info (Optional[Dict[Any, Any]]): Dados GPS extraídos dos metadados EXIF.

    Returns:
        Tuple[str, str]:
            - String com as coordenadas no formato "lat, lon" ou "Sem localização";
            - Link do Google Maps ou "Sem localização" se não houver dados.
    """
    if not gps_info or not isinstance(gps_info, dict):
        return "Sem localização", "Sem localização"

    # Função auxiliar para converter valores racionais em float
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

    # Ajusta o sinal das coordenadas conforme os hemisférios indicados nos metadados
    if gps_info.get(1) == 'S':
        lat = -lat
    if gps_info.get(3) == 'W':
        lon = -lon

    gmaps_link = f"https://www.google.com/maps?q={lat},{lon}"
    coordinates_str = f"{lat}, {lon}"
    return coordinates_str, gmaps_link

def extract_image_datetime(image_path: Path) -> Optional[str]:
    """
    Extrai a data e hora da imagem utilizando os metadados EXIF. Se não encontrar,
    utiliza a data de modificação do arquivo.

    Args:
        image_path (Path): Caminho da imagem.

    Returns:
        Optional[str]: Data/hora no formato "YYYY-MM-DD_HH-MM-SS" ou None em caso de erro.
    """
    try:
        exif_data, _ = get_exif_and_image(image_path)
        if exif_data and isinstance(exif_data, dict):
            # Tenta as tags comuns que podem conter a data/hora
            for tag in [36867, 36868, 306]:
                if tag in exif_data:
                    date_str = exif_data[tag]
                    dt = datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                    return dt.strftime("%Y-%m-%d_%H-%M-%S")
    except Exception as e:
        logger.error(f"Erro ao extrair EXIF de {image_path}: {e}", exc_info=True)
    try:
        # Se não encontrar a data no EXIF, utiliza a data de modificação do arquivo
        timestamp = image_path.stat().st_mtime
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d_%H-%M-%S")
    except Exception as e:
        logger.error(f"Erro ao obter data de modificação de {image_path}: {e}", exc_info=True)
        return None

def find_nearest_geometry(features: List[Dict[str, Any]], lat: float, lon: float) -> Tuple[str, str, str, float]:
    """
    Dado um conjunto de features (polígonos do GeoJSON) e uma coordenada (lat, lon),
    retorna:
      - Tipo de área ("Quadra" ou "Canteiro"),
      - Identificador da área (valor da propriedade),
      - Sigla,
      - Distância até o polígono.

    Se o ponto estiver contido em um polígono, a distância retornada será 0.
    """
    point = Point(lon, lat)
    
    # Primeiro, verifica se o ponto está contido em algum polígono
    for feature in features:
        try:
            geom = shape(feature.get('geometry'))
            if geom.contains(point):
                props = feature.get('properties', {})
                if 'Quadra' in props and props['Quadra']:
                    tipo_area = "Quadra"
                    id_area   = str(props['Quadra'])
                elif 'Canteiro' in props and props['Canteiro']:
                    tipo_area = "Canteiro"
                    id_area   = str(props['Canteiro'])
                else:
                    tipo_area = "Desconhecida"
                    id_area = "Desconhecida"
                return tipo_area, id_area, props.get('Sigla', 'Desconhecida'), 0.0
        except Exception as e:
            logger.error(f"Erro ao verificar contenção na feature: {e}", exc_info=True)
    
    # Se o ponto não estiver contido, procura o polígono mais próximo
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

    Args:
        filename (str): Nome do arquivo.

    Returns:
        bool: True se o nome estiver no formato esperado, False caso contrário.
    """
    pattern = r"^\d{3}\s*-\s*.+\.\w+$"
    return re.match(pattern, filename) is not None

def generate_new_filename(index: int, sigla: str, ext: str) -> str:
    """
    Gera um novo nome de arquivo no formato "Índice - SIGLA.ext".

    Args:
        index (int): Número de ordem.
        sigla (str): Sigla que identifica a área.
        ext (str): Extensão do arquivo.

    Returns:
        str: Novo nome formatado.
    """
    sigla_sanitizada = sanitize_sigla(sigla)
    return f"{index:03} - {sigla_sanitizada}{ext}"

# -----------------------------------------------------------------------------
# Reutiliza a constante IMAGE_EXTENSIONS para verificação de extensões válidas
# -----------------------------------------------------------------------------
IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".heic"]

def rename_images(directory: Path, selected_images=None):
    """
    Renomeia os arquivos de imagem no diretório com base em informações dos metadados e do GeoJSON.
    
    Primeiro, renomeia todos os arquivos (com extensões válidas) para um nome aleatório de 8 dígitos.
    Depois, renomeia os arquivos para o formato "Índice - SIGLA.ext" usando os metadados EXIF e dados do GeoJSON.
    
    Retorna:
        List[str]: Lista dos nomes dos arquivos renomeados.
    """
    # Passo 1: Renomeação aleatória para evitar conflitos
    all_image_files = [f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS]
    for image_file in all_image_files:
        random_name = ''.join(random.choices("0123456789", k=8)) + image_file.suffix.lower()
        new_path = directory / random_name
        while new_path.exists():
            random_name = ''.join(random.choices("0123456789", k=8)) + image_file.suffix.lower()
            new_path = directory / random_name
        try:
            image_file.rename(new_path)
            logger.info(f"Arquivo {image_file.name} renomeado aleatoriamente para {new_path.name}")
        except Exception as e:
            logger.error(f"Erro ao renomear {image_file.name} para nome aleatório: {e}", exc_info=True)
    
    # Passo 2: Renomeação final com índice e sigla
    if selected_images is not None:
        image_files = sorted(
            [directory / f for f in selected_images if (directory / f).suffix.lower() in IMAGE_EXTENSIONS]
        )
    else:
        image_files = sorted(
            [f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS]
        )
    
    renamed_files = []
    items = []
    geojson_data = load_geojson()
    
    for image_file in image_files:
        logger.info(f"Processando imagem: {image_file.name}...")
        try:
            exif_data, _ = get_exif_and_image(image_file)
        except Exception as e:
            logger.error(f"Erro ao ler EXIF de {image_file.name}: {e}", exc_info=True)
            exif_data = {}
        
        gps_info = exif_data.get(34853) if exif_data else None
        coordinates, _ = get_coordinates(gps_info)
        if coordinates != "Sem localização":
            try:
                lat, lon = map(float, coordinates.split(", "))
                _, _, sigla, _ = find_nearest_geometry(geojson_data['features'], lat, lon)
            except Exception as conv_err:
                logger.error(f"Erro ao converter coordenadas de {image_file.name}: {conv_err}")
                sigla = "Desconhecida"
        else:
            sigla = "Desconhecida"
        
        if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
            sigla = "Desconhecida"
        
        date_str = extract_image_datetime(image_file)
        try:
            capture_dt = datetime.strptime(date_str, "%Y-%m-%d_%H-%M-%S") if date_str else datetime.max
        except Exception:
            capture_dt = datetime.max
        
        items.append((image_file, sigla, capture_dt))
    
    items.sort(key=lambda x: (x[1].upper(), x[2]))
    
    counter = 1
    for image_file, sigla, _ in items:
        new_filename = generate_new_filename(counter, sigla, image_file.suffix)
        new_path = directory / new_filename
        while new_path.exists():
            counter += 1
            new_filename = generate_new_filename(counter, sigla, image_file.suffix)
            new_path = directory / new_filename
        try:
            image_file.rename(new_path)
            logger.info(f" -> Renomeado {image_file.name} para {new_filename}")
            renamed_files.append(new_filename)
        except OSError as os_err:
            logger.error(f"Erro ao renomear {image_file.name}: {os_err}")
        counter += 1
    
    return renamed_files
