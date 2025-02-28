#macro_editor.py

import json, os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QLabel, QHBoxLayout,
    QPushButton, QFileDialog, QMessageBox
)

# Valores padrão (hardcoded) para os macros. Estes são usados caso não haja macros salvas.
DEFAULT_MACROS = {
    "b1": "Macro padrão 1",
    "b2": "Macro padrão 2",
    "b3": "Macro padrão 3",
    "b4": "Macro padrão 4",
    "b5": "Macro padrão 5",
    "b6": "Macro padrão 6",
    "b7": "Macro padrão 7",
    "b8": "Macro padrão 8",
    "b9": "Macro padrão 9",
    "b0": "Macro padrão 0",
}

class MacroEditorDialog(QDialog):
    """
    Diálogo para edição dos macros.
    
    Este diálogo permite ao usuário visualizar, editar, importar, exportar, salvar e restaurar
    os macros utilizados no sistema.
    
    O layout consiste em:
      - Um formulário com campos de edição (QLineEdit) para cada macro.
      - Um conjunto de botões para importar, exportar, salvar e restaurar os macros.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar Macros")
        self.resize(800, 400)
        # Inicialmente, carrega os macros padrão (cópia dos defaults)
        self.macros = DEFAULT_MACROS.copy()
        self.init_ui()
        # Tenta carregar os macros existentes do arquivo "macros.json"
        self.load_macros_from_file()
        # Atualiza os campos de edição com os valores atuais dos macros
        self.load_macros()

    def init_ui(self):
        """
        Inicializa a interface do diálogo.
        
        Cria o layout principal, os campos de edição para cada macro e os botões de ação.
        """
        layout = QVBoxLayout(self)

        # Cria um formulário (layout em forma de tabela) para os campos de edição
        self.form_layout = QFormLayout()
        self.edit_b1 = QLineEdit()
        self.edit_b2 = QLineEdit()
        self.edit_b3 = QLineEdit()
        self.edit_b4 = QLineEdit()
        self.edit_b5 = QLineEdit()
        self.edit_b6 = QLineEdit()
        self.edit_b7 = QLineEdit()
        self.edit_b8 = QLineEdit()
        self.edit_b9 = QLineEdit()
        self.edit_b0 = QLineEdit()

        # Adiciona cada campo com um rótulo correspondente ao formulário
        self.form_layout.addRow(QLabel("Num1:"), self.edit_b1)
        self.form_layout.addRow(QLabel("Num2:"), self.edit_b2)
        self.form_layout.addRow(QLabel("Num3:"), self.edit_b3)
        self.form_layout.addRow(QLabel("Num4:"), self.edit_b4)
        self.form_layout.addRow(QLabel("Num5:"), self.edit_b5)
        self.form_layout.addRow(QLabel("Num6:"), self.edit_b6)
        self.form_layout.addRow(QLabel("Num7:"), self.edit_b7)
        self.form_layout.addRow(QLabel("Num8:"), self.edit_b8)
        self.form_layout.addRow(QLabel("Num9:"), self.edit_b9)
        self.form_layout.addRow(QLabel("Num0:"), self.edit_b0)

        layout.addLayout(self.form_layout)

        # Layout horizontal para os botões de ação
        button_layout = QHBoxLayout()
        self.btn_import = QPushButton("Importar")
        self.btn_export = QPushButton("Exportar")
        self.btn_save = QPushButton("Salvar")
        self.btn_restore = QPushButton("Restaurar")
        button_layout.addWidget(self.btn_import)
        button_layout.addWidget(self.btn_export)
        button_layout.addWidget(self.btn_save)
        button_layout.addWidget(self.btn_restore)
        layout.addLayout(button_layout)

        # Conecta os botões com suas respectivas funções
        self.btn_import.clicked.connect(self.import_macros)
        self.btn_export.clicked.connect(self.export_macros)
        self.btn_save.clicked.connect(self.save_macros)
        self.btn_restore.clicked.connect(self.restore_defaults)

    def load_macros(self):
        """
        Carrega os valores atuais dos macros nos campos de edição.
        """
        self.edit_b1.setText(self.macros.get("b1", ""))
        self.edit_b2.setText(self.macros.get("b2", ""))
        self.edit_b3.setText(self.macros.get("b3", ""))
        self.edit_b4.setText(self.macros.get("b4", ""))
        self.edit_b5.setText(self.macros.get("b5", ""))
        self.edit_b6.setText(self.macros.get("b6", ""))
        self.edit_b7.setText(self.macros.get("b7", ""))
        self.edit_b8.setText(self.macros.get("b8", ""))
        self.edit_b9.setText(self.macros.get("b9", ""))
        self.edit_b0.setText(self.macros.get("b0", ""))

    def import_macros(self):
        """
        Importa os macros de um arquivo JSON selecionado pelo usuário.
        
        Após a importação, os macros são atualizados nos campos de edição e salvos no arquivo padrão.
        """
        filename, _ = QFileDialog.getOpenFileName(
            self, "Importar macros", "", "JSON Files (*.json)"
        )
        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Atualiza os macros com os valores importados
                self.macros.update(data)
                self.load_macros()
                # Salva os macros importados no arquivo padrão (macros.json)
                if self.save_to_default_file():
                    QMessageBox.information(self, "Importar", "Macros importadas e salvas com sucesso.")
            except Exception as e:
                QMessageBox.warning(self, "Erro", f"Falha ao importar macros: {e}")

    def export_macros(self):
        """
        Exporta os macros atuais para um arquivo JSON.
        
        Os valores dos campos de edição são atualizados no dicionário de macros antes da exportação.
        """
        # Atualiza os valores atuais dos campos nos macros
        self.macros["b1"] = self.edit_b1.text()
        self.macros["b2"] = self.edit_b2.text()
        self.macros["b3"] = self.edit_b3.text()
        self.macros["b4"] = self.edit_b4.text()
        self.macros["b5"] = self.edit_b5.text()
        self.macros["b6"] = self.edit_b6.text()
        self.macros["b7"] = self.edit_b7.text()
        self.macros["b8"] = self.edit_b8.text()
        self.macros["b9"] = self.edit_b9.text()
        self.macros["b0"] = self.edit_b0.text()

        filename, _ = QFileDialog.getSaveFileName(
            self, "Exportar macros", "", "JSON Files (*.json)"
        )
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(self.macros, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, "Exportar", "Macros exportadas com sucesso.")
            except Exception as e:
                QMessageBox.warning(self, "Erro", f"Falha ao exportar macros: {e}")

    def save_macros(self):
        """
        Salva os macros atuais no arquivo padrão (macros.json).
        
        Os valores dos campos de edição são atualizados no dicionário de macros e salvos.
        """
        self.macros["b1"] = self.edit_b1.text()
        self.macros["b2"] = self.edit_b2.text()
        self.macros["b3"] = self.edit_b3.text()
        self.macros["b4"] = self.edit_b4.text()
        self.macros["b5"] = self.edit_b5.text()
        self.macros["b6"] = self.edit_b6.text()
        self.macros["b7"] = self.edit_b7.text()
        self.macros["b8"] = self.edit_b8.text()
        self.macros["b9"] = self.edit_b9.text()
        self.macros["b0"] = self.edit_b0.text()

        if self.save_to_default_file():
            QMessageBox.information(self, "Salvar", "Macros salvas com sucesso no arquivo macros.json.")
    
    def load_macros_from_file(self):
        """
        Carrega os macros do arquivo padrão "macros.json", se existir.
        
        Atualiza o dicionário de macros com os valores lidos do arquivo.
        """
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macros.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.macros = json.load(f)
            except Exception as e:
                QMessageBox.warning(self, "Erro", f"Falha ao carregar macros: {e}")

    def save_to_default_file(self):
        """
        Salva os macros atuais no arquivo padrão "macros.json", localizado no mesmo diretório deste script.

        Retorna:
            True se a operação for bem-sucedida, False caso contrário.
        """
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "macros.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.macros, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            QMessageBox.warning(self, "Erro", f"Falha ao salvar macros: {e}")
            return False

    def restore_defaults(self):
        """
        Restaura os macros para os valores padrão definidos em DEFAULT_MACROS e atualiza os campos de edição.
        """
        self.macros = DEFAULT_MACROS.copy()
        self.load_macros()
        QMessageBox.information(self, "Restaurar", "Macros restauradas para os valores padrão.")

if __name__ == "__main__":
    # Caso o script seja executado de forma independente, inicia o diálogo para teste
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dialog = MacroEditorDialog()
    dialog.exec_()
