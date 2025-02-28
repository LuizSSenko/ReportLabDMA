# configEditor.py
import json
import io
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QScrollArea, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel,
    QDialogButtonBox, QWidget, QMessageBox, QPushButton, QFileDialog
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage

import fitz  # PyMuPDF

# Importa funções do módulo pdf_tools (usado para desenhar as páginas de capa e assinatura)
from req_classes import pdf_tools
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

# Importa o diálogo para edição de macros e a classe de configuração
from req_classes.macro_editor import MacroEditorDialog
from req_classes.settingsClass import Settings  # Classe que gerencia a configuração (Report_config.json)


def create_first_and_last_page_in_memory(report_date, config, include_last_page=True):
    """
    Gera, em memória, APENAS DUAS PÁGINAS do PDF:
      - A primeira página (capa) utilizando as funções auxiliares do pdf_tools.
      - A última página (assinatura), se a flag include_last_page estiver True.

    Retorna os bytes do PDF gerado em memória.

    Args:
        report_date (str): Data do relatório.
        config (dict): Dicionário de configuração com textos e parâmetros do relatório.
        include_last_page (bool, optional): Se True, inclui a página de assinatura. Default é True.
    """
    pdf_buffer = io.BytesIO()   # Buffer em memória para armazenar o PDF
    c = canvas.Canvas(pdf_buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    # ------------------ PÁGINA 1 (Capa) ------------------ #
    # Desenha a capa utilizando a função draw_first_page do pdf_tools
    pdf_tools.draw_first_page(c, width, height, report_date, config)
    # Adiciona uma pequena indicação de numeração de página
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 5 * mm, "Página 1 de 2" if include_last_page else "Página 1 de 1")
    c.showPage()

    if include_last_page:
        # ------------------ PÁGINA FINAL (Assinatura) ------------------ #
        # Define um dicionário com os textos necessários para a página de assinatura
        text_objects = {
            "location_date": f"{config.get('address','')}, {report_date}",
            "sign1": config.get("sign1", "PREPOSTO CONTRATANTE"),
            "sign1_name": config.get("sign1_name", ""),
            "sign2": config.get("sign2", "PREPOSTO CONTRATADA"),
            "sign2_name": config.get("sign2_name", "Laércio P. Oliveira"),
        }

        # Desenha a página de assinatura utilizando a função draw_signature_section do pdf_tools
        pdf_tools.draw_signature_section(c, width, height, text_objects)
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, 5 * mm, "Página 2 de 2")
        c.showPage()

    c.save()    # Finaliza e salva o PDF no buffer
    pdf_buffer.seek(0)
    return pdf_buffer.read()


class ConfigEditorDialog(QDialog):
    """
    Diálogo para editar as configurações do relatório.
    
    Este diálogo exibe:
      - Um editor de campos para cada parâmetro da configuração.
      - Uma área de prévia que renderiza a capa e a página de assinatura do PDF.
      - Botões para importar, exportar, restaurar a configuração padrão e atualizar a prévia.
      - Um botão para editar macros.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor de Configurações (Prévia: 1ª e Última Pág.)")
        self.resize(1300, 700)
        
        # Cria a instância da classe Settings, que carrega o arquivo de configuração (Report_config.json)
        self.settings = Settings()
        self.config = self.settings.config

        # Dicionário para armazenar os QLineEdit criados dinamicamente para cada campo da configuração
        self.line_edits = {}

        main_layout = QVBoxLayout(self)

        # Layout central dividido horizontalmente: Editor de Campos (esquerda) e Prévia do PDF (direita)
        central_layout = QHBoxLayout()

        # ========== Esquerda: Editor de Campos ========== #
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_widget)

        # Popula os campos do editor com base nos itens da configuração
        self.populate_fields()  

        self.scroll_area.setWidget(scroll_widget)
        central_layout.addWidget(self.scroll_area, stretch=2)

        # ========== Direita: Área de Prévia ========== #
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setWidget(self.preview_container)

        central_layout.addWidget(self.preview_scroll, stretch=3)
        main_layout.addLayout(central_layout)

        # Botões de ação e operações diversas
        btn_layout = QHBoxLayout()

        # Botão para abrir o editor de macros
        self.btn_edit_macros = QPushButton("Editar Macros")
        self.btn_edit_macros.clicked.connect(self.open_macro_editor)
        btn_layout.addWidget(self.btn_edit_macros)

        # Botões para importar, exportar, restaurar configurações e atualizar a prévia
        self.btn_import = QPushButton("Importar")
        self.btn_export = QPushButton("Exportar")
        self.btn_restore = QPushButton("Restaurar")
        self.btn_preview = QPushButton("Atualizar Prévia")

        # Botões padrão de diálogo (Save e Cancel)
        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self.save)
        btn_box.rejected.connect(self.reject)

        self.btn_import.clicked.connect(self.import_config)
        self.btn_export.clicked.connect(self.export_config)
        self.btn_restore.clicked.connect(self.restore_default)
        self.btn_preview.clicked.connect(self.update_pdf_preview)
        btn_layout.addWidget(self.btn_import)
        btn_layout.addWidget(self.btn_export)
        btn_layout.addWidget(self.btn_restore)
        btn_layout.addWidget(self.btn_preview)
        btn_layout.addWidget(btn_box)
        main_layout.addLayout(btn_layout)

        # Timer para atualização em tempo real da prévia (delay de 500ms)
        self.preview_update_timer = QTimer()
        self.preview_update_timer.setInterval(500)  # milissegundos
        self.preview_update_timer.setSingleShot(True)
        self.preview_update_timer.timeout.connect(self.update_pdf_preview)

        # Conecta cada QLineEdit para agendar a atualização da prévia quando o texto for alterado
        for le in self.line_edits.values():
            le.textChanged.connect(self.schedule_preview_update)

        # Gera a prévia inicial do PDF
        self.update_pdf_preview()

    # -------------------- Funções de Configuração -------------------- #
    def populate_fields(self):
        """
        Cria dinamicamente um campo de edição (QLineEdit) para cada item da configuração.
        Remove os widgets antigos antes de criar novos.
        """
        # Remove widgets existentes para evitar duplicação
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Para cada chave-valor na configuração, cria um rótulo e um campo de edição
        for key, val in self.config.items():
            row = QHBoxLayout()
            lbl = QLabel(key)
            lbl.setFixedWidth(90)
            row.addWidget(lbl)
            le = QLineEdit(str(val))
            row.addWidget(le)
            self.line_edits[key] = le
            self.scroll_layout.addLayout(row)

    def schedule_preview_update(self):
        """
        Agenda a atualização da prévia do PDF 0,5 segundos após a última alteração.
        """
        self.preview_update_timer.start()

    def import_config(self):
        """
        Abre um diálogo para importar uma configuração de um arquivo JSON.
        Após importar, atualiza os campos do editor e a prévia.
        """
        file_path, _ = QFileDialog.getOpenFileName(self, "Importar Config", "", "JSON Files (*.json)")
        if file_path:
            try:
                # Utiliza o método da classe Settings para importar a configuração
                self.settings.import_config(file_path)
                self.config = self.settings.config
                self.populate_fields()
                QMessageBox.information(self, "Importar", "Configurações importadas.")
                self.update_pdf_preview()
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao importar: {e}")

    def export_config(self):
        """
        Abre um diálogo para exportar a configuração atual para um arquivo JSON.
        """
        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar Config", "", "JSON Files (*.json)")

        # Atualiza a configuração com os valores atuais dos campos de edição
        if file_path:
            for k, le in self.line_edits.items():
                self.config[k] = le.text()
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, ensure_ascii=False, indent=4)
                QMessageBox.information(self, "Exportar", "Configurações exportadas.")
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao exportar: {e}")

    def restore_default(self):
        """
        Restaura a configuração padrão utilizando o método da classe Settings e atualiza os campos.
        """
        try:
            # Restaura a configuração padrão via método da classe
            self.settings.restore_config()
            self.config = self.settings.config
            self.populate_fields()
            QMessageBox.information(self, "Restaurar", "Configurações padrão restauradas.")
            self.update_pdf_preview()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao restaurar: {e}")

    def save(self):
        """
        Salva as configurações atualizadas utilizando o método da classe Settings.
        Se a operação for bem-sucedida, o diálogo é aceito (fechado).
        """
        # Atualiza a configuração com os valores dos QLineEdit
        for k, le in self.line_edits.items():
            self.config[k] = le.text()
        try:
            # Salva a nova configuração usando o método da classe
            self.settings.save_config(self.config)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao salvar: {e}")

    # -------------------- Prévia da 1ª e Última Página -------------------- #
    def update_pdf_preview(self):
        """
        Atualiza a prévia do PDF exibida na área de visualização.
        
        Esta função:
          - Atualiza a configuração com os valores atuais dos campos;
          - Gera o PDF (apenas a primeira e a última página) em memória;
          - Renderiza as páginas utilizando PyMuPDF (fitz) e as exibe como imagens (QPixmap).
        """
        # Atualiza a config com os valores atuais dos QLineEdit
        for k, le in self.line_edits.items():
            self.config[k] = le.text()

        report_date = "13/02/2025"  # Data de exemplo para a prévia
        pdf_data = create_first_and_last_page_in_memory(
            report_date=report_date,
            config=self.config,
            include_last_page=True
        )

        # Abre o PDF em memória com PyMuPDF para renderizar as páginas da prévia
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        num_pages = len(doc)
        print("[DEBUG] PDF com", num_pages, "página(s) geradas para prévia.")

        # Limpa a prévia atual removendo os widgets existentes
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # Se não houver páginas geradas, exibe mensagem de erro
        if num_pages == 0:
            self.preview_layout.addWidget(QLabel("Nenhuma página gerada!"))
            return

        # Renderiza e exibe a primeira página
        first_img = self._page_to_pixmap(doc, 0)
        if first_img:
            lbl_first = QLabel()
            lbl_first.setAlignment(Qt.AlignCenter)
            lbl_first.setPixmap(first_img)
            self.preview_layout.addWidget(lbl_first)
        else:
            self.preview_layout.addWidget(QLabel("Falha ao renderizar 1ª página."))

        # Se houver mais de uma página, renderiza e exibe a última página
        if num_pages > 1:
            last_img = self._page_to_pixmap(doc, num_pages - 1)
            if last_img:
                lbl_last = QLabel()
                lbl_last.setAlignment(Qt.AlignCenter)
                lbl_last.setPixmap(last_img)
                self.preview_layout.addWidget(lbl_last)
            else:
                self.preview_layout.addWidget(QLabel("Falha ao renderizar última página."))
        else:
            self.preview_layout.addWidget(QLabel("Só existe 1 página (capa)."))

    def _page_to_pixmap(self, doc, page_index, dpi=65):
        """
        Converte a página do PDF para QPixmap, para exibição na prévia.

        Args:
            doc: Documento PDF aberto com fitz.
            page_index (int): Índice da página a ser renderizada.
            dpi (int, optional): Resolução da renderização. Default é 65.

        Returns:
            QPixmap ou None se ocorrer erro.
        """
        if page_index < 0 or page_index >= len(doc):
            return None
        page = doc.load_page(page_index)
        pix = page.get_pixmap(alpha=False, dpi=dpi)
        qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        qimg = qimg.copy()  # Garante que a imagem não seja invalidada
        if qimg.isNull():
            return None
        return QPixmap.fromImage(qimg)
    
    def open_macro_editor(self):
        """
        Abre o diálogo de edição de macros. Após editar, salva as macros no arquivo 'macros.json'.
        """
        dialog = MacroEditorDialog(self)
        if dialog.exec_():
            script_dir = Path(__file__).parent
            macros_path = script_dir / "macros.json"
            try:
                with open(macros_path, "w", encoding="utf-8") as f:
                    json.dump(dialog.macros, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, "Salvar Macros", "Macros salvas com sucesso.")
            except Exception as e:
                QMessageBox.warning(self, "Erro", f"Falha ao salvar macros: {e}")
