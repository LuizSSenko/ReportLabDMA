# ReportLab_DMA.py
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
    QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QListWidget,
    QListWidgetItem, QTextEdit, QProgressDialog, QMessageBox, QCheckBox,
    QRadioButton, QButtonGroup, QSizePolicy, QGraphicsOpacityEffect, QSplitter
)
from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal, QObject, pyqtSlot, QRunnable, QTimer
from PyQt5.QtGui import QPixmap

from PIL import Image, ExifTags, ImageOps

# Importa funções do módulo principal para processamento
from main import (
    process_images_with_progress,
    rename_images,
    collect_entries,
    get_exif_and_image,
    generate_thumbnail_base64
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
    """
    Worker para gerar o PDF a partir dos dados processados.
    """
    def __init__(self, directory: Path, report_date: str, contract_number: str,
                 pdf_path: Path, include_last_page: bool, comments_dict: dict,
                 status_dict: dict, disable_states: bool, selected_images: list) -> None:
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
            convert_data_to_pdf(self.report_date, self.contract_number, entries, str(self.pdf_path), self.include_last_page)
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
        """
        Valida se o diretório selecionado é válido e tenta renomear os arquivos.
        """
        dir_path = self.line_edit.text().strip()
        if not dir_path or not Path(dir_path).is_dir():
            QMessageBox.warning(self, "Erro", "Por favor, selecione uma pasta válida contendo imagens.", QMessageBox.Ok)
            return False
        directory = Path(dir_path)
        try:
            renamed_files = rename_images(directory)
            if not renamed_files:
                QMessageBox.warning(self, "Aviso", "Nenhum arquivo foi renomeado.", QMessageBox.Ok)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Renomear", f"Ocorreu um erro ao renomear os arquivos: {e}", QMessageBox.Ok)
            return False
        return True

    def nextId(self) -> int:
        return WizardPage.ImageListPage


# =============================================================================
# Página 2: Lista de Imagens, Comentários e Pré-visualização
# =============================================================================

class PageImageList(QWizardPage):
    """
    Página para seleção de imagens, definição de status, adição de comentários e definição da data do relatório.
    Nesta versão, utiliza um QSplitter para dividir responsivamente a área de lista/comentários (lado esquerdo)
    da área de pré-visualização (lado direito), além de validar a data no momento em que o usuário avança.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setTitle("Selecionar Imagens, Definir Status, Adicionar Comentários e Data do Relatório")
        self.setSubTitle("Selecione as imagens, defina o status, insira comentários e informe a data do relatório.")
        
        # Cria um QSplitter para dividir responsivamente as áreas esquerda e direita
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Lado esquerdo: área com lista de imagens, comentários, data, etc.
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # --- Área de cabeçalho (botão "Editar template" + campo de data) ---
        header_container = QVBoxLayout()
        
        # Botão "Editar template" logo acima do campo de data
        self.edit_template_button = QPushButton("Editar template")
        self.edit_template_button.clicked.connect(self.open_template_editor) 
        header_container.addWidget(self.edit_template_button)
        
        # Campo para data do relatório
        date_layout = QHBoxLayout()
        date_label = QLabel("Data do Relatório:")
        from datetime import datetime
        self.report_date_line_edit = QLineEdit(datetime.now().strftime("%d/%m/%Y"))
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.report_date_line_edit)
        header_container.addLayout(date_layout)
        
        # Adiciona o header_container ao layout esquerdo
        left_layout.addLayout(header_container)
        # --- Fim da área de cabeçalho ---
        
        # Adiciona o checkbox para desativar a função de estados
        self.checkbox_disable_states = QCheckBox("Desativar a função de estados")
        self.checkbox_disable_states.setChecked(False)
        left_layout.addWidget(self.checkbox_disable_states)
        
        # Cabeçalho da lista de imagens
        header_layout = QHBoxLayout()
        header_layout.addWidget(QLabel("Incluir"), 1)
        header_layout.addWidget(QLabel("Nome da Imagem"), 3)
        header_layout.addWidget(QLabel("Concluído"), 1)
        header_layout.addWidget(QLabel("Parcial"), 1)
        header_layout.addWidget(QLabel("Não Concluído"), 1)
        left_layout.addLayout(header_layout)
        
        # Lista de imagens
        self.list_widget = QListWidget()
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.list_widget)
        
        # Área de comentário
        self.comment_label = QLabel("Comentário:")
        left_layout.addWidget(self.comment_label)
        self.comment_text = QTextEdit()
        self.comment_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.comment_text)
        
        # Define os stretch factors para distribuir o espaço vertical
        left_layout.setStretchFactor(self.list_widget, 3)
        left_layout.setStretchFactor(self.comment_text, 1)
        
        # Lado direito: pré-visualização da imagem
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        self.preview_label = QLabel("Miniatura da Imagem")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_label.setStyleSheet("border: 1px solid black;")
        right_layout.addWidget(self.preview_label)
        
        # Adiciona os widgets esquerdo e direito ao splitter
        main_splitter.addWidget(left_widget)
        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 2)
        main_splitter.setSizes([500, 500])
        
        # Layout principal da página
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(main_splitter)
        
        # Dicionário para armazenar os objetos ImageData (chave: filename)
        self.image_data_map: Dict[str, ImageData] = {}
        
        # Conecta sinais para atualização
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        self.comment_text.textChanged.connect(self.save_comment_current)
        
        # Timer para debounce do salvamento (1 segundo)
        from PyQt5.QtCore import QTimer
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)
        self.save_timer.timeout.connect(self.save_database)

    def validatePage(self) -> bool:
        """
        Valida a data digitada. Se for inválida, exibe erro e impede avançar.
        """
        from datetime import datetime
        # Pega a string de data que o usuário digitou
        user_date_str = self.get_report_date().strip()

        # Tenta converter a data para o formato dd/mm/yyyy
        try:
            datetime.strptime(user_date_str, "%d/%m/%Y")
        except ValueError:
            QMessageBox.warning(
                self,
                "Data inválida",
                "Por favor, corrija a data informada.\nEla deve estar no formato DD/MM/AAAA.",
                QMessageBox.Ok
            )
            return False  # Impede o avanço para a próxima página

        # Se passou, significa que a data está válida
        return True

    def nextId(self) -> int:
        """
        Indica qual a próxima página do Wizard após esta (provavelmente a PageFinish).
        """
        return WizardPage.FinishPage

    def open_template_editor(self):
        dialog = TemplateEditorDialog(self)
        if dialog.exec_():
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.information(self, 
                                    "Template Atualizado", 
                                    "O template foi atualizado com sucesso.", 
                                    QMessageBox.Ok)

    def get_report_date(self) -> str:
        """
        Retorna a data informada pelo usuário para o relatório.
        """
        return self.report_date_line_edit.text().strip()

    def on_disable_states_toggled(self, checked: bool) -> None:
        """
        Habilita ou desabilita os radio buttons dos itens da lista conforme o estado do checkbox.
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

    def initializePage(self) -> None:
        """
        Inicializa a página carregando as imagens e dados previamente salvos.
        """
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        directory = Path(directory_text)

        self.list_widget.clear()
        self.image_data_map.clear()

        # Carrega os arquivos de imagem suportados e computa o hash para cada um
        image_files = sorted([f for f in directory.iterdir() if f.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS])
        for image_file in image_files:
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
            self.image_data_map[image_data.filename] = image_data
            widget = ImageStatusItemWidget(image_data)
            widget.lblName.clicked.connect(self.set_comment_focus)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

        # Carrega informações previamente salvas (se houver)
        self.load_database()

        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            self.load_current_item_data()

    def set_comment_focus(self) -> None:
        """
        Define o foco na área de comentário.
        """
        self.comment_text.setFocus()

    def load_database(self) -> None:
        """
        Carrega o arquivo JSON de banco de dados (imagens_db.json) e atualiza os dados de cada imagem.
        """
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
        """
        Salva os comentários, status e o estado de inclusão de cada imagem em um arquivo JSON.
        """
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
        """
        Salva os dados do item anterior e carrega os dados do item atual.
        """
        if previous is not None:
            self.save_current_item_data(previous)
            self.save_timer.stop()
            self.save_database()
        self.load_current_item_data()

    def load_current_item_data(self) -> None:
        """
        Carrega o comentário e a pré-visualização da imagem do item selecionado.
        """
        current_item = self.list_widget.currentItem()
        if current_item:
            widget = self.list_widget.itemWidget(current_item)
            image_data = widget.image_data
            self.comment_text.blockSignals(True)
            self.comment_text.setText(image_data.comment)
            self.comment_text.blockSignals(False)
            try:
                _, img = get_exif_and_image(image_data.file_path)
                if img:
                    base64_thumb, _ = generate_thumbnail_base64(img, max_size=(600, 600))
                    pixmap = QPixmap()
                    pixmap.loadFromData(base64.b64decode(base64_thumb))
                    self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    self.preview_label.setText("Erro ao carregar imagem.")
            except Exception as e:
                self.preview_label.setText("Erro ao processar imagem.")

    def save_current_item_data(self, item: QListWidgetItem) -> None:
        """
        Salva os dados atuais do item (comentário).
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
        Salva o comentário do item atual enquanto o usuário digita.
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
        Retorna uma lista dos nomes dos arquivos que estão marcados para inclusão.
        """
        return [filename for filename, data in self.image_data_map.items() if data.include]

    def get_status_dict(self) -> Dict[str, str]:
        """
        Retorna um dicionário com o status de cada imagem.
        """
        return {filename: data.status for filename, data in self.image_data_map.items()}

    def get_comment_dict(self) -> Dict[str, str]:
        """
        Retorna um dicionário com os comentários de cada imagem.
        """
        return {filename: data.comment for filename, data in self.image_data_map.items()}

    def get_disable_states(self) -> bool:
        """
        Retorna True se a função de estados estiver desativada.
        """
        return self.checkbox_disable_states.isChecked()


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
        from main import load_config
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

        self.progress_dialog = QProgressDialog("Processando imagens e gerando HTML...", None, 0, 100, self)
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

        from main import load_config
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

        worker = PDFGenerationRunnable(
            directory, user_date_str, contract_number, pdf_path,
            include_signature, comments_dict, status_dict,
            disable_states, selected_images
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
        """
        Ajusta o tamanho da janela conforme a página atual e a centraliza.
        """
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
        """
        Ao fechar o Wizard, garante que os dados sejam salvos.
        """
        image_page: PageImageList = self.page(WizardPage.ImageListPage)
        if image_page:
            image_page.save_database()
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
