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

from PyQt5.QtWidgets import (
    QApplication, QWizard, QWizardPage, QLabel, QLineEdit, QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QListWidget, QDialog,
    QListWidgetItem, QTextEdit, QProgressDialog, QMessageBox, QCheckBox,
    QRadioButton, QButtonGroup, QSizePolicy, QGraphicsOpacityEffect, QSplitter
)
from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal, QObject, pyqtSlot, QRunnable, QTimer, QEvent, QEventLoop
from PyQt5.QtGui import QPixmap

from PIL import Image, ExifTags, ImageOps

# Importa funções do módulo principal para processamento
from main import (
    process_images_with_progress,
    rename_images,
    collect_entries,
    get_exif_and_image,
    generate_thumbnail_from_file,
    load_config
)
from pdf_tools import convert_data_to_pdf
from template_editor import TemplateEditorDialog


# Configuração do logger para este módulo
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    file_handler = logging.FileHandler("gui_app.log")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

# Constantes
SUPPORTED_IMAGE_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".heic"]
#DEFAULT_CONTRACT: str = "039/2019 - PROVAC TERCEIRIZAÇÃO DE MÃO DE OBRA LTDA"


def compute_image_hash(img: Image.Image, quality: int = 85) -> Optional[str]:
    """
    Calcula um hash MD5 da imagem após salvá-la num buffer com qualidade reduzida.

    Args:
        img (Image.Image): Imagem a ser processada.
        quality (int, optional): Qualidade do JPEG. Defaults to 85.

    Returns:
        Optional[str]: Hash MD5 da imagem ou None em caso de erro.
    """
    buffer = BytesIO()
    try:
        img.save(buffer, format="JPEG", quality=quality)
    except Exception as e:
        logger.error(f"Erro ao salvar imagem para computar hash: {e}", exc_info=True)
        return None
    data = buffer.getvalue()
    return hashlib.md5(data).hexdigest()


# =============================================================================
# Worker Signals e Runnables (para processamento em segundo plano)
# =============================================================================

class WorkerSignals(QObject):
    """
    Sinais usados pelos workers para comunicação com a interface.
    """
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int, int)  # current, total


class LoadImagesRunnable(QRunnable):
    """
    Worker para carregar e pré-processar (EXIF, hash) as imagens do diretório.
    """
    def __init__(self, directory: Path, supported_extensions: List[str]) -> None:
        super().__init__()
        self.directory = directory
        self.supported_extensions = supported_extensions
        self.signals = WorkerSignals()
        self.image_data_list = []  # Lista de objetos ImageData

    @pyqtSlot()
    def run(self) -> None:
        try:
            image_files = sorted([f for f in self.directory.iterdir() if f.suffix.lower() in self.supported_extensions])
            total = len(image_files)
            results = []
            for idx, image_file in enumerate(image_files, start=1):
                image_data = ImageData(image_file)
                try:
                    _, img = get_exif_and_image(image_file)
                    if img:
                        image_hash = compute_image_hash(img)
                        image_data.hash = image_hash
                    else:
                        image_data.hash = None
                except Exception as e:
                    logger.error(f"Erro ao computar hash para {image_file.name}: {e}", exc_info=True)
                    image_data.hash = None
                results.append(image_data)
                self.signals.progress.emit(idx, total)
            self.image_data_list = results
            self.signals.result.emit(results)
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))


class ProcessImagesRunnable(QRunnable):
    """
    Worker para processar imagens em segundo plano.
    """
    def __init__(self, directory: Path, comments_dict: dict, selected_images: list,
                 report_date: str, contract_number: str, status_dict: dict, disable_states: bool) -> None:
        super().__init__()
        self.directory = directory
        self.comments_dict = comments_dict
        self.selected_images = selected_images
        self.report_date = report_date
        self.contract_number = contract_number
        self.status_dict = status_dict  # Armazena o status correto
        self.disable_states = disable_states
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            process_images_with_progress(
                self.directory,
                comments_dict=self.comments_dict,
                selected_images=self.selected_images,
                report_date=self.report_date,
                contract_number=self.contract_number,
                status_dict=self.status_dict,  # Passa o status_dict correto
                progress_callback=self.signals.progress.emit,
                disable_states=self.disable_states
            )
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))


class PDFGenerationRunnable(QRunnable):
    # # #
    # Worker para gerar o PDF em segundo plano
    # # #
    def __init__(self, directory: Path, report_date: str, contract_number: str,
                 pdf_path: Path, include_last_page: bool, comments_dict: dict,
                 status_dict: dict, disable_states: bool, selected_images: list, general_comments: str) -> None:
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
        self.general_comments = general_comments  # novo parâmetro
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self) -> None:
        try:
            entries = collect_entries(
                self.directory,
                self.comments_dict,
                self.status_dict,
                disable_states=self.disable_states,
                selected_images=self.selected_images
            )
            # Repasse o general_comments para a função de conversão
            convert_data_to_pdf(
                self.report_date,
                self.contract_number,
                entries,
                str(self.pdf_path),
                self.include_last_page,
                disable_states=self.disable_states,
                general_comments=self.general_comments
            )
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))



class RenameImagesRunnable(QRunnable):
    """
    Worker para renomear as imagens em segundo plano.
    """
    def __init__(self, directory: Path) -> None:
        super().__init__()
        self.directory = directory
        self.signals = WorkerSignals()
        self.renamed_files = None

    @pyqtSlot()
    def run(self) -> None:
        try:
            self.renamed_files = rename_images(self.directory)
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))


# =============================================================================
# Classe para armazenar o estado de cada imagem (Modelo de Dados)
# =============================================================================

class ImageData:
    """
    Armazena informações e estado de cada imagem.
    """
    def __init__(self, file_path: Path) -> None:
        self.file_path: Path = file_path
        self.filename: str = file_path.name
        self.include: bool = True
        self.status: str = "Não Concluído"
        self.comment: str = ""
        self.hash: Optional[str] = None  # Será preenchido com o hash único da imagem
        self.order: int = 9999  # Valor padrão para a ordem


# =============================================================================
# Rótulo Clicável
# =============================================================================

class ClickableLabel(QLabel):
    """
    QLabel que emite um sinal 'clicked' ao ser pressionado.
    """
    clicked = pyqtSignal()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


# =============================================================================
# Widget Customizado para cada item da lista de imagens
# =============================================================================

class ImageStatusItemWidget(QWidget):
    """
    Widget customizado para exibir os controles de cada imagem:
      - Checkbox para inclusão
      - Rótulo com o nome da imagem (clicável)
      - Radio buttons para status: "Concluído", "Parcial" e "Não Concluído"
    """
    def __init__(self, image_data: ImageData, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.image_data = image_data
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        # Checkbox para inclusão
        self.chkInclude = QCheckBox()
        self.chkInclude.setChecked(self.image_data.include)
        layout.addWidget(self.chkInclude, 0)

        # Rótulo clicável para o nome da imagem
        self.lblName = ClickableLabel(self.image_data.filename)
        self.lblName.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(self.lblName, 3)

        # Radio buttons para status
        self.rbConcluido = QRadioButton("Concluído")
        self.rbParcial = QRadioButton("Parcial")
        self.rbNao = QRadioButton("Não Concluído")

        # Define o valor padrão conforme o estado em image_data
        if self.image_data.status == "Concluído":
            self.rbConcluido.setChecked(True)
        elif self.image_data.status == "Parcial":
            self.rbParcial.setChecked(True)
        else:
            self.rbNao.setChecked(True)

        # Agrupa os radio buttons
        self.btnGroup = QButtonGroup(self)
        self.btnGroup.addButton(self.rbConcluido)
        self.btnGroup.addButton(self.rbParcial)
        self.btnGroup.addButton(self.rbNao)

        layout.addWidget(self.rbConcluido, 1)
        layout.addWidget(self.rbParcial, 1)
        layout.addWidget(self.rbNao, 1)

        # Conecta os sinais para atualizar o estado no ImageData
        self.chkInclude.stateChanged.connect(self.onIncludeChanged)
        self.rbConcluido.toggled.connect(functools.partial(self.onStatusChanged, status="Concluído"))
        self.rbParcial.toggled.connect(functools.partial(self.onStatusChanged, status="Parcial"))
        self.rbNao.toggled.connect(functools.partial(self.onStatusChanged, status="Não Concluído"))

    def onIncludeChanged(self, state: int) -> None:
        """
        Atualiza a flag de inclusão e aplica efeito de opacidade caso a imagem não seja incluída.
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
        Atualiza o status da imagem quando um radio button é marcado.
        """
        if checked:
            self.image_data.status = status


# =============================================================================
# Identificadores das Páginas do Wizard
# =============================================================================

class WizardPage:
    SelectDirectoryPage = 0
    ImageListPage = 1
    FinishPage = 2


# =============================================================================
# Página 1: Selecionar Diretório
# =============================================================================

class PageSelectDirectory(QWizardPage):
    """
    Página para seleção do diretório que contém as imagens.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Selecionar pasta com imagens")
        self.setSubTitle("Escolha a pasta que contém os arquivos de imagem.")
        layout = QVBoxLayout()
        self.setLayout(layout)

        hlayout = QHBoxLayout()
        self.label = QLabel("Caminho da pasta:")
        self.line_edit = QLineEdit()
        self.browse_button = QPushButton("Procurar...")
        hlayout.addWidget(self.label)
        hlayout.addWidget(self.line_edit)
        hlayout.addWidget(self.browse_button)
        layout.addLayout(hlayout)

        about_layout = QHBoxLayout()
        self.about_button = QPushButton("Sobre")
        about_layout.addWidget(self.about_button, alignment=Qt.AlignLeft)
        about_layout.addStretch()
        layout.addLayout(about_layout)

        self.browse_button.clicked.connect(self.on_browse)
        self.about_button.clicked.connect(self.show_about_popup)

    def on_browse(self) -> None:
        """
        Abre o diálogo para seleção de diretório.
        """
        directory = QFileDialog.getExistingDirectory(self, "Selecione a pasta com as imagens")
        if directory:
            self.line_edit.setText(directory)

    def show_about_popup(self) -> None:
        """
        Exibe informações sobre o aplicativo.
        """
        QMessageBox.information(self, "Sobre", "Desenvolvido por Luiz Senko - DMA - DAV", QMessageBox.Ok)

    def validatePage(self) -> bool:
        dir_path = self.line_edit.text().strip()
        if not dir_path or not Path(dir_path).is_dir():
            QMessageBox.warning(self, "Erro", "Por favor, selecione uma pasta válida contendo imagens.", QMessageBox.Ok)
            return False

        # Cria e exibe o progress dialog logo que o usuário clica em Next
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

        worker = RenameImagesRunnable(directory)
        worker.signals.finished.connect(on_finished)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)
        loop.exec_()

        progress_dialog.close()

        renamed_files = result_container.get('renamed_files', None)
        if renamed_files is None:
            return False
        if not renamed_files:
            QMessageBox.warning(self, "Aviso", "Nenhum arquivo foi renomeado.", QMessageBox.Ok)
        # Armazena no wizard para depois fechar na próxima página
        self.wizard().folder_progress_dialog = None
        # Deixa o botão Next em bold
        next_button = self.wizard().button(QWizard.NextButton)
        if next_button:
            font = next_button.font()
            font.setBold(True)
            next_button.setFont(font)
        return True

    def nextId(self) -> int:
        return WizardPage.ImageListPage


# =============================================================================
# Página 2: Lista de Imagens, Comentários e Pré-visualização
# =============================================================================

class PageImageList(QWizardPage):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Selecionar Imagens, Definir Status, Adicionar Comentários e Data do Relatório")
        self.setSubTitle("Selecione as imagens, defina o status, insira comentários e informe a data do relatório.")
        self.setFocusPolicy(Qt.StrongFocus)

        # Cria um QSplitter para dividir a área de lista/comentários da pré-visualização
        main_splitter = QSplitter(Qt.Horizontal)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        header_container = QHBoxLayout()
        self.edit_template_button = QPushButton("Editar template")
        self.edit_template_button.clicked.connect(self.open_template_editor)
        header_container.addWidget(self.edit_template_button)
        
        self.general_comments_button = QPushButton("Comentários Gerais")
        self.general_comments_button.clicked.connect(self.open_general_comments)
        header_container.addWidget(self.general_comments_button)
        
        date_layout = QHBoxLayout()
        date_label = QLabel("Data do Relatório:")
        self.report_date_line_edit = QLineEdit(datetime.now().strftime("%d/%m/%Y"))
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.report_date_line_edit)
        header_container.addLayout(date_layout)
        left_layout.addLayout(header_container)
        
        self.checkbox_disable_states = QCheckBox("Desativar a função de estados")
        self.checkbox_disable_states.setChecked(False)
        self.checkbox_disable_states.toggled.connect(self.on_disable_states_toggled)
        left_layout.addWidget(self.checkbox_disable_states)
        
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Incluir"), 1)
        header_layout.addWidget(QLabel("Nome da Imagem"), 3)
        header_layout.addWidget(QLabel("Concluído"), 1)
        header_layout.addWidget(QLabel("Parcial"), 1)
        header_layout.addWidget(QLabel("Não Concluído"), 1)
        left_layout.addLayout(header_layout)
        
        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.list_widget)

        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        
        self.comment_label = QLabel("Comentário:")
        left_layout.addWidget(self.comment_label)
        self.comment_text = QTextEdit()
        self.comment_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.comment_text)
        
        left_layout.setStretchFactor(self.list_widget, 3)
        left_layout.setStretchFactor(self.comment_text, 1)
        
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        self.preview_label = QLabel("Miniatura da Imagem")
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
        
        self.image_data_map: Dict[str, ImageData] = {}
        
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        self.comment_text.textChanged.connect(self.save_comment_current)
        
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self.save_database)
        
        # Instala o event filter para capturar eventos de teclado e foco
        self.installEventFilter(self)
        self.comment_text.installEventFilter(self)
        self.comment_text.installEventFilter(self)
        self.comment_text.viewport().installEventFilter(self)
        self.waiting_macro_insertion = False
    

    def validatePage(self) -> bool:
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
        return WizardPage.FinishPage
    
    def open_general_comments(self):
        dialog = GeneralCommentsDialog(self)
        # Se houver comentário geral já salvo, preenche o diálogo
        if hasattr(self, "general_comments_text") and self.general_comments_text:
            dialog.text_edit.setPlainText(self.general_comments_text)
        if dialog.exec_() == QDialog.Accepted:
            self.general_comments_text = dialog.get_text()

    def open_template_editor(self):
        dialog = TemplateEditorDialog(self)
        if dialog.exec_():
            QMessageBox.information(self, 
                                    "Template Atualizado", 
                                    "O template foi atualizado com sucesso.", 
                                    QMessageBox.Ok)

    def get_report_date(self) -> str:
        return self.report_date_line_edit.text().strip()

    def on_disable_states_toggled(self, checked: bool) -> None:
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

    def initializePage(self) -> None:
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

        # Cria o worker para carregar e pré-processar as imagens
        worker = LoadImagesRunnable(directory, SUPPORTED_IMAGE_EXTENSIONS)
        worker.signals.progress.connect(lambda current, total: progress_dialog.setLabelText(f"Carregando imagens... {current}/{total}"))
        def on_result(results):
            for image_data in results:
                self.image_data_map[image_data.filename] = image_data
                widget = ImageStatusItemWidget(image_data)
                widget.lblName.clicked.connect(self.set_comment_focus)
                item = QListWidgetItem()
                item.setSizeHint(widget.sizeHint())
                self.list_widget.addItem(item)
                self.list_widget.setItemWidget(item, widget)
            self.load_database()
            if self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
                self.load_current_item_data()
                self.set_comment_focus()
        worker.signals.result.connect(on_result)
        worker.signals.finished.connect(progress_dialog.close)
        QThreadPool.globalInstance().start(worker)

    def set_comment_focus(self) -> None:
        self.waiting_macro_insertion = True
        self.comment_text.setStyleSheet("background-color: #FFFFCC;")  # amarelo claro
        self.setFocus()  # Faz com que a própria página receba os eventos de teclado

    def keyPressEvent(self, event):
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
                # Obtém o diretório onde o script está localizado
                script_dir = os.path.dirname(os.path.abspath(__file__))
                macros_path = os.path.join(script_dir, "macros.json")
                try:
                    with open(macros_path, "r", encoding="utf-8") as f:
                        macros = json.load(f)
                except Exception as e:
                    QMessageBox.warning(self, "Erro", f"Não foi possível carregar o arquivo macros.json: {e}", QMessageBox.Ok)
                    macros = {}
                macro_text = macros.get(macro_key, "")
                cursor = self.comment_text.textCursor()
                cursor.insertText(macro_text)
                cursor.insertBlock()  # Insere uma nova linha

                event.accept()
                return  # Não propaga o evento
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        # Se o usuário clicar na caixa de comentários ou no seu viewport, desativa o modo macro
        if (obj == self.comment_text or obj == self.comment_text.viewport()) and event.type() == QEvent.MouseButtonPress:
            self.waiting_macro_insertion = False
            self.comment_text.setStyleSheet("")  # Remove o fundo amarelo
        return super().eventFilter(obj, event)

    def load_database(self) -> None:
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        db_path = Path(directory_text) / "imagens_db.json"
        if db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar banco de dados: {e}", exc_info=True)
                db = {}
        else:
            db = {}

        for image_data in self.image_data_map.values():
            if image_data.hash and image_data.hash in db:
                saved = db[image_data.hash]
                image_data.comment = saved.get("comment", "")
                image_data.status = saved.get("status", "Não Concluído")
                image_data.include = saved.get("include", True)

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
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        db_path = Path(directory_text) / "imagens_db.json"
        db = {}
        for image_data in self.image_data_map.values():
            if image_data.hash:
                db[image_data.hash] = {
                    "comment": image_data.comment,
                    "status": image_data.status,
                    "include": image_data.include
                }
        try:
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=4)
            logger.info("Banco de dados salvo com sucesso.")
        except Exception as e:
            logger.error(f"Erro ao salvar banco de dados: {e}", exc_info=True)



    def on_item_changed(self, current: QListWidgetItem, previous: Optional[QListWidgetItem]) -> None:
        if previous is not None:
            self.save_current_item_data(previous)
            self.save_timer.stop()
            self.save_database()
        self.load_current_item_data()

    def load_current_item_data(self) -> None:
        current_item = self.list_widget.currentItem()
        if current_item:
            widget = self.list_widget.itemWidget(current_item)
            image_data = widget.image_data
            self.comment_text.blockSignals(True)
            self.comment_text.setText(image_data.comment)
            self.comment_text.blockSignals(False)
            try:
                base64_thumb, _ = generate_thumbnail_from_file(image_data.file_path, max_size=(600, 600))
                if base64_thumb:
                    pixmap = QPixmap()
                    pixmap.loadFromData(base64.b64decode(base64_thumb))
                    self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    self.preview_label.setText("Erro ao carregar imagem.")
            except Exception as e:
                self.preview_label.setText("Erro ao processar imagem.")

    def save_current_item_data(self, item: QListWidgetItem) -> None:
        widget = self.list_widget.itemWidget(item)
        image_data = widget.image_data
        text = self.comment_text.toPlainText()
        image_data.comment = text
        if text.strip():
            widget.lblName.setStyleSheet("background-color: lightgreen;")
        else:
            widget.lblName.setStyleSheet("")

    def save_comment_current(self) -> None:
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
        selected_images = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            widget = self.list_widget.itemWidget(item)
            if widget.image_data.include:
                selected_images.append(widget.image_data.filename)
        return selected_images

    def get_status_dict(self) -> Dict[str, str]:
        return {filename: data.status for filename, data in self.image_data_map.items()}

    def get_comment_dict(self) -> Dict[str, str]:
        return {filename: data.comment for filename, data in self.image_data_map.items()}

    def get_disable_states(self) -> bool:
        return self.checkbox_disable_states.isChecked()

class GeneralCommentsDialog(QDialog):
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
        
        self.save_button.clicked.connect(self.on_save)
        self.close_button.clicked.connect(self.reject)
    
    def on_save(self):
        # Simplesmente aceita o diálogo; o método get_text() retornará o conteúdo
        self.accept()
    
    def get_text(self):
        return self.text_edit.toPlainText()
    
# =============================================================================
# Página 3: Concluir e Geração de PDF
# =============================================================================

class PageFinish(QWizardPage):
    """
    Página final para concluir o processamento e, opcionalmente, gerar o PDF.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Concluir")
        self.setSubTitle("Clique em 'Concluir' para finalizar o processo.")
        layout = QVBoxLayout()
        self.setLayout(layout)

        info_label = QLabel("Pronto para finalizar o processamento.")
        layout.addWidget(info_label)

        self.checkbox_generate_pdf = QCheckBox("Gerar PDF automaticamente após processamento")
        self.checkbox_generate_pdf.setChecked(True)
        layout.addWidget(self.checkbox_generate_pdf)

        self.checkbox_include_signature = QCheckBox("Adicionar página de assinaturas")
        self.checkbox_include_signature.setChecked(False)
        layout.addWidget(self.checkbox_include_signature)

        self.threadpool = QThreadPool()
        self.progress_dialog: Optional[QProgressDialog] = None
        self.pdf_progress_dialog: Optional[QProgressDialog] = None
        self.generated_pdf_path = None

    def nextId(self) -> int:
        return -1

    def validatePage(self) -> bool:
        """
        Valida a data que o usuário digitou na página anterior e,
        se estiver tudo correto, inicia o processamento das imagens.
        Caso contrário, exibe uma mensagem de erro e interrompe o fluxo.
        """
        from datetime import datetime
        # 1) Obtém o valor do campo "Data do Relatório" na página 2
        wizard = self.wizard()
        image_page = wizard.page(WizardPage.ImageListPage)
        report_date = image_page.get_report_date().strip()

        # 2) Tenta converter a data para o formato dd/mm/yyyy
        try:
            datetime.strptime(report_date, "%d/%m/%Y")
        except ValueError:
            QMessageBox.warning(
                self,
                "Data inválida",
                "Por favor, corrija a data informada.\nEla deve estar no formato DD/MM/AAAA.",
                QMessageBox.Ok
            )
            # Reabilita o botão "Concluir" e interrompe aqui
            self.wizard().button(QWizard.FinishButton).setEnabled(True)
            return False

        # 3) Se a data estiver válida, prossegue com o fluxo normal
        self.wizard().button(QWizard.FinishButton).setEnabled(False)
        self.run_image_processing()
        # Retorna False para não avançar imediatamente de página,
        # pois o processamento é assíncrono (usamos threads)
        return False

    def run_image_processing(self) -> None:
        wizard = self.wizard()
        directory = Path(wizard.page(WizardPage.SelectDirectoryPage).line_edit.text())
        image_page = wizard.page(WizardPage.ImageListPage)

        # Coleta dict de comentários, imagens selecionadas, status, etc.
        comments_dict = image_page.get_comment_dict()
        selected_images = image_page.get_selected_images()
        status_dict = image_page.get_status_dict()  
        report_date = image_page.get_report_date()
        
        # Carrega config p/ obter número do contrato
        config = load_config()
        contract_number = config.get("reference_number", "Contrato Exemplo")

        disable_states = image_page.get_disable_states()

        # Cria o worker para processar as imagens e gerar o HTML
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
        Atualiza a barra de progresso.
        """
        if self.progress_dialog:
            self.progress_dialog.setValue(current * 100 // total)
            QApplication.processEvents()

    def on_processing_finished(self) -> None:
        """
        Finaliza o processamento e inicia a geração do PDF, se selecionado.
        """
        if self.progress_dialog:
            self.progress_dialog.close()

        if self.checkbox_generate_pdf.isChecked():
            self.run_pdf_generation(self.checkbox_include_signature.isChecked())
        else:
            self.show_pdf_generated_message()

    def on_processing_error(self, error_info: tuple) -> None:
        """
        Exibe mensagem de erro caso o processamento falhe.
        """
        if self.progress_dialog:
            self.progress_dialog.close()
        QMessageBox.critical(self, "Erro no Processamento", f"Erro: {error_info[1]}", QMessageBox.Ok)
        self.wizard().close()

    def run_pdf_generation(self, include_signature: bool) -> None:
        wizard = self.wizard()
        directory = Path(wizard.page(WizardPage.SelectDirectoryPage).line_edit.text())

        # Pega a data digitada na página 2
        user_date_str = wizard.page(WizardPage.ImageListPage).get_report_date()

        # Converte de dd/mm/yyyy para datetime e re-formata para yyMMdd
        try:
            dt = datetime.strptime(user_date_str, "%d/%m/%Y")
            formatted_date_str = dt.strftime("%y%m%d")
        except ValueError:
            formatted_date_str = datetime.now().strftime('%y%m%d')

        config = load_config()
        contract_number = config.get("reference_number", "Contrato Exemplo")

        # Usa a data digitada (em formato yyMMdd) para gerar o nome do PDF
        pdf_path = directory / f"{formatted_date_str}_Relatorio.pdf"
        self.generated_pdf_path = pdf_path

        image_page = wizard.page(WizardPage.ImageListPage)
        comments_dict = image_page.get_comment_dict()
        status_dict = image_page.get_status_dict()
        disable_states = image_page.get_disable_states()
        selected_images = image_page.get_selected_images()
        
        # Obtém o comentário geral (caso exista)
        general_comments = getattr(image_page, "general_comments_text", "")

        # Cria o worker com o parâmetro general_comments já incluído
        worker = PDFGenerationRunnable(
            directory, user_date_str, contract_number, pdf_path,
            include_signature, comments_dict, status_dict,
            disable_states, selected_images, general_comments
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
        Finaliza a geração do PDF.
        """
        if self.pdf_progress_dialog:
            self.pdf_progress_dialog.close()
        self.show_pdf_generated_message()

    def on_pdf_error(self, error_info: tuple) -> None:
        """
        Exibe mensagem de erro caso a geração do PDF falhe.
        """
        if self.pdf_progress_dialog:
            self.pdf_progress_dialog.close()
        QMessageBox.critical(self, "Erro na Geração de PDF", f"Erro: {error_info[1]}", QMessageBox.Ok)
        self.wizard().close()

    def show_pdf_generated_message(self) -> None:
        """
        Exibe mensagem informando que o PDF foi gerado com sucesso.
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
        page1 = PageSelectDirectory()
        page2 = PageImageList()
        page3 = PageFinish()
        self.setPage(WizardPage.SelectDirectoryPage, page1)
        self.setPage(WizardPage.ImageListPage, page2)
        self.setPage(WizardPage.FinishPage, page3)
        self.setStartId(WizardPage.SelectDirectoryPage)
        self.currentIdChanged.connect(self.on_current_id_changed)

    def on_current_id_changed(self, current_id: int) -> None:
        # Se a nova página for a de imagens, fecha o progress dialog e restaura o botão Next
        if current_id == WizardPage.ImageListPage:
            if hasattr(self, "folder_progress_dialog") and self.folder_progress_dialog:
                self.folder_progress_dialog.close()
                self.folder_progress_dialog = None
            next_button = self.button(QWizard.NextButton)
            if next_button:
                font = next_button.font()
                font.setBold(False)
                next_button.setFont(font)
                
        # Ajusta o tamanho da janela conforme a página
        if current_id == WizardPage.ImageListPage:
            self.resize(*self.image_list_page_size)
        else:
            self.resize(*self.default_size)
        self.center()

    def center(self) -> None:
        """
        Centraliza a janela na tela.
        """
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geometry = screen.availableGeometry()
            center_point = screen_geometry.center()
            frame_geometry = self.frameGeometry()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())

    def closeEvent(self, event) -> None:
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
    Função principal para executar o aplicativo GUI.
    """
    app = QApplication(sys.argv)
    wizard = MyWizard()
    wizard.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    run_gui()
