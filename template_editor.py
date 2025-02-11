# template_editor.py

import json
from pathlib import Path
from PyQt5.QtWidgets import (
    QDialog, QScrollArea, QVBoxLayout, QHBoxLayout, QLineEdit, QLabel,
    QDialogButtonBox, QWidget, QMessageBox
)

class TemplateEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar template")
        self.resize(400, 300)
        
        # Carrega a configuração do pdf_config.json
        config_path = Path(__file__).parent / "pdf_config.json"
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    self.config = json.load(f)
            except Exception as e:
                QMessageBox.critical(self, "Erro", f"Erro ao carregar o template: {e}")
                self.config = {}
        else:
            self.config = {}
        
        self.line_edits = {}  # Dicionário para armazenar os QLineEdit por chave
        
        main_layout = QVBoxLayout(self)
        
        # Cria uma área rolável para a lista de configurações
        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        # Para cada par chave-valor do config, cria uma linha com um QLineEdit e um QLabel
        for key, value in self.config.items():
            row_layout = QHBoxLayout()
            # Caixa de texto com o valor atual
            le = QLineEdit(str(value))
            row_layout.addWidget(le)
            # Rótulo com o nome da variável
            label = QLabel(key)
            row_layout.addWidget(label)
            scroll_layout.addLayout(row_layout)
            self.line_edits[key] = le
        
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
        
        # Botões: Salvar e Cancelar centralizados
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.save)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
    
    def save(self):
        # Atualiza o dicionário de configuração com os valores dos QLineEdit
        for key, le in self.line_edits.items():
            self.config[key] = le.text()
        # Salva no pdf_config.json
        config_path = Path(__file__).parent / "pdf_config.json"
        try:
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro ao salvar o template: {e}")
            return
        self.accept()
