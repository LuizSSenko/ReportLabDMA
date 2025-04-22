import json, os
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QRadioButton, QButtonGroup, QDialogButtonBox,
    QLineEdit, QWidget, QScrollArea, QHBoxLayout, QMessageBox, QTextEdit, QPushButton, QFileDialog
)
from PyQt5.QtCore import Qt

class QuestionarioPodaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Questionário de Poda")
        self.setMinimumSize(600, 600)
        
        # Conjunto padrão de perguntas com a chave "color_inverted"
        self.default_questions = [
            {"text": "Utilização de EPI (item 12.12 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Utilização de EPC (item 12.12 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Equipamento de motosserra pequeno, para poda de galharia, presente e conforme? (Item 12.17.a do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Equipamento de motosserra grande, para grandes diâmetros de madeira, presente e conforme? (Item 12.17.b do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Equipamento motopoda do tipo telescópica, para podas altas, presente e conforme? (Item 12.17.c do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Caminhão munck está conforme? (Item 12.3 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Veículo para acondicionamento e transporte de resíduos está presente e conforme? (Item 12.17.f do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Triturador de galhos está presente e conforme? (Item 12.11 e 12.17.e do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "A técnica de poda de árvore e galhos foi adequada? (Item 12.9 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "A árvore ficou equilibrada após a poda? (Item 12.6 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Triturador de galhos presente? (Item 12.11 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "A área ficou limpa após a execução do serviço?", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Encarregado presente e atuante durante toda a execução dos serviços?", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Nome do encarregado:", "type": "text", "color_inverted": False},
            {"text": "As toras com mais de 15cm, foram cortadas em seções com menos de 2m de comprimento? (Item 12.14.1 do contrato)", "type": "radio", "requires_justification": True, "justify_on": "Não", "default": "Sim", "color_inverted": False},
            {"text": "Houve alguma ocorrência de danos ao patrimônio?", "type": "radio", "requires_justification": True, "justify_on": "Sim", "default": "Não", "color_inverted": True},
            {"text": "Houve quebra de algum equipamento utilizado?", "type": "radio", "requires_justification": True, "justify_on": "Sim", "default": "Não", "color_inverted": True}
        ]

        # Tenta carregar perguntas de 'questionario.json', senão, usa as perguntas padrão
        base_dir = os.path.dirname(os.path.abspath(__file__))
        json_file = os.path.join(base_dir, "questionario.json")
        try:
            if os.path.exists(json_file):
                print(f"Carregando perguntas de {json_file}")
                # Carrega o arquivo JSON e verifica se é uma lista de perguntas
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self.questions = data
                else:
                    raise ValueError("O JSON não contém uma lista de perguntas")
            else:
                self.questions = list(self.default_questions)
                print(f"Arquivo {json_file} não encontrado. Usando perguntas padrão.")
        except Exception as e:
            QMessageBox.warning(self, "Carregar Questionário",
                                f"Não foi possível carregar perguntas de {json_file}: {e}\nUsando questionário padrão.")
            self.questions = list(self.default_questions)

        self.question_widgets = []  # Guarda referências dos widgets criados
        self.init_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        
        # Cria um QScrollArea para acomodar todas as perguntas
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.scroll_layout = QVBoxLayout(self.content_widget)
        self.populate_fields()  # Cria os widgets com base em self.questions
        self.scroll_layout.addStretch()
        self.scroll_area.setWidget(self.content_widget)
        self.main_layout.addWidget(self.scroll_area)
        
        # Cria um QHBoxLayout para agrupar os botões na mesma linha
        buttons_layout = QHBoxLayout()
        
        self.btn_importar = QPushButton("Importar")
        self.btn_exportar = QPushButton("Exportar")
        self.btn_restaurar = QPushButton("Restaurar")
        buttons_layout.addWidget(self.btn_importar)
        buttons_layout.addWidget(self.btn_exportar)
        buttons_layout.addWidget(self.btn_restaurar)
        
        # Botões padrão (OK e Cancelar)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons_layout.addWidget(self.button_box)
        self.main_layout.addLayout(buttons_layout)
        
        # Conecta as ações dos botões padrão para OK/Cancelar
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        
        # Conecta as ações dos botões personalizados
        self.btn_importar.clicked.connect(self.import_questions)
        self.btn_exportar.clicked.connect(self.export_questions)
        self.btn_restaurar.clicked.connect(self.restore_questions)

    def populate_fields(self):
        """Cria os widgets das perguntas a partir da lista self.questions."""
        # Limpa o layout atual
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.question_widgets.clear()
        
        # Cria os widgets para cada questão
        for q in self.questions:
            container = QWidget()
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(10, 10, 10, 10)
            
            # Rótulo da pergunta
            label = QLabel(q["text"])
            label.setWordWrap(True)
            label.setStyleSheet("font-weight: bold;")
            container_layout.addWidget(label)
            
            widget_entry = {"question": q["text"], "type": q["type"]}
            
            if q["type"] == "radio":
                response_widget = QWidget()
                response_layout = QHBoxLayout(response_widget)
                response_layout.setAlignment(Qt.AlignLeft)
                response_layout.setSpacing(20)
                
                button_group = QButtonGroup(response_widget)
                radio_sim = QRadioButton("Sim")
                radio_nao = QRadioButton("Não")
                
                default_response = q.get("default", "Sim")
                if default_response == "Sim":
                    radio_sim.setChecked(True)
                else:
                    radio_nao.setChecked(True)
                button_group.addButton(radio_sim)
                button_group.addButton(radio_nao)
                
                response_layout.addWidget(radio_sim)
                response_layout.addWidget(radio_nao)
                container_layout.addWidget(response_widget)
                
                widget_entry.update({
                    "group": button_group,
                    "sim": radio_sim,
                    "nao": radio_nao
                })
                
                if q.get("requires_justification", False):
                    justification_edit = QTextEdit()
                    justification_edit.setPlaceholderText("Descreva a justificativa...")
                    justification_edit.setFixedHeight(60)
                    justification_edit.setVisible(False)
                    container_layout.addWidget(justification_edit)
                    widget_entry["justification"] = justification_edit
                    
                    if q.get("justify_on", "Não") == "Sim":
                        radio_sim.toggled.connect(lambda checked, edit=justification_edit: (edit.setVisible(checked), edit.clear() if not checked else None))
                    else:
                        radio_nao.toggled.connect(lambda checked, edit=justification_edit: (edit.setVisible(checked), edit.clear() if not checked else None))
            
            elif q["type"] == "text":
                line_edit = QLineEdit()
                container_layout.addWidget(line_edit)
                widget_entry["line_edit"] = line_edit
            
            self.question_widgets.append(widget_entry)
            self.scroll_layout.addWidget(container)

    def import_questions(self):
        """Importa um arquivo .json contendo as perguntas e suas configurações."""
        filename, _ = QFileDialog.getOpenFileName(self, "Importar Questionário", "", "JSON Files (*.json)")
        if filename:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Espera-se que 'data' seja uma lista de dicionários
                if isinstance(data, list):
                    self.questions = data
                    self.populate_fields()
                    QMessageBox.information(self, "Importar", "Questionário importado com sucesso.")
                else:
                    QMessageBox.warning(self, "Importar", "Arquivo inválido. Certifique-se de que o JSON contenha uma lista de perguntas.")
            except Exception as e:
                QMessageBox.warning(self, "Importar", f"Erro ao importar: {e}")

    def export_questions(self):
        """Exporta as questões atuais para um arquivo .json."""
        filename, _ = QFileDialog.getSaveFileName(self, "Exportar Questionário", "questionario.json", "JSON Files (*.json)")
        if filename:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(self.questions, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, "Exportar", "Questionário exportado com sucesso.")
            except Exception as e:
                QMessageBox.warning(self, "Exportar", f"Erro ao exportar: {e}")

    def restore_questions(self):
        """Restaura as perguntas para o conjunto padrão."""
        self.questions = list(self.default_questions)
        self.populate_fields()
        QMessageBox.information(self, "Restaurar", "Questionário restaurado para os valores padrão.")

    def get_answers(self):
        """
        Retorna um dicionário com as respostas:
          - Para perguntas do tipo radio, retorna um dicionário com 'resposta' ("Sim" ou "Não")
            e, se aplicável, a 'justificativa' (o conteúdo do QTextEdit).
          - Para perguntas do tipo texto, retorna o conteúdo digitado.
        """
        answers = {}
        for widget_info in self.question_widgets:
            question = widget_info["question"]
            if widget_info["type"] == "radio":
                resposta = "Sim" if widget_info["sim"].isChecked() else "Não"
                justificativa = ""
                if "justification" in widget_info:
                    justificativa = widget_info["justification"].toPlainText().strip()
                answers[question] = {"resposta": resposta, "justificativa": justificativa}
            elif widget_info["type"] == "text":
                answers[question] = widget_info["line_edit"].text().strip()
        return answers

    def accept(self):
        # Ao clicar em OK, as respostas serão salvas e utilizadas no relatório em PDF
        super().accept()
    
    def set_answers(self, answers):
        """
        Atualiza os widgets do questionário com as respostas salvas.
        'answers' é um dicionário no formato:
        { "Texto da pergunta": {"resposta": "Sim" ou "Não", "justificativa": "texto"}, ... }
        Para perguntas do tipo texto, o valor é uma string.
        """
        for widget_info in self.question_widgets:
            question = widget_info["question"]
            if question in answers:
                dado = answers[question]
                if widget_info["type"] == "radio" and isinstance(dado, dict):
                    # Atualiza a resposta: se for "Sim", marca o botão sim, senão marca o botão não.
                    if dado.get("resposta", "").lower() == "sim":
                        widget_info["sim"].setChecked(True)
                    else:
                        widget_info["nao"].setChecked(True)
                    # Atualiza a justificativa, se existir o widget
                    if "justification" in widget_info:
                        justificativa = dado.get("justificativa", "")
                        widget_info["justification"].setPlainText(justificativa)
                        # Exibe o QTextEdit se houver justificativa
                        widget_info["justification"].setVisible(bool(justificativa.strip()))
                elif widget_info["type"] == "text":
                    widget_info["line_edit"].setText(dado)


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv)
    dialog = QuestionarioPodaDialog()
    if dialog.exec_() == QDialog.Accepted:
        respostas = dialog.get_answers()
        print("Respostas do Questionário de Poda:")
        for pergunta, dados in respostas.items():
            if isinstance(dados, dict):
                print(f"{pergunta} -> {dados['resposta']} | Justificativa: {dados['justificativa']}")
            else:
                print(f"{pergunta} -> {dados}")
    sys.exit(0)
