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

# Importa seu pdf_tools inalterado
import pdf_tools

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def create_first_and_last_page_in_memory(report_date, config, include_last_page=True):
    """
    Gera APENAS DUAS PÁGINAS (capa e assinatura) em memória, 
    usando as MESMAS funções auxiliares do pdf_tools (draw_first_page, draw_signature_section).
    Não gera as páginas intermediárias do relatório. 
    Retorna bytes de PDF (em memória).
    """
    pdf_buffer = io.BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    # ------------------ PÁGINA 1 (Capa) ------------------ #
    # Usa a mesma lógica do pdf_tools.draw_first_page
    pdf_tools.draw_first_page(c, width, height, report_date, config)
    # Opcional: numeração
    c.setFont("Helvetica", 8)
    c.drawCentredString(width / 2, 5 * mm, "Página 1 de 2" if include_last_page else "Página 1 de 1")
    c.showPage()

    if include_last_page:
        # ------------------ PÁGINA FINAL (assinatura) ------------------ #
        # Usa pdf_tools.draw_signature_section
        text_objects = {
            "location_date": f"{config.get('address','')}, {report_date}",
            "sign1": config.get("sign1","PREPOSTO CONTRATANTE"),
            "sign1_name": config.get("sign1_name",""),
            "sign2": config.get("sign2","PREPOSTO CONTRATADA"),
            "sign2_name": config.get("sign2_name","Laércio P. Oliveira"),
        }
        pdf_tools.draw_signature_section(c, width, height, text_objects)
        # Numeração
        c.setFont("Helvetica", 8)
        c.drawCentredString(width / 2, 5 * mm, "Página 2 de 2")
        c.showPage()

    c.save()
    pdf_buffer.seek(0)
    pdf_data = pdf_buffer.read()
    return pdf_data


class TemplateEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editor de Template (Prévia: 1ª e Última Pág.)")
        self.resize(1300, 700)
        
        # Definição de arquivos de config
        self.default_config_path = Path(__file__).parent / "pdf_config_default.json"
        self.user_config_path = Path(__file__).parent / "pdf_config_user.json"

        # Carrega config
        self.config = self.load_user_config()
        self.line_edits = {}

        main_layout = QVBoxLayout(self)

        # Layout horizontal -> Editor (esq) + Prévia (dir)
        central_layout = QHBoxLayout()

        # ========== Esquerda: Editor de Campos ========== #
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_widget)

        self.populate_fields()  # cria lineEdits

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

        # Botões
        btn_layout = QHBoxLayout()
        self.btn_import = QPushButton("Importar")
        self.btn_export = QPushButton("Exportar")
        self.btn_restore = QPushButton("Restaurar")
        self.btn_preview = QPushButton("Atualizar Prévia")

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

        # Timer para prévia em tempo real (opcional)
        self.preview_update_timer = QTimer()
        self.preview_update_timer.setInterval(500)  # ms
        self.preview_update_timer.setSingleShot(True)
        self.preview_update_timer.timeout.connect(self.update_pdf_preview)

        # Conecta textChanged de cada lineEdit
        for le in self.line_edits.values():
            le.textChanged.connect(self.schedule_preview_update)

        # Gera prévia inicial
        self.update_pdf_preview()

    # -------------------- Funções de Config -------------------- #
    def populate_fields(self):
        # Limpa layout anterior
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

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
        """Aguarda 0.5s após digitação para atualizar a prévia."""
        self.preview_update_timer.start()

    def load_default_config(self):
        # Tenta ler default_pdf_config.json
        if self.default_config_path.exists():
            try:
                with self.default_config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                QMessageBox.warning(self, "Aviso", "Não foi possível ler config padrão.")
                return pdf_tools.load_pdf_config()  # fallback
        else:
            return pdf_tools.load_pdf_config()  # fallback

    def load_user_config(self):
        # Tenta ler pdf_config.json do usuário
        if self.user_config_path.exists():
            try:
                with self.user_config_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                QMessageBox.warning(self, "Aviso", "Config corrompida. Usando padrão.")
                return self.load_default_config()
        else:
            default_c = self.load_default_config()
            try:
                with self.user_config_path.open("w", encoding="utf-8") as f:
                    json.dump(default_c, f, ensure_ascii=False, indent=4)
            except:
                pass
            return default_c

    def import_config(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Importar Config", "", "JSON Files (*.json)")
        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    imported = json.load(f)
                self.config = imported
                self.populate_fields()
                QMessageBox.information(self, "Importar", "Configurações importadas.")
                self.update_pdf_preview()
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao importar: {e}")

    def export_config(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Exportar Config", "", "JSON Files (*.json)")
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
        default_c = self.load_default_config()
        try:
            with self.user_config_path.open("w", encoding="utf-8") as f:
                json.dump(default_c, f, ensure_ascii=False, indent=4)
            self.config = default_c
            self.populate_fields()
            QMessageBox.information(self, "Restaurar", "Configurações padrão restauradas.")
            self.update_pdf_preview()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao restaurar: {e}")

    def save(self):
        # Salva no pdf_config.json
        for k, le in self.line_edits.items():
            self.config[k] = le.text()
        try:
            with self.user_config_path.open("w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao salvar: {e}")

    # -------------------- Prévia da 1ª e Última Página -------------------- #
    def update_pdf_preview(self):
        # Atualiza self.config a partir dos lineEdits
        for k, le in self.line_edits.items():
            self.config[k] = le.text()

        # Gera PDF em memória (apenas capa e última página)
        report_date = "13/02/2025"  # Exemplo
        pdf_data = create_first_and_last_page_in_memory(
            report_date=report_date,
            config=self.config,
            include_last_page=True
        )

        # Abre o PDF com PyMuPDF
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        num_pages = len(doc)
        print("[DEBUG] PDF com", num_pages, "página(s) geradas para prévia.")

        # Limpa a prévia anterior
        while self.preview_layout.count():
            item = self.preview_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if num_pages == 0:
            self.preview_layout.addWidget(QLabel("Nenhuma página gerada!"))
            return

        # Renderiza a primeira (página 0)
        first_img = self._page_to_pixmap(doc, 0)
        if first_img:
            lbl_first = QLabel()
            lbl_first.setAlignment(Qt.AlignCenter)
            lbl_first.setPixmap(first_img)
            self.preview_layout.addWidget(lbl_first)
        else:
            self.preview_layout.addWidget(QLabel("Falha ao renderizar 1ª página."))

        # Renderiza a última (página num_pages-1), se houver mais de 1
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
        """Converte doc[page_index] para QPixmap."""
        if page_index < 0 or page_index >= len(doc):
            return None
        page = doc.load_page(page_index)
        pix = page.get_pixmap(alpha=False, dpi=dpi)
        qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        qimg = qimg.copy()
        if qimg.isNull():
            return None
        return QPixmap.fromImage(qimg)