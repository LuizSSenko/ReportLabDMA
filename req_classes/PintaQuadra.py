#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PintaQuadra.py

import sys
import os
import json
import tempfile
import re
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QRadioButton, QButtonGroup, QPushButton, QFileDialog,
    QScrollArea, QMessageBox, QFrame, QColorDialog
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Polygon as MplPolygon, Patch as MplPatch
from matplotlib.collections import PatchCollection

from PIL import Image
import numpy as np


class MapColoringApp(QMainWindow):
    def __init__(self, save_dir: Path = None):
        super().__init__()
        self.setWindowTitle("Pinta Quadras e Canteiros")
        self.resize(1400, 900)

        # data atual em português
        meses_pt = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        hoje = datetime.now()
        data_str = f'{hoje.day:02d} de {meses_pt[hoje.month-1]} de {hoje.year}'

        # diretórios
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent
        self.script_dir = script_dir
        self.project_root = project_root

        # db path
        self.db_path = (Path(save_dir) / "PintaQuadraDB.json") if save_dir \
                       else (project_root / "PintaQuadraDB.json")

        # carrega estado salvo (suporta formato legado e novo)
        saved = {}
        if self.db_path.is_file():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
            except:
                saved = {}

        # cores e mapeamentos
        self.state_colors = {
            "Finalizado":     "#00FF00",
            "Parcial":        "#FFFF00",
            "Não Iniciado":   "#FF9999",
            "Não Programado": "#D3D3D3"
        }
        self.status_map = {
            "Concluído":     "Finalizado",
            "Parcial":       "Parcial",
            "Não Iniciado":  "Não Iniciado",
            "Não Programado":"Não Programado"
        }
        self.column_widths = {
            "Área": 150,
            "Finalizado": 70,
            "Parcial": 70,
            "Não Iniciado": 90,
            "Não Programado": 100,
            "Cor": 30
        }

        # modos de exibição e cores específicas
        self.modes = ["Estados", "Programação", "Arbitrário"]
        generic = list(self.state_colors.values())[:4]
        self.mode_colors = {
            "Estados": dict(self.state_colors),
            "Programação": {f"Semana {i}": generic[i-1] for i in range(1, 5)},
            "Arbitrário": dict(zip(["A", "B", "C", "D"], generic))
        }
        self.mode = "Estados"

        # --- MONTA INTERFACE ---

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # painel esquerdo
        left_frame = QFrame()
        left_frame.setFrameShape(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_frame)
        left_frame.setMaximumWidth(700)
        main_layout.addWidget(left_frame)

        # título + importar
        ttl_layout = QHBoxLayout()
        lbl_ttl = QLabel("Título:")
        lbl_ttl.setStyleSheet("font-weight:bold;")
        self.input_titulo = QLineEdit(saved.get('title', f'UNICAMP - {data_str}'))
        self.input_titulo.textChanged.connect(self._on_title_changed)
        ttl_layout.addWidget(lbl_ttl)
        ttl_layout.addWidget(self.input_titulo)
        btn_import = QPushButton("Importar estados")
        btn_import.clicked.connect(self.import_states)
        ttl_layout.addWidget(btn_import)
        left_layout.addLayout(ttl_layout)

        # seleção de modo
        mode_layout = QHBoxLayout()
        mode_layout.setContentsMargins(0, 5, 0, 15)
        lbl_mode = QLabel("Modo:")
        lbl_mode.setStyleSheet("font-weight:bold;")
        mode_layout.addWidget(lbl_mode)
        self.mode_group = QButtonGroup(self)
        for m in self.modes:
            rb = QRadioButton(m)
            self.mode_group.addButton(rb)
            mode_layout.addWidget(rb)
            if m == self.mode:
                rb.setChecked(True)
            rb.toggled.connect(lambda checked, mm=m: checked and self._on_mode_changed(mm))
        left_layout.addLayout(mode_layout)

        # cabeçalho da tabela
        self.header = QWidget()
        self.header_layout = QHBoxLayout(self.header)
        self.header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_labels = []
        for text, w in self.column_widths.items():
            lbl = QLabel(text)
            f = lbl.font(); f.setBold(True); lbl.setFont(f)
            lbl.setFixedWidth(w)
            lbl.setAlignment(Qt.AlignCenter)
            self.header_layout.addWidget(lbl)
            self.header_labels.append(lbl)
        left_layout.addWidget(self.header)
        left_layout.addWidget(QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken))

        # scroll de itens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.v_layout = QVBoxLayout(content)
        self.v_layout.setContentsMargins(0, 0, 0, 0)
        self.v_layout.setSpacing(0)
        scroll.setWidget(content)
        left_layout.addWidget(scroll)

        # área de seleção de cores dinâmica
        picker_layout = QHBoxLayout()
        picker_layout.setContentsMargins(0, 10, 0, 10)
        self.picker_layout = picker_layout
        left_layout.addLayout(picker_layout)
        self._update_color_buttons()

        # botão gerar imagem
        btn_generate = QPushButton("Gerar Imagem")
        btn_generate.clicked.connect(self.generate_image)
        left_layout.addWidget(btn_generate)

        # painel direito (mapa)
        self.fig = Figure(figsize=(5, 5))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(self.input_titulo.text(), fontsize=12, fontweight='bold', pad=16)

        # carrega geojson e inicializa patches
        self.map_path = project_root / "map.geojson"
        if not self.map_path.is_file():
            QMessageBox.critical(self, "Erro",
                                 f"Arquivo map.geojson não encontrado em: {self.map_path}")
            sys.exit(1)
        try:
            with open(self.map_path, 'r', encoding='utf-8') as f:
                geojson = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Erro",
                                 f"Falha ao carregar map.geojson:\n{e}")
            sys.exit(1)
        self.features = geojson.get("features", [])
        if not self.features:
            QMessageBox.critical(self, "Erro", "Nenhuma feature em map.geojson.")
            sys.exit(1)

        # itens: quadras, canteiros e outros
        quadra, canteiro, outros = [], [], []
        for idx, feat in enumerate(self.features):
            p = feat.get("properties", {})
            if "Quadra" in p:
                try:
                    quadra.append((idx, int(p["Quadra"]), p.get("Sigla", f"Q{idx}")))
                    continue
                except:
                    pass
            if "Canteiro" in p:
                try:
                    canteiro.append((idx, int(p["Canteiro"]), p.get("Sigla", f"C{idx}")))
                    continue
                except:
                    pass
            outros.append((idx, p.get("Sigla", f"F{idx}")))
        quadra.sort(key=lambda x: x[1])
        canteiro.sort(key=lambda x: x[1])

        # carrega estados salvos por índice
        saved_items = {i['index']: i for i in saved.get('items', [])}

        # prepara lista de items com estados por modo
        self.items = []
        for idx, num, sig in quadra:
            self._add_item(idx, f"Qda. {num} – {sig}", sig, saved_items)
        for idx, num, sig in canteiro:
            self._add_item(idx, f"Cant. {num} – {sig}", sig, saved_items)
        for idx, sig in outros:
            self._add_item(idx, sig, sig, saved_items)

        # prepara patches do mapa
        self.patches = []
        self.facecolors = []
        self.feature_to_patch_idxs = {}
        def add_patch(coords, lst):
            lst.append(len(self.patches))
            self.patches.append(MplPolygon(coords, closed=True))
            self.facecolors.append(self.mode_colors["Estados"]["Não Programado"])
        for i, feat in enumerate(self.features):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            lst = []
            if geom.get("type") == "Polygon":
                add_patch(coords[0], lst)
            elif geom.get("type") == "MultiPolygon":
                for poly in coords:
                    add_patch(poly[0], lst)
            self.feature_to_patch_idxs[i] = lst

        # cor inicial baseado em 'Estados'
        for it in self.items:
            cor = self.mode_colors["Estados"].get(it['states']["Estados"], self.state_colors["Não Programado"])
            for p in self.feature_to_patch_idxs.get(it['index'], []):
                self.facecolors[p] = cor

        self.patch_collection = PatchCollection(self.patches, facecolor=self.facecolors,
                                                edgecolor='black', linewidth=0.5)
        self.ax.add_collection(self.patch_collection)
        self.ax.autoscale()
        self.ax.set_aspect('equal')
        self.ax.axis('off')

        # popula itens na UI
        self._populate_items()
        self._update_legend()
        self.canvas = FigureCanvas(self.fig)
        main_layout.addWidget(self.canvas)
        self.canvas.draw_idle()

    def _add_item(self, idx, name, sigla, saved_items):
        saved_i = saved_items.get(idx, {})
        if 'states' in saved_i:
            states = saved_i['states']
        else:
            legacy = saved_i.get('state', "Não Programado")
            states = {
                "Estados": legacy,
                "Programação": "Semana 1",
                "Arbitrário": "A"
            }
        item = {
            "index": idx,
            "sigla": sigla,
            "name": name,
            "states": states,
            "rbs": {m: {} for m in self.modes},
            "color_label": None
        }
        self.items.append(item)
        # índice por sigla para import_states
        if not hasattr(self, 'sigla_map'):
            self.sigla_map = {}
        self.sigla_map.setdefault(sigla, []).append(item)

    def _populate_items(self):
        # limpar layout
        while self.v_layout.count():
            w = self.v_layout.takeAt(0).widget()
            if w:
                w.deleteLater()

        # cabeçalho já em self.header
        # para cada item cria linha
        for it in self.items:
            row = QWidget()
            row.setFixedHeight(30)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            lbl = QLabel(it['name'])
            lbl.setFixedWidth(self.column_widths['Área'])
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            row_layout.addWidget(lbl)

            grp = QButtonGroup(row)
            options = list(self.mode_colors[self.mode].keys())
            for opt in options:
                rb = QRadioButton()
                rb.setFixedWidth(self.column_widths.get(opt, 70))
                grp.addButton(rb)
                it['rbs'][self.mode][opt] = rb
                if it['states'][self.mode] == opt:
                    rb.setChecked(True)
                rb.toggled.connect(lambda chk, item=it, o=opt: self._on_state_changed(item, o, chk))
                row_layout.addWidget(rb, alignment=Qt.AlignCenter)

            color_label = QLabel()
            color_label.setFixedSize(self.column_widths['Cor'], 20)
            color_label.setAutoFillBackground(True)
            pal = color_label.palette()
            pal.setColor(QPalette.Window,
                         QColor(self.mode_colors[self.mode][it['states'][self.mode]]))
            color_label.setPalette(pal)
            row_layout.addWidget(color_label)
            it['color_label'] = color_label

            self.v_layout.addWidget(row)
            self.v_layout.addWidget(QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken))

    def _on_title_changed(self, text):
        self.ax.set_title(text, fontsize=12, fontweight='bold', pad=16)
        self._save_state()
        self.canvas.draw_idle()

    def _on_state_changed(self, item, state_text, checked):
        if not checked:
            return
        # atualiza estado do modo atual
        item['states'][self.mode] = state_text
        # atualiza cor do label
        pal = item['color_label'].palette()
        pal.setColor(QPalette.Window, QColor(self.mode_colors[self.mode][state_text]))
        item['color_label'].setPalette(pal)
        # atualiza cores do mapa
        self._update_facecolors()
        self._save_state()
        self.canvas.draw_idle()

    def _on_mode_changed(self, mode):
        self.mode = mode

        # atualizar cabeçalho
        for lbl in self.header_labels:
            self.header_layout.removeWidget(lbl)
            lbl.deleteLater()
        self.header_labels.clear()

        if mode == "Estados":
            labels = list(self.column_widths.keys())
            widths = list(self.column_widths.values())
        elif mode == "Programação":
            labels = ["Área", "Semana 1", "Semana 2", "Semana 3", "Semana 4"]
            widths = [self.column_widths["Área"]] + [70]*4
        else:  # Arbitrário
            labels = ["Área", "A", "B", "C", "D"]
            widths = [self.column_widths["Área"]] + [70]*4

        for text, w in zip(labels, widths):
            lbl = QLabel(text)
            f = lbl.font(); f.setBold(True); lbl.setFont(f)
            lbl.setFixedWidth(w)
            lbl.setAlignment(Qt.AlignCenter)
            self.header_layout.addWidget(lbl)
            self.header_labels.append(lbl)

        # atualizar botões de cor e legenda
        self._update_color_buttons()
        # repopular itens de acordo com o novo modo
        self._populate_items()
        # recolorir mapa
        self._update_facecolors()
        self._update_legend()
        self.canvas.draw_idle()

    def _update_facecolors(self):
        for it in self.items:
            cor = self.mode_colors[self.mode].get(it['states'][self.mode],
                                                 list(self.mode_colors[self.mode].values())[0])
            for p in self.feature_to_patch_idxs.get(it['index'], []):
                self.facecolors[p] = cor
        self.patch_collection.set_facecolor(self.facecolors)

    def _update_color_buttons(self):
        # limpa layout
        while self.picker_layout.count():
            item = self.picker_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        lbl = QLabel("Cores:")
        lbl.setStyleSheet("font-weight:bold;")
        self.picker_layout.addWidget(lbl)

        self.color_buttons = {}
        for name, col in self.mode_colors[self.mode].items():
            btn = QPushButton(name)
            btn.setFixedSize(80, 20)
            btn.setStyleSheet(f"background-color: {col};")
            btn.clicked.connect(lambda _, n=name: self._change_mode_color(n))
            self.picker_layout.addWidget(btn)
            self.color_buttons[name] = btn

    def _change_mode_color(self, name):
        current = QColor(self.mode_colors[self.mode][name])
        nova = QColorDialog.getColor(current, self, f"Escolha a cor para '{name}'")
        if not nova.isValid():
            return
        hex_nova = nova.name()
        self.mode_colors[self.mode][name] = hex_nova
        self.color_buttons[name].setStyleSheet(f"background-color: {hex_nova};")

        # se for Estados, atualiza state_colors também
        if self.mode == "Estados":
            self.state_colors[name] = hex_nova

        # reaplicar cores
        self._update_color_buttons()
        self._populate_items()
        self._update_facecolors()
        self._update_legend()
        self.canvas.draw_idle()
        self._save_state()

    def import_states(self):
        path = self.db_path.parent / "imagens_db.json"
        if not path.is_file():
            QMessageBox.warning(self, "Erro", f"Arquivo não encontrado:\n{path}")
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Erro ao ler JSON", str(e))
            return
        sigla_statuses = {}
        for entry in data.get("images", {}).values():
            if not entry.get("include", False):
                continue
            loc = entry.get("location", "")
            sigla = re.sub(r'^\d+\s*-\s*', '', loc)
            status = entry.get("status", "")
            mapped = self.status_map.get(status)
            if not mapped:
                continue
            sigla_statuses.setdefault(sigla, []).append(mapped)
        total = 0
        for sigla, statuses in sigla_statuses.items():
            chosen = "Parcial" if "Parcial" in statuses else max(set(statuses), key=statuses.count)
            for it in self.sigla_map.get(sigla, []):
                rb = it['rbs']['Estados'].get(chosen)
                if rb and not rb.isChecked():
                    rb.setChecked(True)
                    total += 1
        self.canvas.draw_idle()
        QMessageBox.information(self, "Importação",
                                f"{total} estados aplicados com sucesso.")

    def generate_image(self):
        self._save_state()
        path, _ = QFileDialog.getSaveFileName(self, "Salvar Imagem", "",
                                              "PNG Files (*.png)")
        if not path:
            return

        # gera base transparente
        fig_base = Figure(figsize=(11, 11))
        ax_base = fig_base.add_subplot(111)
        pc_base = PatchCollection(self.patches, facecolor=self.facecolors,
                                  edgecolor='black', linewidth=0.5)
        ax_base.add_collection(pc_base)
        ax_base.autoscale()
        ax_base.set_aspect('equal')
        ax_base.axis('off')
        fd, tmp_base = tempfile.mkstemp(suffix='_base.png')
        os.close(fd)
        fig_base.savefig(tmp_base, dpi=600, bbox_inches='tight', transparent=True)
        del fig_base

        # mistura overlay
        base = Image.open(tmp_base).convert('RGBA')
        overlay = Image.open(
            str(self.project_root / 'req_classes' / '[alpha_labeled]map_blank_highres.png')
        ).convert('RGBA')
        if base.size != overlay.size:
            overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
        base.alpha_composite(overlay)
        os.remove(tmp_base)
        arr = np.array(base)

        # figura final com legenda embutida
        fig_final = Figure(figsize=(10, 10))
        ax = fig_final.add_subplot(111)
        ax.imshow(arr)
        ax.axis('off')
        ax.set_title(self.input_titulo.text(), fontsize=16,
                     fontweight='bold', pad=16)
        labels = list(self.mode_colors[self.mode].keys())
        colors = list(self.mode_colors[self.mode].values())
        handles = [MplPatch(facecolor=col, edgecolor='black', label=lbl)
                   for lbl, col in zip(labels, colors)]
        ax.legend(handles=handles, loc='lower left', title='Legenda')
        fig_final.savefig(path, dpi=600, bbox_inches="tight",
                          pad_inches=0, transparent=False)
        del fig_final

        QMessageBox.information(self, 'Sucesso', f'Imagem salva em:\n{path}')

    def _save_state(self):
        data = {
            'title': self.input_titulo.text(),
            'items': [
                {'index': it['index'], 'states': it['states']}
                for it in self.items
            ]
        }
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, 'Erro ao salvar estado', str(e))

    def _update_legend(self):
        labels = list(self.mode_colors[self.mode].keys())
        colors = list(self.mode_colors[self.mode].values())
        handles = [MplPatch(facecolor=col, edgecolor='black', label=lbl)
                   for lbl, col in zip(labels, colors)]
        self.ax.legend(handles=handles, loc='lower left', title='Legenda')

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MapColoringApp()
    win.show()
    sys.exit(app.exec_())
