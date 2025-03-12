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
from req_classes.settingsClass import Settings

# Importa funções utilitárias compartilhadas para manipulação de configuração, imagens, geojson, etc.
from utils import (
    load_config,
    sanitize_sigla,
    load_geojson,
    get_exif_and_image,
    get_coordinates,
    extract_image_datetime,
    find_nearest_geometry,
    is_friendly_name,
    generate_new_filename,
    generate_thumbnail_from_file,
    compute_image_hash,
    rename_images
)

# =============================================================================
# Configuração do Logger
# =============================================================================
# Configura o logger para registrar informações de execução e erros neste módulo.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.hasHandlers():
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler = logging.FileHandler("main.log")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

# =============================================================================
# Constantes
# =============================================================================

# Lista de extensões de imagem suportadas pelo sistema.
IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".heic"]


# =============================================================================
# Função: generate_html_report
# =============================================================================

def generate_html_report(
    output_file: Path,
    config: dict,
    report_date: str,
    contract_number: str,
    fiscal_name: str,
    image_files: List[Path],
    comments_dict: Optional[Dict[str, str]] = None,
    status_dict: Optional[Dict[str, str]] = None,
    disable_states: bool = False,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> None:
    """
    Gera o relatório HTML a partir dos dados das imagens.

    Esta função cria um arquivo HTML contendo:
      - Cabeçalho com informações extraídas do arquivo de configuração;
      - Lista de imagens com seus respectivos thumbnails, dados extraídos (data, localização, área, sigla);
      - Status e comentários de cada imagem, quando disponíveis.
    
    Parâmetros:
      - output_file: Caminho para o arquivo HTML de saída.
      - config: Dicionário de configuração com textos e informações para o relatório.
      - report_date: Data do relatório.
      - contract_number: Número do contrato (não utilizado diretamente neste código, mas pode fazer parte do cabeçalho).
      - fiscal_name: Nome do fiscal (pode ser utilizado para exibição ou registros adicionais).
      - image_files: Lista de caminhos das imagens a serem processadas.
      - comments_dict: Dicionário opcional com comentários para cada imagem.
      - status_dict: Dicionário opcional com o status de cada imagem.
      - disable_states: Flag para desabilitar a exibição do estado de cada imagem.
      - progress_callback: Função opcional para atualizar o progresso do processamento.
    """
    # Carrega os dados do geojson, que serão utilizados para determinar a localização das imagens
    geojson_data = load_geojson()
    total = len(image_files)
    
    # Abre o arquivo de saída para escrita em modo UTF-8
    with output_file.open("w", encoding="utf-8") as html_file:
        # Escreve a estrutura básica do HTML e o cabeçalho
        html_file.write("<html><head><meta charset='UTF-8'></head><body>")
        # Cabeçalho: utiliza os valores de "header_1" e "header_2" definidos na configuração
        header_line1 = f"{config["header_1"]}<br>{config["header_2"]}"
        html_file.write(f"<p style='text-align: center; text-transform: uppercase; margin: 0;'>{header_line1}</p>")
        header_line2 = config["title"]
        html_file.write(f"<p style='text-align: center; text-transform: uppercase; font-weight: bold; margin: 10px 0 20px 0;'>{header_line2}</p>")

        html_file.write(f"<p style='text-align: center; margin: 0;'>{config["date_prefix"]} {report_date}</p>")
        html_file.write(f"<p style='text-align: center; margin: 0;'>{config["reference_number"]}</p>")
        html_file.write("<ul style='list-style-type: none; padding: 0;'>")
        
        # Processa cada imagem da lista
        for idx, image_file in enumerate(image_files, start=1):
            # Atualiza o progresso, se a função de callback foi fornecida
            if progress_callback:
                progress_callback(idx, total)
            logger.info(f"Processando imagem: {image_file.name}...")
            try:
                # Verifica se o nome do arquivo segue o padrão amigável
                if not is_friendly_name(image_file.name):
                    logger.warning(f" -> O nome '{image_file.name}' não está no formato amigável.")
                # Extrai os dados EXIF e a imagem propriamente dita
                exif_data, img = get_exif_and_image(image_file)
                gps_info = exif_data.get(34853) if exif_data else None
                # Obtém as coordenadas e o link do Google Maps a partir dos dados GPS
                coordinates, gmaps_link = get_coordinates(gps_info)
                # Extrai a data e hora em que a imagem foi capturada
                date_time_str = extract_image_datetime(image_file)
                if date_time_str:
                    try:
                        date_time_obj = datetime.strptime(date_time_str, "%Y-%m-%d_%H-%M-%S")
                        date_time_formatted = date_time_obj.strftime("%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        date_time_formatted = "Data/Hora inválida"
                else:
                    date_time_formatted = "Data/Hora desconhecida"
                # Determina a área mais próxima se houver coordenadas válidas
                if coordinates != "Sem localização":
                    try:
                        lat, lon = map(float, coordinates.split(", "))
                        tipo_area, id_area, sigla, distance = find_nearest_geometry(geojson_data['features'], lat, lon)
                    except Exception as conv_err:
                        logger.error(f"Erro ao converter coordenadas: {conv_err}", exc_info=True)
                        tipo_area, id_area, sigla, distance = "Sem área", "Sem área", "Desconhecida", float('inf')
                else:
                    tipo_area, id_area, sigla, distance = "Sem área", "Sem área", "Desconhecida", float('inf')

                # Se a sigla não for válida, define como "Desconhecida"
                if not sigla or sigla.lower() in ["sem sigla", "desconhecida"]:
                    sigla = "Desconhecida"
                # Gera a miniatura da imagem e obtém sua representação em base64
                base64_thumb, (thumb_width, thumb_height) = generate_thumbnail_from_file(image_file)
                # Escreve os dados da imagem no HTML, incluindo o link para a imagem e a miniatura
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
                # Extrai o número do título a partir do nome do arquivo (usando o primeiro segmento do nome)
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

                # Exibe o status da imagem, se a exibição não estiver desabilitada
                default_status = "Não Iniciado"
                status = status_dict.get(image_file.name, default_status) if status_dict is not None else default_status
                if not disable_states:
                    html_file.write(f"<br/><strong>Estado:</strong> {status}<br/>")
                # Exibe comentários de usuário, se houver
                user_comment = comments_dict.get(image_file.name, "") if comments_dict else ""
                if user_comment:
                    formatted_comment = user_comment.replace('\n', '<br/>')
                    html_file.write(f"<p><strong>Comentário:</strong> {formatted_comment}</p>")
                html_file.write("<div style='clear:both;'></div>")
                html_file.write("</li>")
                logger.info(f" -> Processed {image_file.name}")
            except Exception as e:
                logger.error(f"Erro ao processar {image_file.name}: {e}", exc_info=True)
        # Fecha a estrutura HTML
        html_file.write("</ul></body></html>")
        logger.info(f"Arquivo HTML gerado: {output_file}")

# =============================================================================
# Função: process_images_with_progress
# =============================================================================

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
    """
    Processa as imagens presentes no diretório e gera o relatório HTML, atualizando o progresso.

    Parâmetros:
      - directory: Caminho do diretório contendo as imagens.
      - comments_dict: Dicionário com comentários para cada imagem.
      - selected_images: Lista de nomes de arquivos a serem processados; se None, todas as imagens são processadas.
      - report_date: Data do relatório (formato "dd/mm/yyyy").
      - fiscal_name: Nome do fiscal (não utilizado diretamente neste código).
      - contract_number: Número do contrato.
      - status_dict: Dicionário com o status de cada imagem.
      - progress_callback: Função para atualizar o progresso (atual, total).
      - disable_states: Flag para desabilitar a exibição do status.
    """
    if status_dict is None:
        status_dict = {}
    
    # Carrega a configuração do sistema
    config = load_config()

    # Converte a data informada (dd/mm/yyyy) para yyMMdd
    try:
        dt = datetime.strptime(report_date, "%d/%m/%Y")
        date_slug = dt.strftime("%y%m%d")
    except ValueError:
        date_slug = datetime.now().strftime("%y%m%d")

    # Define o nome do arquivo HTML de saída
    output_file = directory / f"{date_slug}_Relatorio.html"
    
    # Filtra os arquivos de imagem a partir dos nomes selecionados, se fornecidos; caso contrário, processa todas
    if selected_images is not None:
        image_files = sorted([directory / f for f in selected_images if (directory / f).suffix.lower() in IMAGE_EXTENSIONS])
    else:
        image_files = sorted([f for f in directory.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS])
    if not image_files:
        logger.warning("Nenhuma imagem selecionada para processar.")
        return

    logger.info(f"Encontradas {len(image_files)} imagens para processar em: {directory}")
    
    # Chama a função que gera o relatório HTML com base nos dados processados
    generate_html_report(
        output_file,
        config,
        report_date,
        contract_number,
        fiscal_name,
        image_files,
        comments_dict,
        status_dict,
        disable_states,
        progress_callback
    )

# =============================================================================
# Função: collect_entries
# =============================================================================

def collect_entries(
    directory: Path, 
    comments_dict: Dict[str, str], 
    status_dict: Dict[str, str] = {}, 
    disable_states: bool = False, 
    selected_images: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Coleta e organiza os dados de cada imagem para a geração dos relatórios (HTML e PDF).

    Para cada imagem, extrai:
      - Dados EXIF e data/hora da captura.
      - Informações de localização e área, utilizando o geojson.
      - Miniatura da imagem.
      - Comentários e status (se disponíveis).
    
    Retorna:
      - Lista de dicionários, onde cada dicionário representa os dados de uma imagem.
    """
    if selected_images is not None:
        image_files = [
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
    # Carrega os dados do geojson para identificar áreas e siglas
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
            
            # Determina a área mais próxima a partir das coordenadas, se disponíveis
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
            
            # Gera a miniatura da imagem e obtém sua representação em base64
            base64_thumb, _ = generate_thumbnail_from_file(image_file)
            
            # Monta a descrição da imagem com os dados extraídos
            description = (
                f"<strong>{idx:03}</strong><br/>"
                f"<strong>Data e hora:</strong> {date_time_formatted}<br/>"
                f"<strong>{tipo_area}:</strong> {id_area}, <strong>Sigla:</strong> {sigla}<br/>"
                f"<strong>Localização:</strong> <a href='{gmaps_link}' target='_blank'>{gmaps_link}</a><br/>"
            )
            
            default_status = "Não Iniciado"
            status = status_dict.get(image_file.name, default_status)
            if not disable_states:
                description += f"<strong>Estado:</strong> {status}<br/>"
            else:
                status = ""
            
            comment = comments_dict.get(image_file.name, "")
            if comment:
                formatted_comment = comment.replace("\n", "<br/>")
                description += f"<u><b>Comentários</b></u><br/>{formatted_comment}<br/>"
            
            # Decodifica a miniatura de base64 para dados binários
            image_data = base64.b64decode(base64_thumb)
            entry = {
                'image': image_data,
                'description': description,
                'status': status,
                'tipo_area': tipo_area,
                'id_area': id_area,
                'sigla': sigla,
                'comment': comment
            }
            entries.append(entry)
        except Exception as e:
            logger.error(f"Erro ao coletar dados para {image_file.name}: {e}", exc_info=True)
            continue
    return entries

# =============================================================================
# Função: load_image_status_db
# =============================================================================

def load_image_status_db(directory: Path) -> Dict[str, str]:
    """
    Carrega o arquivo JSON (imagens_db.json) que contém o status das imagens e monta
    um dicionário mapeando o nome do arquivo para o status salvo.

    Retorna:
      - Dicionário com a chave sendo o nome do arquivo e o valor o status da imagem.
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
                            status_dict[file.name] = db[image_hash].get("status", "Não Iniciado")
        except Exception as e:
            logger.error(f"Erro ao carregar o banco de dados: {e}", exc_info=True)
    return status_dict

# =============================================================================
# Função Principal: main
# =============================================================================

def main() -> None:
    """
    Função principal que realiza as seguintes etapas:
      1. Renomeia as imagens presentes no diretório atual.
      2. Gera o relatório HTML a partir das imagens processadas.
      3. Coleta os dados necessários de cada imagem para a geração do relatório PDF.
      4. Cria o relatório PDF utilizando os dados coletados.

    Em caso de erros, registra as exceções no log.
    """
    # Define o diretório atual como ponto de partida
    directory = Path.cwd()
    
    logger.info("Renomeando imagens...")
    # Renomeia as imagens conforme a lógica implementada na função 'rename_images'
    renamed = rename_images(directory)
    logger.info(f"Imagens renomeadas: {renamed}")
    
    # Carrega a configuração do sistema
    config = load_config()
    
    # Define a data do relatório com a data atual (formato dd/mm/yyyy)
    report_date = datetime.now().strftime("%d/%m/%Y")

    # Obtém o número do contrato a partir da configuração
    contract_number = config.get("reference_number", "Contrato Exemplo")
    
    # Carrega os status salvos das imagens, se houver, a partir do banco de dados JSON
    status_dict = load_image_status_db(directory)
    
    logger.info("Gerando relatório HTML...")
    # Processa as imagens e gera o relatório HTML
    process_images_with_progress(
        directory,
        comments_dict={},
        report_date=report_date,
        contract_number=contract_number,
        status_dict=status_dict
    )
    
    logger.info("Coletando dados para o PDF...")
    # Coleta os dados de cada imagem para a criação do relatório PDF
    entries = collect_entries(directory, {}, status_dict)
    
    # Define o caminho para o PDF que será gerado
    pdf_path = directory / "Relatorio.pdf"
    # Importa a função de conversão de dados para PDF localmente para evitar dependências cíclicas
    from req_classes.pdf_tools import convert_data_to_pdf  
    logger.info(f"Criando PDF em: {pdf_path}")
    try:
        # Cria o PDF utilizando os dados coletados
        convert_data_to_pdf(report_date, contract_number, entries, str(pdf_path), include_last_page=False)
        logger.info("PDF criado com sucesso.")
    except Exception as e:
        logger.error(f"Erro ao gerar PDF: {e}", exc_info=True)

# =============================================================================
# Execução do Script
# =============================================================================

if __name__ == "__main__":
    main()
