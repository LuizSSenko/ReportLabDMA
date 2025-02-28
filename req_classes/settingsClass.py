#settingsClass.py

import os
import json
import logging
from pathlib import Path

# Configura o logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("pdf_tools.log"),
        logging.StreamHandler()
    ]
)

class Settings:
    CONFIG_FILENAME = "Report_config.json"

    def __init__(self):
        self.config_path = Path(__file__).parent / self.CONFIG_FILENAME
        self.config = self.load_config()

    @staticmethod
    def get_default_config():
        """
        Retorna o dicionário de configuração padrão.
        """
        return {
            "header_1": "SIGLA - DIRETORIA / SIGLA - DIVISÃO",
            "header_2": "UNICAMP - UNIVERSIDADE ESTADUAL DE CAMPINAS",
            "title": "RELATÓRIO DE XXXX - SERVIÇOS DE XXXX",
            "date_prefix": "DATA DO RELATÓRIO:",
            "reference_number": "CONTRATO Nº: XXX/20XX - PRESTADORA LTDA",
            "description": "Descrição: Vistoria de campo realizada pelos técnicos da SIGLA/SIGLA,",
            "address": "Rua XX de XX, número - Cidade Universitária Zeferino Vaz - Campinas - SP",
            "postal_code": "CEP: XXXXX-XXX",
            "contact_phone": "Tel: (19) XXXX-XXXX",
            "contact_fax": "Fax: (19) XXXX-XXXX",
            "contact_email": "XXXXXXXXXX@unicamp.br",
            "sign1": "PREPOSTO CONTRATANTE",
            "sign1_name": "sign1_name",
            "sign2": "PREPOSTO CONTRATADA",
            "sign2_name": "sign2_name"
        }

    def load_config(self):
        """
        Carrega a configuração a partir do arquivo Report_config.json.
        Se o arquivo não existir ou ocorrer erro, retorna os valores padrão.
        """
        default_config = self.get_default_config()
        if self.config_path.exists():
            try:
                with self.config_path.open("r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                # Preenche os campos faltantes
                for key, value in default_config.items():
                    if key not in loaded_config:
                        loaded_config[key] = value
                logging.info(f"Configuração carregada e mesclada de {self.config_path}.")
                return loaded_config
            except Exception as e:
                logging.error(f"Erro ao carregar a configuração: {e}", exc_info=True)
        logging.warning("Arquivo Report_config.json não encontrado. Usando valores padrão.")
        return default_config

    def save_config(self, config=None):
        """
        Salva a configuração no arquivo Report_config.json.
        Se nenhum dicionário for informado, salva o valor atual.
        """
        if config is None:
            config = self.config
        try:
            with self.config_path.open("w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            logging.info(f"Configuração salva em {self.config_path}.")
        except Exception as e:
            logging.error(f"Erro ao salvar a configuração: {e}", exc_info=True)

    def import_config(self, imported_config_path):
        """
        Importa uma nova configuração a partir de um arquivo externo
        e sobrescreve o Report_config.json.
        """
        try:
            with open(imported_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            self.config = config
            self.save_config()
            logging.info("Configuração importada e salva em Report_config.json.")
        except Exception as e:
            logging.error(f"Erro ao importar a configuração: {e}", exc_info=True)

    def restore_config(self):
        """
        Restaura a configuração para os valores padrão (hardcoded).
        """
        self.config = self.get_default_config()
        self.save_config()
        logging.info("Configuração restaurada para os valores padrão.")

# Teste simples quando o módulo for executado diretamente
if __name__ == "__main__":
    settings = Settings()
    print("Configuração atual:")
    print(json.dumps(settings.config, indent=4, ensure_ascii=False))
