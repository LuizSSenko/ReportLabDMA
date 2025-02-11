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
from io import BytesIO  # Necessário para computar o hash

from PyQt5.QtWidgets import (
    QApplication, QWizard, QWizardPage, QLabel, QLineEdit, QWidget,
    QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QListWidget,
    QListWidgetItem, QTextEdit, QProgressDialog, QMessageBox, QCheckBox,
    QRadioButton, QButtonGroup, QSizePolicy, QGraphicsOpacityEffect
)
from PyQt5.QtCore import Qt, QThreadPool, pyqtSignal, QObject, pyqtSlot, QRunnable, QTimer
from PyQt5.QtGui import QPixmap

from PIL import Image, ExifTags, ImageOps

# Importa funções do módulo principal para processamento
from main import process_images_with_progress, rename_images, collect_entries, get_exif_and_image, generate_thumbnail_base64
from pdf_tools import convert_data_to_pdf

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("gui_app.log"),
        logging.StreamHandler()
    ]
)

# Constantes
SUPPORTED_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".heic"]
DEFAULT_CONTRACT = "039/2019 - PROVAC TERCEIRIZAÇÃO DE MÃO DE OBRA LTDA"

##############################################################################
# Função para computar o hash da imagem após redução de qualidade
##############################################################################
def compute_image_hash(img, quality=85):
    """
    Calcula um hash MD5 da imagem após salvá-la num buffer com qualidade reduzida.
    """
    buffer = BytesIO()
    try:
        img.save(buffer, format="JPEG", quality=quality)
    except Exception as e:
        logging.error(f"Erro ao salvar imagem para computar hash: {e}")
        return None
    data = buffer.getvalue()
    return hashlib.md5(data).hexdigest()

##############################################################################
# Worker Signals e Runnables (para processamento em segundo plano)
##############################################################################
class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int, int)  # current, total

class ProcessImagesRunnable(QRunnable):
    def __init__(self, directory, comments_dict, selected_images, report_date, contract_number, disable_states):
        super().__init__()
        self.directory = directory
        self.comments_dict = comments_dict
        self.selected_images = selected_images
        self.report_date = report_date
        self.contract_number = contract_number
        self.disable_states = disable_states
        self.signals = WorkerSignals()
        
    @pyqtSlot()
    def run(self):
        try:
            process_images_with_progress(
                self.directory,
                comments_dict=self.comments_dict,
                selected_images=self.selected_images,
                report_date=self.report_date,
                contract_number=self.contract_number,
                status_dict={},  # status_dict não é utilizado para a geração do HTML aqui
                progress_callback=self.signals.progress.emit,
                disable_states=self.disable_states
            )
            self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit((e.__class__, e, traceback.format_exc()))

class PDFGenerationRunnable(QRunnable):
    def __init__(self, directory, report_date, contract_number, pdf_path, include_last_page, comments_dict, status_dict, disable_states, selected_images):
        super().__init__()
        self.directory = directory
        self.report_date = report_date
        self.contract_number = contract_number
        self.pdf_path = pdf_path
        self.include_last_page = include_last_page
        self.comments_dict = comments_dict
        self.status_dict = status_dict
        self.disable_states = disable_states
        self.selected_images = selected_images  # Novo parâmetro para as imagens selecionadas
        self.signals = WorkerSignals()
        
    @pyqtSlot()
    def run(self):
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

##############################################################################
# Classe para armazenar o estado de cada imagem (Modelo de Dados)
##############################################################################
class ImageData:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.filename = file_path.name
        self.include = True
        self.status = "Não Concluído"
        self.comment = ""
        self.hash = None  # Será preenchido com o hash único da imagem

##############################################################################
# Rótulo Clicável
##############################################################################
class ClickableLabel(QLabel):
    clicked = pyqtSignal()
    
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

##############################################################################
# Widget Customizado para cada item da lista de imagens
##############################################################################
class ImageStatusItemWidget(QWidget):
    """
    Widget customizado para exibir os controles de cada imagem:
      - Checkbox para inclusão
      - Rótulo com o nome do arquivo (clicável)
      - Três radio buttons para o status: "Concluído", "Parcial", "Não Concluído"
    Utiliza um objeto ImageData para centralizar o estado.
    """
    def __init__(self, image_data: ImageData, parent=None):
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
        
        # Agrupando os radio buttons
        self.btnGroup = QButtonGroup(self)
        self.btnGroup.addButton(self.rbConcluido)
        self.btnGroup.addButton(self.rbParcial)
        self.btnGroup.addButton(self.rbNao)
        
        layout.addWidget(self.rbConcluido, 1)
        layout.addWidget(self.rbParcial, 1)
        layout.addWidget(self.rbNao, 1)
        
        # Conecta os sinais para atualizar o objeto ImageData usando partial
        self.chkInclude.stateChanged.connect(self.onIncludeChanged)
        self.rbConcluido.toggled.connect(functools.partial(self.onStatusChanged, status="Concluído"))
        self.rbParcial.toggled.connect(functools.partial(self.onStatusChanged, status="Parcial"))
        self.rbNao.toggled.connect(functools.partial(self.onStatusChanged, status="Não Concluído"))
        
    def onIncludeChanged(self, state):
        """Atualiza a flag de inclusão e aplica efeito de opacidade se não incluir."""
        self.image_data.include = (state == Qt.Checked)
        if state == Qt.Checked:
            self.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.5)
            self.setGraphicsEffect(effect)
            
    def onStatusChanged(self, checked, status):
        """Atualiza o status no ImageData quando o radio button é marcado."""
        if checked:
            self.image_data.status = status

##############################################################################
# Identificadores das Páginas do Wizard
##############################################################################
class WizardPage:
    SelectDirectoryPage = 0
    ImageListPage = 1
    FinishPage = 2

##############################################################################
# Página 1: Selecionar Diretório
##############################################################################
class PageSelectDirectory(QWizardPage):
    def __init__(self, parent=None):
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
        
    def on_browse(self):
        directory = QFileDialog.getExistingDirectory(self, "Selecione a pasta com as imagens")
        if directory:
            self.line_edit.setText(directory)
            
    def show_about_popup(self):
        QMessageBox.information(self, "Sobre", "Desenvolvido por Luiz Senko - DMA - DAV", QMessageBox.Ok)
        
    def validatePage(self):
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
        
    def nextId(self):
        return WizardPage.ImageListPage

##############################################################################
# Página 2: Lista de Imagens, Comentários e Pré-visualização
##############################################################################
class PageImageList(QWizardPage):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle("Selecionar Imagens, Definir Status, Adicionar Comentários e Data do Relatório")
        self.setSubTitle("Selecione as imagens, defina o status, insira comentários e informe a data do relatório.")
        
        # Layout principal: à esquerda a lista e área de comentários; à direita a pré-visualização
        main_layout = QHBoxLayout()
        self.setLayout(main_layout)
        
        # Layout esquerdo
        left_layout = QVBoxLayout()
        
        # Novo campo para a data do relatório
        date_layout = QHBoxLayout()
        date_label = QLabel("Data do Relatório:")
        # Define a data atual como padrão (formato dd/mm/aaaa)
        from datetime import datetime
        self.report_date_line_edit = QLineEdit(datetime.now().strftime("%d/%m/%Y"))
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.report_date_line_edit)
        left_layout.addLayout(date_layout)
        
        # --- Checkbox para desativar a função de estados ---
        self.checkbox_disable_states = QCheckBox("Desativar a função de estados")
        self.checkbox_disable_states.setChecked(False)
        left_layout.addWidget(self.checkbox_disable_states)
        self.checkbox_disable_states.toggled.connect(self.on_disable_states_toggled)
        # ----------------------------------------------------------------
        
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
        left_layout.addWidget(self.list_widget)
        
        # Área de comentário
        self.comment_label = QLabel("Comentário:")
        left_layout.addWidget(self.comment_label)
        self.comment_text = QTextEdit()
        left_layout.addWidget(self.comment_text)
        
        main_layout.addLayout(left_layout, 3)
        
        # Layout direito: pré-visualização da imagem
        right_layout = QVBoxLayout()
        self.preview_label = QLabel("Miniatura da Imagem")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(600, 600)
        self.preview_label.setStyleSheet("border: 1px solid black;")
        right_layout.addWidget(self.preview_label)
        main_layout.addLayout(right_layout, 2)
        
        # Dicionário para armazenar os objetos ImageData (chave: filename)
        self.image_data_map = {}
        
        # Conecta sinais para atualização
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        self.comment_text.textChanged.connect(self.save_comment_current)
        
        # Timer para debounce do salvamento on-the-fly (1 segundo)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(1000)  # 1000 ms = 1 segundo
        self.save_timer.timeout.connect(self.save_database)
        
    def get_report_date(self):
        """Retorna a data informada pelo usuário para o relatório."""
        return self.report_date_line_edit.text().strip()    
    
    def on_disable_states_toggled(self, checked):
        """
        Quando a checkbox for marcada ou desmarcada, desabilita ou habilita os radio buttons de cada item,
        aplicando um efeito de opacidade caso estejam desativados.
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
                    
    def initializePage(self):
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
                logging.error(f"Erro ao computar hash para {image_file.name}: {e}")
                image_data.hash = None
            self.image_data_map[image_data.filename] = image_data
            widget = ImageStatusItemWidget(image_data)
            widget.lblName.clicked.connect(lambda: self.comment_text.setFocus())
            
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)
        
        # Carrega informações previamente salvas (se houver)
        self.load_database()
        
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
            self.load_current_item_data()
            
    def load_database(self):
        """
        Carrega o arquivo JSON de banco de dados (imagens_db.json) e atualiza os dados
        de cada imagem (comentário, status e inclusão) com base no hash. Em seguida, atualiza os widgets
        para refletir essas informações na interface.
        """
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        db_path = Path(directory_text) / "imagens_db.json"
        if db_path.exists():
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db = json.load(f)
            except Exception as e:
                logging.error(f"Erro ao carregar banco de dados: {e}")
                db = {}
        else:
            db = {}

        # Atualiza os dados (ImageData) com as informações salvas
        for image_data in self.image_data_map.values():
            if image_data.hash and image_data.hash in db:
                saved = db[image_data.hash]
                image_data.comment = saved.get("comment", "")
                image_data.status = saved.get("status", "Não Concluído")
                image_data.include = saved.get("include", True)
        
        # Atualiza os widgets para refletir os dados carregados
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            widget = self.list_widget.itemWidget(item)
            image_data = widget.image_data
            
            # Atualiza os radio buttons conforme o status
            if image_data.status == "Concluído":
                widget.rbConcluido.setChecked(True)
            elif image_data.status == "Parcial":
                widget.rbParcial.setChecked(True)
            else:
                widget.rbNao.setChecked(True)
            
            # Atualiza o checkbox de inclusão
            widget.chkInclude.setChecked(image_data.include)
            
            # Se houver comentário, atualiza o estilo do rótulo para verde
            if image_data.comment.strip():
                widget.lblName.setStyleSheet("background-color: lightgreen;")
            else:
                widget.lblName.setStyleSheet("")
                
    def save_database(self):
        """
        Salva os comentários, status e o estado do checkbox (inclusão) de cada imagem em um arquivo JSON (imagens_db.json)
        na pasta de trabalho.
        """
        directory_text = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text().strip()
        db_path = Path(directory_text) / "imagens_db.json"
        db = {}
        for image_data in self.image_data_map.values():
            if image_data.hash:
                db[image_data.hash] = {
                    "comment": image_data.comment,
                    "status": image_data.status,
                    "include": image_data.include  # Estado do checkbox
                }
        try:
            with open(db_path, "w", encoding="utf-8") as f:
                json.dump(db, f, ensure_ascii=False, indent=4)
            logging.info("Banco de dados salvo com sucesso.")
        except Exception as e:
            logging.error(f"Erro ao salvar banco de dados: {e}")
            
    def on_item_changed(self, current, previous):
        if previous is not None:
            self.save_current_item_data(previous)
            # Cancela o timer de debounce e salva imediatamente ao trocar de imagem
            self.save_timer.stop()
            self.save_database()
        self.load_current_item_data()
        
    def load_current_item_data(self):
        current_item = self.list_widget.currentItem()
        if current_item:
            widget = self.list_widget.itemWidget(current_item)
            image_data = widget.image_data
            self.comment_text.blockSignals(True)
            self.comment_text.setText(image_data.comment)
            self.comment_text.blockSignals(False)
            
            # Carrega a pré-visualização da imagem
            try:
                _, img = get_exif_and_image(image_data.file_path)
                if img:
                    base64_thumb, _ = generate_thumbnail_base64(img, max_size=(600,600))
                    pixmap = QPixmap()
                    pixmap.loadFromData(base64.b64decode(base64_thumb))
                    self.preview_label.setPixmap(pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    self.preview_label.setText("Erro ao carregar imagem.")
            except Exception as e:
                self.preview_label.setText("Erro ao processar imagem.")
                
    def save_current_item_data(self, item):
        widget = self.list_widget.itemWidget(item)
        image_data = widget.image_data
        text = self.comment_text.toPlainText()
        image_data.comment = text
        if text.strip():
            widget.lblName.setStyleSheet("background-color: lightgreen;")
        else:
            widget.lblName.setStyleSheet("")
            
    def save_comment_current(self):
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
            # Inicia/reinicia o timer para salvamento com debounce
            self.save_timer.start()
            
    def get_selected_images(self):
        """Retorna uma lista dos nomes dos arquivos que estão marcados para inclusão."""
        return [filename for filename, data in self.image_data_map.items() if data.include]
        
    def get_status_dict(self):
        """Retorna um dicionário com o status de cada imagem."""
        return {filename: data.status for filename, data in self.image_data_map.items()}
        
    def get_comment_dict(self):
        """Retorna um dicionário com os comentários de cada imagem."""
        return {filename: data.comment for filename, data in self.image_data_map.items()}
        
    def get_disable_states(self):
        """Retorna True se a função de estados estiver desativada."""
        return self.checkbox_disable_states.isChecked()

##############################################################################
# Página 3: Concluir e Geração de PDF
##############################################################################
class PageFinish(QWizardPage):
    def __init__(self, parent=None):
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
        self.progress_dialog = None
        self.pdf_progress_dialog = None
        
    def nextId(self):
        return -1
        
    def validatePage(self):
        self.wizard().button(QWizard.FinishButton).setEnabled(False)
        self.run_image_processing()
        return False
        
    def run_image_processing(self):
        wizard = self.wizard()
        directory = Path(wizard.page(WizardPage.SelectDirectoryPage).line_edit.text())
        image_page = wizard.page(WizardPage.ImageListPage)
        comments_dict = image_page.get_comment_dict()
        selected_images = image_page.get_selected_images()
        status_dict = image_page.get_status_dict()
        # Utilize a data informada na página de imagens
        report_date = image_page.get_report_date()
        contract_number = DEFAULT_CONTRACT
        
        disable_states = image_page.get_disable_states()
        worker = ProcessImagesRunnable(directory, comments_dict, selected_images, report_date, contract_number, disable_states)
        worker.signals.progress.connect(self.on_progress_update)
        worker.signals.finished.connect(self.on_processing_finished)
        worker.signals.error.connect(self.on_processing_error)
        self.threadpool.start(worker)
        
        self.progress_dialog = QProgressDialog("Processando imagens e gerando HTML...", None, 0, 100, self)
        self.progress_dialog.setWindowTitle("Aguarde")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()
        
    def on_progress_update(self, current, total):
        if self.progress_dialog:
            self.progress_dialog.setValue(current * 100 // total)
            QApplication.processEvents()
            
    def on_processing_finished(self):
        if self.progress_dialog:
            self.progress_dialog.close()
        if self.checkbox_generate_pdf.isChecked():
            self.run_pdf_generation(self.checkbox_include_signature.isChecked())
        else:
            self.show_pdf_generated_message()
            
    def on_processing_error(self, error_info):
        if self.progress_dialog:
            self.progress_dialog.close()
        QMessageBox.critical(self, "Erro no Processamento", f"Erro: {error_info[1]}", QMessageBox.Ok)
        self.wizard().close()
        
    def run_pdf_generation(self, include_signature):
        wizard = self.wizard()
        directory = Path(wizard.page(WizardPage.SelectDirectoryPage).line_edit.text())
        # Utilize a data informada na página de imagens
        report_date = wizard.page(WizardPage.ImageListPage).get_report_date()
        contract_number = DEFAULT_CONTRACT
        pdf_path = directory / f"{datetime.now().strftime('%y%m%d')}_Relatorio.pdf"
        image_page = wizard.page(WizardPage.ImageListPage)
        
        comments_dict = image_page.get_comment_dict()
        status_dict = image_page.get_status_dict()
        disable_states = image_page.get_disable_states()
        selected_images = image_page.get_selected_images()  # Reutiliza a mesma lista filtrada usada no HTML
        
        worker = PDFGenerationRunnable(
            directory, report_date, contract_number, pdf_path, include_signature,
            comments_dict, status_dict, disable_states, selected_images
        )
        worker.signals.finished.connect(self.on_pdf_finished)
        worker.signals.error.connect(self.on_pdf_error)
        self.threadpool.start(worker)
        
        self.pdf_progress_dialog = QProgressDialog("Gerando PDF...", None, 0, 0, self)
        self.pdf_progress_dialog.setWindowTitle("Aguarde")
        self.pdf_progress_dialog.setWindowModality(Qt.WindowModal)
        self.pdf_progress_dialog.setCancelButton(None)
        self.pdf_progress_dialog.show()
        
    def on_pdf_finished(self):
        if self.pdf_progress_dialog:
            self.pdf_progress_dialog.close()
        self.show_pdf_generated_message()
        
    def on_pdf_error(self, error_info):
        if self.pdf_progress_dialog:
            self.pdf_progress_dialog.close()
        QMessageBox.critical(self, "Erro na Geração de PDF", f"Erro: {error_info[1]}", QMessageBox.Ok)
        self.wizard().close()
        
    def show_pdf_generated_message(self):
        directory = self.wizard().page(WizardPage.SelectDirectoryPage).line_edit.text()
        nome_pdf = f"{datetime.now().strftime('%y%m%d')}_Relatorio.pdf"
        QMessageBox.information(self, "PDF Gerado", f"PDF gerado com sucesso em:\n{directory}/{nome_pdf}", QMessageBox.Ok)
        self.wizard().close()

##############################################################################
# Classe Principal do Wizard
##############################################################################
class MyWizard(QWizard):
    def __init__(self, parent=None):
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
        
    def on_current_id_changed(self, current_id):
        if current_id == WizardPage.ImageListPage:
            self.resize(*self.image_list_page_size)
        else:
            self.resize(*self.default_size)
        self.center()
        
    def center(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            screen_geometry = screen.availableGeometry()
            center_point = screen_geometry.center()
            frame_geometry = self.frameGeometry()
            frame_geometry.moveCenter(center_point)
            self.move(frame_geometry.topLeft())
            
    def closeEvent(self, event):
        # Ao fechar o wizard, garante que os dados sejam salvos.
        image_page = self.page(WizardPage.ImageListPage)
        if image_page:
            image_page.save_database()
        event.accept()

##############################################################################
# Função de Execução do GUI
##############################################################################
def run_gui():
    app = QApplication(sys.argv)
    wizard = MyWizard()
    wizard.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    run_gui()
