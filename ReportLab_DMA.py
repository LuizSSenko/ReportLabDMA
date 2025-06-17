# ReportLab_DMA.py, GUI para processamento de imagens e geração de PDFs.
import sys
import os
import logging
import traceback
from pathlib import Path
from datetime import datetime
import io
import base64
import functools
import json
import hashlib
from io import BytesIO
from typing import Optional, List, Dict
import re

# Importação dos componentes do PyQt5 para a criação da interface gráfica
from PyQt5.QtWidgets import (
    QApplication, QWizard, QWizardPage, QLabel, QLineEdit, QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QListWidget, QDialog,
    QListWidgetItem, QTextEdit, QProgressDialog, QMessageBox, QCheckBox,
    QRadioButton, QButtonGroup, QSizePolicy, QGraphicsOpacityEffect, QSplitter
)
from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal, QObject, pyqtSlot, QRunnable, QTimer, QEvent, QEventLoop
from PyQt5.QtGui import QPixmap

# Importação das funções de manipulação de imagem da biblioteca PIL (Pillow)
from PIL import Image, ExifTags, ImageOps

# Importa funções do módulo principal para processamento de imagens
from main import (
    process_images_with_progress,
    collect_entries,
)
# Importa funções utilitárias do módulo utils
from utils import (
    get_exif_and_image,
    generate_thumbnail_from_file,
    compute_image_hash,
    rename_images,
    load_config, load_geojson
)

# Importa funções para conversão de dados em PDF e editor de configurações
from req_classes.pdf_tools import convert_data_to_pdf
from req_classes.configEditor import ConfigEditorDialog
from req_classes.questionario_poda import QuestionarioPodaDialog
from req_classes.PintaQuadra import MapColoringApp

# =============================================================================
# Configuração do logger para este módulo
# =============================================================================
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    # Define o formato de log com timestamp, nível e mensagem
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # Cria um handler para gravar os logs em um arquivo
    file_handler = logging.FileHandler("gui_app.log")
    file_handler.setFormatter(formatter)

    # Cria um handler para exibir os logs no console
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

# =============================================================================
# Constantes
# =============================================================================
# Lista das extensões de imagem suportadas pelo aplicativo
SUPPORTED_IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".heic"]

# =============================================================================
# Seção: Workers e Sinais para Processamento em Segundo Plano
# =============================================================================

class WorkerSignals(QObject):
    """
    Classe que define os sinais (signals) usados para comunicação entre as threads (workers)
    e a interface do usuário.
    """
    finished = pyqtSignal()              # Sinal emitido quando a tarefa termina
    error = pyqtSignal(tuple)            # Sinal emitido em caso de erro (envia uma tupla com detalhes)
    result = pyqtSignal(object)          # Sinal para retornar o resultado da tarefa
    progress = pyqtSignal(int, int)      # Sinal para atualização de progresso (atual, total)


class LoadImagesRunnable(QRunnable):
    """
    Worker para carregar e pré-processar as imagens do diretório.
    Realiza a leitura dos arquivos, extração dos metadados (EXIF) e cálculo do hash.
    """
    def __init__(self, directory: Path, supported_extensions: List[str]) -> None:
        super().__init__()
        self.directory = directory                          # Diretório de imagens
        self.supported_extensions = supported_extensions    # Extensões permitidas
        self.signals = WorkerSignals()                      # Instância dos sinais para comunicação
        self.image_data_list = []                           # Lista que armazenará os dados de cada imagem

    @pyqtSlot()
    def run(self) -> None:
        """
        Método executado em segundo plano para processar as imagens.
        Percorre os arquivos do diretório e processa cada imagem individualmente.
        """
        try:
            # Lista e ordena os arquivos que possuem as extensões suportadas
            image_files = sorted([f for f in self.directory.iterdir() if f.suffix.lower() in self.supported_extensions])
            total = len(image_files)
            results = []
            for idx, image_file in enumerate(image_files, start=1):
                # Cria uma instância de ImageData para armazenar os dados da imagem
                image_data = ImageData(image_file)
                try:
                    # Tenta obter os metadados EXIF e a imagem
                    _, img = get_exif_and_image(image_file)
                    if img:
                        # Calcula o hash da imagem para identificação única
                        image_hash = compute_image_hash(img)
                        image_data.hash = image_hash
                    else:
                        image_data.hash = None
                except Exception as e:
                    logger.error(f"Erro ao computar hash para {image_file.name}: {e}", exc_info=True)
                    image_data.hash = None
                results.append(image_data)
                # Atualiza o progresso a cada imagem processada
                self.signals.progress.emit(idx, total)
            self.image_data_list = results
            # Emite o sinal com o resultado final (lista de ImageData)
            self.signals.result.emit(results)
            self.signals.finished.emit()
        except Exception as e:
            # Emite o sinal de erro caso ocorra alguma exceção
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))


class ProcessImagesRunnable(QRunnable):
    """
    Worker para processar as imagens em segundo plano.
    Executa a função de processamento das imagens com a atualização do progresso.
    """
    def __init__(self, directory: Path, comments_dict: dict, selected_images: list,
                 report_date: str, contract_number: str, status_dict: dict, disable_states: bool) -> None:
        super().__init__()
        self.directory = directory
        self.comments_dict = comments_dict
        self.selected_images = selected_images
        self.report_date = report_date
        self.contract_number = contract_number
        self.status_dict = status_dict          # Dicionário com o status de cada imagem
        self.disable_states = disable_states    # Flag para desabilitar estados, se necessário
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        """
        Método executado em segundo plano que chama a função principal de processamento de imagens.
        """
        try:
            process_images_with_progress(
                self.directory,
                comments_dict=self.comments_dict,
                selected_images=self.selected_images,
                report_date=self.report_date,
                contract_number=self.contract_number,
                status_dict=self.status_dict,                   # Passa o dicionário de status
                progress_callback=self.signals.progress.emit,
                disable_states=self.disable_states
            )
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))


class PDFGenerationRunnable(QRunnable):
    """
    Worker para geração do PDF em segundo plano.
    Reúne os dados processados e chama a função de conversão para PDF.
    """
    def __init__(self, directory: Path, report_date: str, contract_number: str,
                pdf_path: Path, include_last_page: bool, comments_dict: dict,
                status_dict: dict, disable_states: bool, selected_images: list, 
                general_comments: str, questionario_respostas: dict, disable_comments_table: bool) -> None:
        super().__init__()
        self.directory = directory
        self.report_date = report_date
        self.contract_number = contract_number
        self.pdf_path = pdf_path
        self.include_last_page = include_last_page
        self.comments_dict = comments_dict
        self.status_dict = status_dict
        self.disable_states = disable_states
        self.selected_images = selected_images
        self.general_comments = general_comments
        self.questionario_respostas = questionario_respostas  # Novo atributo
        self.disable_comments_table = disable_comments_table
        self.signals = WorkerSignals()


    @pyqtSlot()
    def run(self) -> None:
        """
        Executa o processo de geração de PDF:
         1. Coleta as entradas (imagens e dados) processados.
         2. Converte os dados coletados em um arquivo PDF.
        """
        try:
            entries = collect_entries(
                self.directory,
                self.comments_dict,
                self.status_dict,
                disable_states=self.disable_states,
                selected_images=self.selected_images
            )
            convert_data_to_pdf(
                self.report_date,
                self.contract_number,
                entries,
                str(self.pdf_path),
                self.include_last_page,
                disable_states=self.disable_states,
                general_comments=self.general_comments,
                questionario_respostas=self.questionario_respostas,  # Parâmetro adicional
                disable_comments_table=self.disable_comments_table,  # Novo parâmetro
            )
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))



class RenameImagesRunnable(QRunnable):
    """
    Worker para renomear as imagens em segundo plano.
    Executa a função de renomeação e emite o sinal de término.
    """
    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self.signals = WorkerSignals()
        self.renamed_files = None

    @pyqtSlot()
    def run(self) -> None:
        """
        Tenta renomear os arquivos de imagem utilizando a função 'rename_images'.
        """
        try:
            self.renamed_files = rename_images(self.directory)
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))


# =============================================================================
# Modelo de Dados: Armazenamento das Informações de Cada Imagem
# =============================================================================

class ImageData:
    """
    Classe que representa os dados e o estado de uma imagem.
    Armazena o caminho do arquivo, nome, flag de inclusão, status, comentário, hash e ordem.
    """
    def __init__(self, file_path: Path) -> None:
        self.file_path: Path = file_path            # Caminho completo do arquivo
        self.filename: str = file_path.name         # Nome do arquivo
        self.include: bool = True                   # Flag para inclusão no processamento
        self.status: str = "Não Iniciado"          # Status inicial da imagem
        self.comment: str = ""                      # Comentário associado à imagem
        self.hash: Optional[str] = None             # Hash único (será calculado posteriormente)
        self.order: int = 9999                      # Ordem de exibição (valor alto por padrão)
        self.location: str = ""                     # Localização extraída do nome do arquivo (ex: "canteiro 12", "quadra 5")


# =============================================================================
# Widget Personalizado: Rótulo Clicável
# =============================================================================

class ClickableLabel(QLabel):
    """
    QLabel personalizado que emite um sinal 'clicked' quando o rótulo é clicado.
    Útil para tornar o nome da imagem interativo.
    """
    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:
        # Emite o sinal de clique e chama o método original
        self.clicked.emit()
        super().mousePressEvent(event)


# =============================================================================
# Widget Personalizado: Item de Lista com Status da Imagem
# =============================================================================

class ImageStatusItemWidget(QWidget):
    """
    Widget customizado para exibir os controles de cada imagem na lista.
    Contém:
      - Checkbox para indicar se a imagem deve ser incluída.
      - Rótulo clicável exibindo o nome da imagem.
      - Botões de rádio para definir o status: "Concluído", "Parcial" ou "Não Iniciado".
    """
    def __init__(self, image_data: ImageData, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.image_data = image_data            # Dados da imagem associados ao widget  
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        # Cria o checkbox para inclusão da imagem
        self.chkInclude = QCheckBox()
        self.chkInclude.setChecked(self.image_data.include)
        layout.addWidget(self.chkInclude, 0)

        # Chama o método para atualizar o efeito visual de acordo com o estado atual
        self.onIncludeChanged(self.chkInclude.checkState())

        # Cria o rótulo clicável para o nome da imagem
        self.lblName = ClickableLabel(self.image_data.filename)
        self.lblName.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.lblName, 3)

        # Cria os botões de rádio para seleção do status
        self.rbConcluido = QRadioButton("Concluído")
        self.rbParcial = QRadioButton("Parcial")
        self.rbNao = QRadioButton("Não Iniciado")

        # Define o botão de rádio padrão conforme o status armazenado
        if self.image_data.status == "Concluído":
            self.rbConcluido.setChecked(True)
        elif self.image_data.status == "Parcial":
            self.rbParcial.setChecked(True)
        else:
            self.rbNao.setChecked(True)

        # Agrupa os botões de rádio para que apenas um seja selecionado por vez
        self.btnGroup = QButtonGroup(self)
        self.btnGroup.addButton(self.rbConcluido)
        self.btnGroup.addButton(self.rbParcial)
        self.btnGroup.addButton(self.rbNao)

        layout.addWidget(self.rbConcluido, 1)
        layout.addWidget(self.rbParcial, 1)
        layout.addWidget(self.rbNao, 1)

        # Conecta os sinais dos botões para atualizar os dados em ImageData
        self.chkInclude.stateChanged.connect(self.onIncludeChanged)
        self.rbConcluido.toggled.connect(functools.partial(self.onStatusChanged, status="Concluído"))
        self.rbParcial.toggled.connect(functools.partial(self.onStatusChanged, status="Parcial"))
        self.rbNao.toggled.connect(functools.partial(self.onStatusChanged, status="Não Iniciado"))

    def onIncludeChanged(self, state: int) -> None:
        """
        Atualiza a flag de inclusão no objeto ImageData e aplica um efeito de opacidade
        se a imagem não for incluída.
        """
        self.image_data.include = (state == Qt.Checked)
        if state == Qt.Checked:
            self.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.5)
            self.setGraphicsEffect(effect)

    def onStatusChanged(self, checked: bool, status: str) -> None:
        """
        Atualiza o status da imagem no objeto ImageData quando o botão de rádio é selecionado.
        """
        if checked:
            self.image_data.status = status


# =============================================================================
# Identificadores das Páginas do Wizard (Assistente)
# =============================================================================


class WizardPage:
    """
    Classe que define constantes para identificar as páginas do Wizard.
    """
    SelectDirectoryPage = 0
    ImageListPage = 1
    FinishPage = 2


# =============================================================================
# Página 1: Selecionar Diretório
# =============================================================================

class PageSelectDirectory(QWizardPage):
    """
    Página do Wizard responsável por selecionar o diretório que contém as imagens.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Selecionar pasta com imagens")
        self.setSubTitle("Escolha a pasta que contém os arquivos de imagem.")
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Layout horizontal para exibir a label, campo de texto e botão de busca
        hlayout = QHBoxLayout()
        self.label = QLabel("Caminho da pasta:")
        self.line_edit = QLineEdit()
        self.browse_button = QPushButton("Procurar...")
        hlayout.addWidget(self.label)
        hlayout.addWidget(self.line_edit)
        hlayout.addWidget(self.browse_button)
        layout.addLayout(hlayout)

        # Layout para botão "Sobre", exibindo informações do aplicativo
        about_layout = QHBoxLayout()
        self.about_button = QPushButton("Sobre")
        about_layout.addWidget(self.about_button, alignment=Qt.AlignLeft)
        about_layout.addStretch()
        layout.addLayout(about_layout)

        # Conecta os botões aos métodos correspondentes
        self.browse_button.clicked.connect(self.on_browse)
        self.about_button.clicked.connect(self.show_about_popup)

    def on_browse(self) -> None:
        """
        Abre um diálogo para que o usuário selecione um diretório contendo as imagens.
        """
        directory = QFileDialog.getExistingDirectory(self, "Selecione a pasta com as imagens")
        if directory:
            self.line_edit.setText(directory)

    def show_about_popup(self) -> None:
        """
        Exibe uma caixa de mensagem com informações sobre o aplicativo.
        """
        QMessageBox.information(self, "Sobre", "Desenvolvido por Luiz Senko - DMA - DAV", QMessageBox.Ok)

    def validatePage(self) -> bool:
        """
        Valida se o diretório informado é válido e contém imagens.
        Também executa a renomeação dos arquivos em background antes de prosseguir.
        """
        dir_path = self.line_edit.text().strip()
        if not dir_path or not Path(dir_path).is_dir():
            QMessageBox.warning(self, "Erro", "Por favor, selecione uma pasta válida contendo imagens.", QMessageBox.Ok)
            return False

        # Cria e exibe um diálogo de progresso enquanto os arquivos são renomeados
        progress_dialog = QProgressDialog("Aguarde...", None, 0, 0, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setCancelButton(None)
        progress_dialog.show()
        QApplication.processEvents()  # Garante que a interface seja atualizada

        directory = Path(dir_path)

        # Usa um QEventLoop para aguardar o término do worker sem bloquear a atualização da UI
        loop = QEventLoop()
        result_container = {}

        def on_finished():
            result_container['renamed_files'] = worker.renamed_files
            loop.quit()

        def on_error(error_info):
            QMessageBox.critical(self, "Erro ao Renomear", f"Ocorreu um erro ao renomear os arquivos: {error_info[1]}", QMessageBox.Ok)
            loop.quit()

        # Cria o worker para renomear as imagens
        worker = RenameImagesRunnable(directory)
        worker.signals.finished.connect(on_finished)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)
        loop.exec_()    # Aguarda o término do worker

        progress_dialog.close()

        renamed_files = result_container.get('renamed_files', None)
        if renamed_files is None:
            return False
        if not renamed_files:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo foi renomeado.", QMessageBox.Ok)
        # Armazena no wizard para depois fechar na próxima página
        self.wizard().folder_progress_dialog = None
        # Deixa o botão Next em negrito para indicar que pode prosseguir
        next_button = self.wizard().button(QWizard.NextButton)
        if next_button:
            font = next_button.font()
            font.setBold(True)
            next_button.setFont(font)
        return True

    def nextId(self) -> int:
        """
        Define o identificador da próxima página do Wizard.
        """
        return WizardPage.ImageListPage


# =============================================================================
# Classe para QLabel Redimensionável
# =============================================================================

class ResizableLabel(QLabel):
    """
    QLabel que redimensiona automaticamente seu pixmap conforme seu tamanho.
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._pixmap = None

    def setPixmap(self, pixmap: QPixmap):
        """
        Armazena o pixmap original e o exibe escalonado para o tamanho atual.
        """
        self._pixmap = pixmap
        if self._pixmap:
            super().setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            super().setPixmap(pixmap)
    
    def resizeEvent(self, event):
        """
        No redimensionamento, reaplica o escalonamento do pixmap.
        """
        if self._pixmap:
            super().setPixmap(self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        super().resizeEvent(event)

# =============================================================================
# Página 2: Lista de Imagens, Comentários e Pré-visualização
# =============================================================================

class PageImageList(QWizardPage):
    """
    Página do Wizard para selecionar imagens, definir status, adicionar comentários e informar a data do relatório.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Selecionar Imagens, Definir Status, Adicionar Comentários e Data do Relatório")
        self.setSubTitle("Selecione as imagens, defina o status, insira comentários e informe a data do relatório.")
        self.setFocusPolicy(Qt.StrongFocus)
        
        # Cria um QSplitter para dividir a área em duas partes (lista e pré-visualização)
        main_splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Layout de cabeçalho com botões de configurações e comentários gerais, e campo para data do relatório
        header_container = QHBoxLayout()
        self.edit_config_button = QPushButton("Configurações")
        self.edit_config_button.clicked.connect(self.open_template_editor)
        header_container.addWidget(self.edit_config_button)
        
        self.general_comments_button = QPushButton("Comentários Gerais")
        self.general_comments_button.clicked.connect(self.open_general_comments)
        header_container.addWidget(self.general_comments_button)
        
        self.questionario_poda_button = QPushButton("Questionário de Poda")
        self.questionario_poda_button.clicked.connect(self.open_questionario_poda)
        header_container.addWidget(self.questionario_poda_button)

        # botão “Pinta Quadra”
        self.pinta_quadra_button = QPushButton("Pinta Quadra")
        self.pinta_quadra_button.clicked.connect(self.open_pinta_quadra)
        header_container.addWidget(self.pinta_quadra_button)

        date_layout = QHBoxLayout()
        date_label = QLabel("Data do Relatório:")
        # Preenche o campo com a data atual
        self.report_date_line_edit = QLineEdit(datetime.now().strftime("%d/%m/%Y"))
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.report_date_line_edit)
        header_container.addLayout(date_layout)
        left_layout.addLayout(header_container)
        # dispara ao terminar edição (enter ou perder foco)
        self.report_date_line_edit.editingFinished.connect(self.save_database)

        # Layout com checkbox para desabilitar os estados e a tabela de comentários
        checkbox_layout = QHBoxLayout()
        self.checkbox_disable_states = QCheckBox("Desativar a função de estados")
        self.checkbox_disable_states.setChecked(False)
        self.checkbox_disable_states.toggled.connect(self.on_disable_states_toggled)
        # grava no JSON toda vez que muda
        self.checkbox_disable_states.toggled.connect(self.save_database)
        checkbox_layout.addWidget(self.checkbox_disable_states)

        self.checkbox_disable_comments = QCheckBox("Desativar tabela de comentários")
        self.checkbox_disable_comments.setChecked(False)
        # grava no JSON toda vez que muda
        self.checkbox_disable_comments.toggled.connect(self.save_database)
        checkbox_layout.addWidget(self.checkbox_disable_comments)
        left_layout.addLayout(checkbox_layout)
        
        # Cabeçalho da lista de imagens com checkbox para selecionar/deselecionar todos
        header_layout = QHBoxLayout()
        self.header_toggle_checkbox = QCheckBox()
        self.header_toggle_checkbox.setChecked(True)
        self.header_toggle_checkbox.stateChanged.connect(lambda state: (self.toggle_all_items(state), self.save_database()))
        header_layout.addWidget(self.header_toggle_checkbox, 0)
        header_layout.addWidget(QLabel("Incluir"), 1)
        header_layout.addWidget(QLabel("Nome da Imagem"), 3)
        header_layout.addWidget(QLabel("Concluído"), 1)
        header_layout.addWidget(QLabel("Parcial"), 1)
        header_layout.addWidget(QLabel("Não Iniciado"), 1)
        left_layout.addLayout(header_layout)
        
        # Cria o QListWidget para exibir a lista de imagens
        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.list_widget)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        
        # Área de comentários para cada imagem selecionada
        self.comment_label = QLabel("Comentário:")
        left_layout.addWidget(self.comment_label)
        self.comment_text = QTextEdit()
        self.comment_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.comment_text)
        
        left_layout.setStretchFactor(self.list_widget, 3)
        left_layout.setStretchFactor(self.comment_text, 1)

        # Área de pré-visualização (thumbnail) da imagem selecionada
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        self.preview_label = ResizableLabel("Miniatura da Imagem")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet("border: 1px solid black;")
        right_layout.addWidget(self.preview_label)
        
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([500, 500])
        
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(main_splitter)
        
        # Mapeamento para armazenar os dados de cada imagem, usando o nome do arquivo como chave
        self.image_data_map: Dict[str, ImageData] = {}
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        self.comment_text.textChanged.connect(self.save_comment_current)

        # Timer para salvar os dados do comentário após uma breve pausa (evita salvamento a cada tecla)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self.save_database)
        
        self.installEventFilter(self)
        self.comment_text.installEventFilter(self)
        self.comment_text.viewport().installEventFilter(self)
        self.waiting_macro_insertion = False

    

    def validatePage(self) -> bool:
        """
        Valida se a data informada no campo "Data do Relatório" está no formato correto (DD/MM/AAAA).
        """
        from datetime import datetime
        user_date_str = self.get_report_date().strip()
        try:
            datetime.strptime(user_date_str, "%d/%m/%Y")
        except ValueError:
            QMessageBox.warning(
                self,
                "Data inválida",
                "Por favor, corrija a data informada.\nEla deve estar no formato DD/MM/AAAA.",
                QMessageBox.Ok
            )
            return False
        return True

    def nextId(self) -> int:
        """
        Retorna o identificador da próxima página (Página de Conclusão).
        """
        return WizardPage.FinishPage
    
    def open_general_comments(self):
        """
        Abre o diálogo para edição dos comentários gerais.
        Se já houver um comentário salvo, o mesmo é carregado no diálogo.
        """
        dialog = GeneralCommentsDialog(self)
        if hasattr(self, "general_comments_text") and self.general_comments_text:
            dialog.text_edit.setPlainText(self.general_comments_text)
        if dialog.exec_() == QDialog.Accepted:
            self.general_comments_text = dialog.get_text()
            self.save_database()  # Salva imediatamente os comentários gerais no JSON

    def open_template_editor(self):
        """
        Abre o diálogo para edição das configurações do template.
        """
        dialog = ConfigEditorDialog(self)
        if dialog.exec_():
            QMessageBox.information(self, 
                                    "Configurações Atualizadas", 
                                    "As configurações foram atualizadas com sucesso.", 
                                    QMessageBox.Ok)
    
    def open_questionario_poda(self):
        dialog = QuestionarioPodaDialog(self)
        # Se já houver respostas salvas, pré-carregue-as no diálogo
        if hasattr(self, "questionario_respostas"):
            dialog.set_answers(self.questionario_respostas)
        if dialog.exec_() == QDialog.Accepted:
            self.questionario_respostas = dialog.get_answers()
        else:
            # Se o usuário cancelar, opcionalmente não atualiza o valor
            pass
    
    def open_pinta_quadra(self) -> None:
        """
        Abre a janela do PintaQuadra usando a mesma pasta de imagens para salvar o JSON.
        """
        # obtém a pasta que o usuário escolheu na primeira página
        dir_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        save_dir = Path(dir_text)

        # instancia passando o save_dir
        self.map_coloring_win = MapColoringApp(save_dir=save_dir)
        self.map_coloring_win.show()


    def get_report_date(self) -> str:
        """
        Retorna o valor do campo de data do relatório.
        """
        return self.report_date_line_edit.text().strip()

    def on_disable_states_toggled(self, checked: bool) -> None:
        """
        Desabilita ou habilita os botões de rádio de status para cada item, conforme o estado do checkbox.
        Aplica também um efeito visual de opacidade quando desabilitado.
        """
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            for rb in [widget.rbConcluido, widget.rbParcial, widget.rbNao]:
                rb.setEnabled(not checked)
                if checked:
                    effect = QGraphicsOpacityEffect(rb)
                    effect.setOpacity(0.5)
                    rb.setGraphicsEffect(effect)
                else:
                    rb.setGraphicsEffect(None)
        self.save_database()
    
    def toggle_all_items(self, state: int) -> None:
        """
        Seleciona ou deseleciona todos os itens da lista com base no estado do checkbox do cabeçalho.
        """
        checked = (state == Qt.Checked)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            # Atualiza a checkbox de inclusão de cada item
            widget.chkInclude.setChecked(checked)
        # salva a escolha “selecionar tudo” no JSON
        self.save_database()

    def parse_location(self, filename: str) -> str:
        """
        Retorna o nome do arquivo sem a extensão, para usar como 'location'.
        """
        return Path(filename).stem
    
    def initializePage(self) -> None:
        """
        Inicializa a página:
         - Lê o diretório selecionado na primeira página.
         - Limpa a lista e o mapeamento interno.
         - Cria um diálogo de progresso e inicia o worker para carregar e pré-processar as imagens.
         - Após o processamento, carrega os dados salvos (JSON) e atualiza a interface.
        """
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        directory = Path(directory_text)

        self.list_widget.clear()
        self.image_data_map.clear()

        # Cria um progress dialog para o carregamento das imagens
        progress_dialog = QProgressDialog("Carregando imagens...", None, 0, 0, self)
        progress_dialog.setWindowModality(Qt.WindowModal)
        progress_dialog.setCancelButton(None)
        progress_dialog.show()
        QApplication.processEvents()

        # Cria o worker para carregar as imagens
        worker = LoadImagesRunnable(directory, SUPPORTED_IMAGE_EXTENSIONS)
        worker.signals.progress.connect(lambda current, total: progress_dialog.setLabelText(f"Carregando imagens... {current}/{total}"))

        def on_result(results):
            # Tenta carregar o arquivo JSON com os dados salvos
            db_path = directory / "imagens_db.json"

            disable_states = False
            
            images_db = {}
            if db_path.exists():
                try:
                    with open(db_path, "r", encoding="utf-8") as f:
                        db_full = json.load(f)
                    # Recupera os dados das imagens, comentários gerais, estados e configurações adicionais
                    images_db = db_full.get("images", {})
                    self.general_comments_text = db_full.get("general_comments", "")
                    disable_states = db_full.get("disable_states", False)
                    self.checkbox_disable_states.setChecked(disable_states)
                    self.on_disable_states_toggled(disable_states)
                    # Recupera as respostas do questionário, se houver
                    self.questionario_respostas = db_full.get("questionario_respostas", {})
                    # NOVO: Recupera o estado do toggle_all_items
                    toggle_state = db_full.get("toggle_all_items", True)
                    self.header_toggle_checkbox.setChecked(toggle_state)
                    # NOVO: Recupera a data do relatório e atualiza o campo
                    report_date = db_full.get("report_date", self.report_date_line_edit.text())
                    self.report_date_line_edit.setText(report_date)
                    # NOVO: Recupera o estado da nova checkbox
                    disable_comments_table = db_full.get("disable_comments_table", False)
                    self.checkbox_disable_comments.setChecked(disable_comments_table)

                except Exception as e:
                    logger.error(f"Erro ao carregar banco de dados: {e}", exc_info=True)

            # Atualiza cada imagem com os dados salvos do JSON (comentário, status, ordem, etc.)
            for image_data in results:
                if image_data.hash and image_data.hash in images_db:
                    saved = images_db[image_data.hash]
                    image_data.comment = saved.get("comment", "")
                    image_data.status = saved.get("status", "Não Iniciado")
                    image_data.include = saved.get("include", True)
                    image_data.order = saved.get("order", 9999)
                    image_data.location = self.parse_location(image_data.filename)
                else:
                    image_data.order = 9999

            # Ordena as imagens pela ordem definida no campo 'order'
            results.sort(key=lambda img: img.order)

            # Adiciona os itens na lista, configurando o estilo conforme a presença de comentário
            for image_data in results:
                self.image_data_map[image_data.filename] = image_data
                image_data.location = self.parse_location(image_data.filename)
                widget = ImageStatusItemWidget(image_data)
                # Conexões para salvar imediatamente ao mudar include/status
                widget.chkInclude.stateChanged.connect(self.save_database)
                widget.rbConcluido.toggled.connect(self.save_database)
                widget.rbParcial.toggled.connect(self.save_database)
                widget.rbNao.toggled.connect(self.save_database)
                if image_data.comment.strip():
                    widget.lblName.setStyleSheet("background-color: lightgreen;")
                else:
                    widget.lblName.setStyleSheet("")
                widget.lblName.clicked.connect(self.set_comment_focus)
                item = QListWidgetItem()
                item.setSizeHint(widget.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, widget)

            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
                self.load_current_item_data()
                self.set_comment_focus()
        
            # Atualiza o estado visual dos botões de status conforme a configuração
            self.on_disable_states_toggled(disable_states)

            # Agora salva imediatamente para garantir que
            # campos como toggle_all_items, report_date e disable_comments_table
            # sejam persistidos mesmo sem alteração do usuário.
            self.save_database()

        worker.signals.result.connect(on_result)
        worker.signals.finished.connect(progress_dialog.close)
        QThreadPool.globalInstance().start(worker)

    def set_comment_focus(self) -> None:
        """
        Configura a interface para inserção de macros no comentário:
         - Ativa o modo de espera para inserção de macro.
         - Destaca a área de comentário com um fundo amarelo.
        """
        self.waiting_macro_insertion = True
        self.comment_text.setStyleSheet("background-color: #FFFFCC;")  # Fundo amarelo claro
        self.setFocus()  # Define o foco na própria página para capturar eventos de teclado

    def keyPressEvent(self, event):
        """
        Intercepta eventos de tecla para verificar a inserção de macros (ex.: teclas numéricas).
        Caso uma tecla numérica seja pressionada enquanto o modo macro está ativo,
        insere o texto correspondente no campo de comentários.
        """
        if self.waiting_macro_insertion:
            key = event.key()
            mapping = {
                Qt.Key_1: "b1",
                Qt.Key_2: "b2",
                Qt.Key_3: "b3",
                Qt.Key_4: "b4",
                Qt.Key_5: "b5",
                Qt.Key_6: "b6",
                Qt.Key_7: "b7",
                Qt.Key_8: "b8",
                Qt.Key_9: "b9",
                Qt.Key_0: "b0"
            }
            if key in mapping:
                macro_key = mapping[key]
                # Determina o caminho do arquivo de macros com base na localização do script
                script_dir = os.path.dirname(os.path.abspath(__file__))
                macros_path = os.path.join(script_dir, "req_classes/macros.json")
                try:
                    with open(macros_path, "r", encoding="utf-8") as f:
                        macros = json.load(f)
                except Exception as e:
                    QMessageBox.warning(self, "Erro", f"Não foi possível carregar o arquivo macros.json: {e}", QMessageBox.Ok)
                    macros = {}
                macro_text = macros.get(macro_key, "")
                cursor = self.comment_text.textCursor()
                cursor.insertText(macro_text)
                cursor.insertBlock()  # Insere uma nova linha após o macro

                event.accept()
                return  # Interrompe a propagação do evento
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """
        Captura eventos na área de comentários para desativar o modo de inserção de macro
        quando o usuário interage com o campo.
        """
        # Se o usuário clicar na caixa de comentários ou no seu viewport, desativa o modo macro
        if (obj == self.comment_text or obj == self.comment_text.viewport()) and event.type() == QEvent.MouseButtonPress:
            self.waiting_macro_insertion = False
            self.comment_text.setStyleSheet("")  # Remove o fundo amarelo
        return super().eventFilter(obj, event)

    def load_database(self) -> None:
        """
        Carrega os dados salvos (JSON) do banco de dados e atualiza os dados de cada imagem na interface.
        """
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        db_path = Path(directory_text) / "imagens_db.json"
        images_db = {}
        if db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db_full = json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar banco de dados: {e}", exc_info=True)
                db_full = {}
            # Se o JSON possui a nova estrutura com a chave "images"
            if "images" in db_full:
                images_db = db_full.get("images", {})
                # Carrega os comentários gerais e o estado do checkbox
                self.general_comments_text = db_full.get("general_comments", "")
                disable_states = db_full.get("disable_states", False)
                self.checkbox_disable_states.setChecked(disable_states)
            else:
                images_db = db_full

        # Atualiza cada objeto ImageData com as informações carregadas do JSON
        for image_data in self.image_data_map.values():
            if image_data.hash and image_data.hash in images_db:
                saved = images_db[image_data.hash]
                image_data.comment = saved.get("comment", "")
                image_data.status = saved.get("status", "Não Iniciado")
                image_data.include = saved.get("include", True)
                image_data.order = saved.get("order", 9999)
                image_data.location = self.parse_location(image_data.filename)
            else:
                image_data.order = 9999

        # Atualiza o estado dos widgets de cada item na lista
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            image_data = widget.image_data

            if image_data.status == "Concluído":
                widget.rbConcluido.setChecked(True)
            elif image_data.status == "Parcial":
                widget.rbParcial.setChecked(True)
            else:
                widget.rbNao.setChecked(True)

            widget.chkInclude.setChecked(image_data.include)

            if image_data.comment.strip():
                widget.lblName.setStyleSheet("background-color: lightgreen;")
            else:
                widget.lblName.setStyleSheet("")


    
    def save_database(self) -> None:
        """
        Salva os dados atuais das imagens (comentários, status, inclusão, ordem) em um arquivo JSON.
        Também salva configurações gerais, como data do relatório e estado dos checkboxes.
        """
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        db_path = Path(directory_text) / "imagens_db.json"
        
        # Atualiza o atributo 'order' de cada imagem de acordo com a ordem na interface
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            widget = self.list_widget.itemWidget(item)
            if widget is None:
                continue
            widget.image_data.order = index + 1

        images_db = {}
        for image_data in self.image_data_map.values():
            if image_data.hash:
                images_db[image_data.hash] = {
                    "comment": image_data.comment,
                    "status": image_data.status,
                    "include": image_data.include,
                    "order": image_data.order,
                    "location":  image_data.location
                }
        
        # Estrutura completa a ser salva no JSON
        db_full = {
            "images": images_db,
            "general_comments": getattr(self, "general_comments_text", ""),
            "disable_states": self.checkbox_disable_states.isChecked(),
            "toggle_all_items": self.header_toggle_checkbox.isChecked(),
            "report_date": self.report_date_line_edit.text().strip(),
            "disable_comments_table": self.checkbox_disable_comments.isChecked(),
            "questionario_respostas": getattr(self, "questionario_respostas", {})  # Nova chave
        }
        try:
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(db_full, f, ensure_ascii=False, indent=4)
            logger.info("Banco de dados salvo com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao salvar banco de dados: {e}", exc_info=True)



    def on_item_changed(self, current: QListWidgetItem, previous: Optional[QListWidgetItem]) -> None:
        """
        Método chamado quando o item selecionado na lista é alterado.
        Salva os dados do item anterior e carrega os dados do novo item selecionado.
        """
        if previous is not None:
            self.save_current_item_data(previous)
            self.save_timer.stop()
            self.save_database()
        self.load_current_item_data()

    def load_current_item_data(self) -> None:
        """
        Carrega os dados (comentário e miniatura) do item atualmente selecionado na lista.
        Atualiza a área de comentário e a pré-visualização.
        """
        current_item = self.list_widget.currentItem()
        if current_item:
            widget = self.list_widget.itemWidget(current_item)
            image_data = widget.image_data
            self.comment_text.blockSignals(True)
            self.comment_text.setText(image_data.comment)
            self.comment_text.blockSignals(False)
            try:
                base64_thumb, _ = generate_thumbnail_from_file(image_data.file_path, max_size=(1200, 1200)) 
                if base64_thumb:
                    pixmap = QPixmap()
                    pixmap.loadFromData(base64.b64decode(base64_thumb))
                    # Passa o pixmap original para a ResizableLabel
                    self.preview_label.setPixmap(pixmap)
                else:
                    self.preview_label.setText("Erro ao carregar imagem.")
            except Exception as e:
                self.preview_label.setText("Erro ao processar imagem.")

    def save_current_item_data(self, item: QListWidgetItem) -> None:
        """
        Salva os dados atuais (comentário) do item que está sendo alterado.
        Atualiza também o estilo visual do rótulo se houver comentário.
        """
        widget = self.list_widget.itemWidget(item)
        image_data = widget.image_data
        text = self.comment_text.toPlainText()
        image_data.comment = text
        if text.strip():
            widget.lblName.setStyleSheet("background-color: lightgreen;")
        else:
            widget.lblName.setStyleSheet("")

    def save_comment_current(self) -> None:
        """
        Salva o comentário atual à medida que o usuário digita.
        Reinicia o timer para salvar após um breve período sem digitação.
        """
        current_item = self.list_widget.currentItem()
        if current_item:
            widget = self.list_widget.itemWidget(current_item)
            image_data = widget.image_data
            text = self.comment_text.toPlainText()

            image_data.comment = text
            if text.strip():
                widget.lblName.setStyleSheet("background-color: lightgreen;")
            else:
                widget.lblName.setStyleSheet("")
            self.save_timer.start()

    def get_selected_images(self) -> List[str]:
        """
        Retorna uma lista com os nomes das imagens que estão marcadas para inclusão.
        """
        selected_images = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            widget = self.list_widget.itemWidget(item)
            if widget.image_data.include:
                selected_images.append(widget.image_data.filename)
        return selected_images

    def get_status_dict(self) -> Dict[str, str]:
        """
        Retorna um dicionário que mapeia o nome do arquivo para o status da imagem.
        """
        return {filename: data.status for filename, data in self.image_data_map.items()}

    def get_comment_dict(self) -> Dict[str, str]:
        """
        Retorna um dicionário que mapeia o nome do arquivo para o comentário associado.
        """
        return {filename: data.comment for filename, data in self.image_data_map.items()}

    def get_disable_states(self) -> bool:
        """
        Retorna o estado (True/False) do checkbox que desativa os estados.
        """
        return self.checkbox_disable_states.isChecked()


# =============================================================================
# Diálogo para Comentários Gerais
# =============================================================================

class GeneralCommentsDialog(QDialog):
    """
    Diálogo para o usuário inserir ou editar comentários gerais.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comentários Gerais")
        self.resize(800, 600)
        layout = QVBoxLayout(self)
        
        self.text_edit = QTextEdit(self)
        layout.addWidget(self.text_edit)
        
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Salvar", self)
        self.close_button = QPushButton("Fechar", self)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.close_button)
        layout.addLayout(button_layout)
        
        # Conecta os botões para salvar ou fechar o diálogo
        self.save_button.clicked.connect(self.on_save)
        self.close_button.clicked.connect(self.reject)
    
    def on_save(self):
        """
        Aceita o diálogo, indicando que os dados foram salvos.
        """
        self.accept()
    
    def get_text(self):
        """
        Retorna o texto inserido no campo de comentários.
        """
        return self.text_edit.toPlainText()
    
# =============================================================================
# Página 3: Concluir e Geração de PDF
# =============================================================================

class PageFinish(QWizardPage):
    """
    Página final do Wizard, onde o processamento é concluído e o PDF pode ser gerado.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Concluir")
        self.setSubTitle("Clique em 'Concluir' para finalizar o processo.")
        layout = QVBoxLayout()
        self.setLayout(layout)

        info_label = QLabel("Pronto para finalizar o processamento.")
        layout.addWidget(info_label)

        # Checkbox para decidir se o PDF será gerado automaticamente
        self.checkbox_generate_pdf = QCheckBox("Gerar PDF automaticamente após processamento")
        self.checkbox_generate_pdf.setChecked(True)
        layout.addWidget(self.checkbox_generate_pdf)

        # Checkbox para incluir uma página de assinaturas no PDF
        self.checkbox_include_signature = QCheckBox("Adicionar página de assinaturas")
        self.checkbox_include_signature.setChecked(False)
        layout.addWidget(self.checkbox_include_signature)

        self.threadpool = QThreadPool()
        self.progress_dialog: Optional[QProgressDialog] = None
        self.pdf_progress_dialog: Optional[QProgressDialog] = None
        self.generated_pdf_path = None

    def nextId(self) -> int:
        """
        Não há próxima página após esta, retorna -1.
        """
        return -1

    def validatePage(self) -> bool:
        """
        Valida a data informada na página anterior e inicia o processamento das imagens.
        Caso a data esteja inválida, exibe uma mensagem de erro e impede a finalização.
        """
        from datetime import datetime
        # Obtém o valor do campo "Data do Relatório" na página 2
        wizard = self.wizard()
        image_page = wizard.page(WizardPage.ImageListPage)
        report_date = image_page.get_report_date().strip()

        # Valida o formato da data
        # Tenta converter a data para o formato dd/mm/yyyy
        try:
            datetime.strptime(report_date, "%d/%m/%Y")
        except ValueError:
            QMessageBox.warning(
                self,
                "Data inválida",
                "Por favor, corrija a data informada.\nEla deve estar no formato DD/MM/AAAA.",
                QMessageBox.Ok
            )
            # Se a data estiver correta, desabilita o botão de concluir e inicia o processamento
            self.wizard().button(QWizard.FinishButton).setEnabled(True)
            # Retorna False para impedir a mudança imediata de página, pois o processamento é assíncrono
            return False

        # 3) Se a data estiver válida, prossegue com o fluxo normal
        self.wizard().button(QWizard.FinishButton).setEnabled(False)
        self.run_image_processing()
        # Retorna False para não avançar imediatamente de página,
        # pois o processamento é assíncrono (usamos threads)
        return False

    def run_image_processing(self) -> None:
        """
        Inicia o processamento das imagens utilizando um worker em background.
        Coleta os dados necessários e cria um diálogo de progresso para informar o usuário.
        """
        wizard = self.wizard()
        directory = Path(wizard.page(WizardPage.SelectDirectoryPage).line_edit.text())
        image_page = wizard.page(WizardPage.ImageListPage)

        # Coleta os dicionários de comentários, imagens selecionadas e status
        comments_dict = image_page.get_comment_dict()
        selected_images = image_page.get_selected_images()
        status_dict = image_page.get_status_dict()  
        report_date = image_page.get_report_date()
        
        # Carrega as configurações para obter o número do contrato
        config = load_config()
        contract_number = config.get("reference_number", "Contrato Exemplo")

        disable_states = image_page.get_disable_states()

        # Cria o worker para processar as imagens e atualizar o progresso
        worker = ProcessImagesRunnable(
            directory, comments_dict, selected_images,
            report_date, contract_number, status_dict, disable_states
        )
        worker.signals.progress.connect(self.on_progress_update)
        worker.signals.finished.connect(self.on_processing_finished)
        worker.signals.error.connect(self.on_processing_error)
        self.threadpool.start(worker)

        self.progress_dialog = QProgressDialog("Processando imagens e gerando o relatório...", None, 0, 100, self)
        self.progress_dialog.setWindowTitle("Aguarde")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()

    def on_progress_update(self, current: int, total: int) -> None:
        """
        Atualiza a barra de progresso com base no valor atual e total.
        """
        if self.progress_dialog:
            self.progress_dialog.setValue(current * 100 // total)
            QApplication.processEvents()

    def on_processing_finished(self) -> None:
        """
        Método chamado quando o processamento das imagens é finalizado.
        Fecha o diálogo de progresso e, se o usuário optou por gerar o PDF, inicia esse processo.
        """
        if self.progress_dialog:
            self.progress_dialog.close()

        if self.checkbox_generate_pdf.isChecked():
            self.run_pdf_generation(self.checkbox_include_signature.isChecked())
        else:
            self.show_pdf_generated_message()

    def on_processing_error(self, error_info: tuple) -> None:
        """
        Exibe uma mensagem de erro se ocorrer algum problema durante o processamento das imagens.
        """
        if self.progress_dialog:
            self.progress_dialog.close()
        QMessageBox.critical(self, "Erro no Processamento", f"Erro: {error_info[1]}", QMessageBox.Ok)
        self.wizard().close()

    def run_pdf_generation(self, include_signature: bool) -> None:
        """
        Inicia a geração do PDF em background utilizando um worker.
        Prepara os dados e configura os parâmetros para a geração do relatório PDF.
        """
        wizard = self.wizard()
        directory = Path(wizard.page(WizardPage.SelectDirectoryPage).line_edit.text())
        user_date_str = wizard.page(WizardPage.ImageListPage).get_report_date()

        try:
            dt = datetime.strptime(user_date_str, "%d/%m/%Y")
            formatted_date_str = dt.strftime("%y%m%d")
        except ValueError:
            formatted_date_str = datetime.now().strftime('%y%m%d')

        config = load_config()
        contract_number = config.get("reference_number", "Contrato Exemplo")
        pdf_path = directory / f"{formatted_date_str}_Relatorio.pdf"
        self.generated_pdf_path = pdf_path

        image_page = wizard.page(WizardPage.ImageListPage)
        comments_dict = image_page.get_comment_dict()
        status_dict = image_page.get_status_dict()
        disable_states = image_page.get_disable_states()
        selected_images = image_page.get_selected_images()
        general_comments = getattr(image_page, "general_comments_text", "")
        
        # Obtém o estado do checkbox que desabilita a tabela de comentários
        disable_comments_table = image_page.checkbox_disable_comments.isChecked()

        worker = PDFGenerationRunnable(
            directory, user_date_str, contract_number, pdf_path,
            include_signature, comments_dict, status_dict,
            disable_states, selected_images,
            general_comments,
            # Add the new parameter below:
            getattr(image_page, "questionario_respostas", {}),
            disable_comments_table  # passing the new parameter
        )
        worker.signals.finished.connect(self.on_pdf_finished)
        worker.signals.error.connect(self.on_pdf_error)
        self.threadpool.start(worker)

        self.pdf_progress_dialog = QProgressDialog("Gerando PDF...", None, 0, 0, self)
        self.pdf_progress_dialog.setWindowTitle("Aguarde")
        self.pdf_progress_dialog.setWindowModality(Qt.WindowModal)
        self.pdf_progress_dialog.setCancelButton(None)
        self.pdf_progress_dialog.show()


    def on_pdf_finished(self) -> None:
        """
        Fecha o diálogo de progresso do PDF e exibe uma mensagem de sucesso.
        """
        if self.pdf_progress_dialog:
            self.pdf_progress_dialog.close()
        self.show_pdf_generated_message()

    def on_pdf_error(self, error_info: tuple) -> None:
        """
        Exibe uma mensagem de erro caso ocorra um problema na geração do PDF.
        """
        if self.pdf_progress_dialog:
            self.pdf_progress_dialog.close()
        QMessageBox.critical(self, "Erro na Geração de PDF", f"Erro: {error_info[1]}", QMessageBox.Ok)
        self.wizard().close()

    def show_pdf_generated_message(self) -> None:
        """
        Exibe uma mensagem informando ao usuário o caminho do PDF gerado com sucesso.
        """
        if self.generated_pdf_path is not None:
            QMessageBox.information(
                self,
                "PDF Gerado",
                f"PDF gerado com sucesso em:\n{self.generated_pdf_path}",
                QMessageBox.Ok
            )
        else:
            directory = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text()
            QMessageBox.information(
                self,
                "PDF Gerado",
                f"PDF gerado com sucesso em:\n{directory}",
                QMessageBox.Ok
            )
        self.wizard().close()


# =============================================================================
# Classe Principal do Wizard
# =============================================================================

class MyWizard(QWizard):
    """
    Classe principal do Wizard, responsável por gerenciar as páginas e centralizar a janela.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ReportLabDMA")
        self.default_size = (800, 600)
        self.image_list_page_size = (1200, 700)
        self.resize(*self.default_size)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Cria as páginas do Wizard
        page1 = PageSelectDirectory()
        page2 = PageImageList()
        page3 = PageFinish()
        self.setPage(WizardPage.SelectDirectoryPage, page1)
        self.setPage(WizardPage.ImageListPage, page2)
        self.setPage(WizardPage.FinishPage, page3)
        self.setStartId(WizardPage.SelectDirectoryPage)
        self.currentIdChanged.connect(self.on_current_id_changed)

    def on_current_id_changed(self, current_id: int) -> None:
        """
        Método chamado quando a página atual do Wizard muda.
        Fecha diálogos de progresso pendentes e ajusta o tamanho da janela conforme a página.
        """
        if current_id == WizardPage.ImageListPage:
            if hasattr(self, "folder_progress_dialog") and self.folder_progress_dialog:
                self.folder_progress_dialog.close()
                self.folder_progress_dialog = None
            next_button = self.button(QWizard.NextButton)
            if next_button:
                font = next_button.font()
                font.setBold(False)
                next_button.setFont(font)


    def center(self) -> None:
        """
        Centraliza a janela na tela do usuário.
        """
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geometry = screen.availableGeometry()
            center_point = screen_geometry.center()
            frame_geometry = self.frameGeometry()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())

    def closeEvent(self, event) -> None:
        """
        Método chamado quando a janela é fechada.
        Salva os dados atuais e aguarda o término das threads em background.
        """
        image_page: PageImageList = self.page(WizardPage.ImageListPage)
        if image_page:
            current_item = image_page.list_widget.currentItem()
            if current_item is not None:
                image_page.save_current_item_data(current_item)
            image_page.save_database()
        try:
            # Tenta esperar que as threads do QThreadPool finalizem (aguarda no máximo 1 segundo)
            QThreadPool.globalInstance().waitForDone(1000)
        except Exception as e:
            logger.error("Erro ao aguardar threads finalizarem: %s", e, exc_info=True)
        event.accept()



# =============================================================================
# Função de Execução do GUI
# =============================================================================

def run_gui() -> None:
    """
    Função principal que inicia o aplicativo GUI.
    Cria a aplicação, instancia o Wizard e inicia o loop de eventos.
    """
    app = QApplication(sys.argv)
    wizard = MyWizard()
    wizard.showMaximized()  # Maximiza a janela
    sys.exit(app.exec_())

# =============================================================================
# Execução do Script
# =============================================================================

if __name__ == "__main__":
    run_gui()
