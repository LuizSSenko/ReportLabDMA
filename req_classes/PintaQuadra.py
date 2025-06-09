#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# PintaQuadra.py

import sys
import os
import json
import tempfile
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QRadioButton, QButtonGroup, QPushButton, QFileDialog,
    QScrollArea, QMessageBox, QFrame
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

        # definir data atual em português
        from datetime import datetime
        meses_pt = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        hoje = datetime.now()
        data_str = f'{hoje.day:02d} de {meses_pt[hoje.month-1]} de {hoje.year}'

        # raiz do projeto (contém ReportLab.py e map.json)
        project_root = Path(__file__).resolve().parent.parent
        self.project_root = project_root

        # caminho para salvar JSON de estado
        if save_dir:
            self.db_path = Path(save_dir) / "PintaQuadraDB.json"
        else:
            self.db_path = project_root / "PintaQuadraDB.json"

        # carrega estado existente
        saved = {}
        if self.db_path.is_file():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
            except Exception:
                saved = {}

        # mapeamento de cores
        self.state_colors = {
            "Finalizado": "#00FF00",
            "Parcial": "#FFFF00",
            "Não Iniciado": "#FF9999",
            "Não Programado": "#D3D3D3"
        }
        self.column_widths = {
            "Área": 150,
            "Finalizado": 70,
            "Parcial": 70,
            "Não Iniciado": 90,
            "Não Programado": 100,
            "Cor": 30
        }

        # carrega map.json
        self.map_path = project_root / "map.geojson"
        if not self.map_path.is_file():
            QMessageBox.critical(self, "Erro", f"Arquivo map.geojson não encontrado em: {self.map_path}")
            sys.exit(1)
        try:
            with open(self.map_path, 'r', encoding='utf-8') as f:
                geojson = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao carregar map.geojson:\n{e}")
            sys.exit(1)

        self.features = geojson.get("features", [])
        if not self.features:
            QMessageBox.critical(self, "Erro", "Nenhuma feature em map.geojson.")
            sys.exit(1)

        # separa entradas
        quadra_entries, canteiro_entries, other_entries = [], [], []
        for idx, feat in enumerate(self.features):
            props = feat.get("properties", {})
            quad = props.get("Quadra")
            cant = props.get("Canteiro")
            sigla = props.get("Sigla", f"Feature {idx}")
            if quad is not None:
                try:
                    quadra_entries.append((idx, int(quad), sigla))
                    continue
                except:
                    pass
            if cant is not None:
                try:
                    canteiro_entries.append((idx, int(cant), sigla))
                    continue
                except:
                    pass
            other_entries.append((idx, sigla))
        quadra_entries.sort(key=lambda x: x[1])
        canteiro_entries.sort(key=lambda x: x[1])

        # monta itens com estado salvo
        self.items = []
        for idx, num, sigla in quadra_entries:
            state = next((it['state'] for it in saved.get('items', []) if it['index'] == idx), "Não Programado")
            self.items.append({"index": idx, "name": f"Qda. {num} – {sigla}", "state": state, "color_label": None})
        for idx, num, sigla in canteiro_entries:
            state = next((it['state'] for it in saved.get('items', []) if it['index'] == idx), "Não Programado")
            self.items.append({"index": idx, "name": f"Cant. {num} – {sigla}", "state": state, "color_label": None})
        for idx, sigla in other_entries:
            state = next((it['state'] for it in saved.get('items', []) if it['index'] == idx), "Não Programado")
            self.items.append({"index": idx, "name": sigla, "state": state, "color_label": None})

        # cria patches e cores iniciais
        self.patches, self.facecolors, self.feature_to_patch_idxs = [], [], {}
        def add_patch(coords, patch_idxs):
            p = MplPolygon(coords, closed=True)
            patch_idxs.append(len(self.patches))
            self.patches.append(p)
            self.facecolors.append(self.state_colors['Não Programado'])
        for i, feat in enumerate(self.features):
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [])
            idxs = []
            if geom.get("type") == "Polygon":
                add_patch(coords[0], idxs)
            elif geom.get("type") == "MultiPolygon":
                for poly in coords:
                    add_patch(poly[0], idxs)
            self.feature_to_patch_idxs[i] = idxs
        for item in self.items:
            col = self.state_colors.get(item['state'], self.state_colors['Não Programado'])
            for pi in self.feature_to_patch_idxs.get(item['index'], []):
                self.facecolors[pi] = col

        # layout UI
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # painel esquerdo
        left_frame = QFrame()
        left_frame.setFrameShape(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_frame)
        left_frame.setMaximumWidth(700)
        main_layout.addWidget(left_frame)

        # título
        ttl_layout = QHBoxLayout()
        lbl_ttl = QLabel("Título:")
        lbl_ttl.setStyleSheet("font-weight: bold;")
        init_ttl = saved.get('title', f'UNICAMP - {data_str}')
        self.input_titulo = QLineEdit(init_ttl)
        self.input_titulo.textChanged.connect(self._on_title_changed)
        ttl_layout.addWidget(lbl_ttl)
        ttl_layout.addWidget(self.input_titulo)
        left_layout.addLayout(ttl_layout)

        # cabeçalho tabela
        hdr = QWidget()
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(0, 0, 0, 0)
        for text, w in self.column_widths.items():
            l = QLabel(text)
            f = l.font()
            f.setBold(True)
            l.setFont(f)
            l.setFixedWidth(w)
            l.setAlignment(Qt.AlignCenter)
            hdr_l.addWidget(l)
        left_layout.addWidget(hdr)
        left_layout.addWidget(QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken))

        # scroll itens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        v_l = QVBoxLayout(content)
        v_l.setContentsMargins(0, 0, 0, 0)
        v_l.setSpacing(0)
        scroll.setWidget(content)
        left_layout.addWidget(scroll)
        for it in self.items:
            row = QWidget()
            row.setFixedHeight(30)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            nm = QLabel(it['name'])
            nm.setFixedWidth(self.column_widths['Área'])
            nm.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            rl.addWidget(nm)
            grp = QButtonGroup(row)
            for st in ("Finalizado", "Parcial", "Não Iniciado", "Não Programado"):
                rb = QRadioButton()
                rb.setFixedWidth(self.column_widths[st])
                grp.addButton(rb)
                rl.addWidget(rb, alignment=Qt.AlignCenter)
                if it['state'] == st:
                    rb.setChecked(True)
                rb.toggled.connect(lambda chk, item=it, st=st: self._on_state_changed(item, st, chk))
            cl = QLabel()
            cl.setFixedSize(self.column_widths['Cor'], 20)
            cl.setAutoFillBackground(True)
            pal = cl.palette()
            pal.setColor(QPalette.Window, QColor(self.state_colors[it['state']]))
            cl.setPalette(pal)
            rl.addWidget(cl)
            it['color_label'] = cl
            v_l.addWidget(row)
            v_l.addWidget(QFrame(frameShape=QFrame.HLine, frameShadow=QFrame.Sunken))
        btn = QPushButton("Gerar Imagem")
        btn.clicked.connect(self.generate_image)
        left_layout.addWidget(btn)

        # painel direito (mapa)
        self.fig = Figure(figsize=(5, 5))
        self.ax = self.fig.add_subplot(111)
        self.ax.set_title(self.input_titulo.text(), fontsize=12, fontweight='bold', pad=16)
        pc = PatchCollection(self.patches, facecolor=self.facecolors, edgecolor='black', linewidth=0.5)
        self.ax.add_collection(pc)
        self.ax.autoscale()
        self.ax.set_aspect('equal')
        self.ax.axis('off')
        # adiciona legenda no mapa inicial
        legend_handles = [MplPatch(facecolor=col, edgecolor='black', label=lbl)
                          for lbl, col in self.state_colors.items()]
        self.ax.legend(handles=legend_handles, loc='lower left', title='Legenda')
        canvas = FigureCanvas(self.fig)
        main_layout.addWidget(canvas)
        self.patch_collection = pc
        self.canvas = canvas

    def _on_title_changed(self, text):
        self.ax.set_title(text, fontsize=12, fontweight='bold', pad=16)
        self._save_state()
        self.canvas.draw_idle()

    def _on_state_changed(self, item, state_text, checked):
        if not checked:
            return
        item['state'] = state_text
        pal = item['color_label'].palette()
        pal.setColor(QPalette.Window, QColor(self.state_colors[state_text]))
        item['color_label'].setPalette(pal)
        for idx in self.feature_to_patch_idxs.get(item['index'], []):
            self.facecolors[idx] = self.state_colors[state_text]
        self.patch_collection.set_facecolor(self.facecolors)
        self._save_state()
        self.canvas.draw_idle()

    def generate_image(self):
        self._save_state()
        path, _ = QFileDialog.getSaveFileName(self, "Salvar Imagem", "", "PNG Files (*.png)")
        if not path:
            return

        # etapa 1: gerar base fill (apenas patches coloridos)
        original_size = (11,11) #tuple(self.fig.get_size_inches())
        fig_base = Figure(figsize=original_size)
        ax_base = fig_base.add_subplot(111)
        pc_base = PatchCollection(self.patches, facecolor=self.facecolors, edgecolor='black', linewidth=0.5)
        ax_base.add_collection(pc_base)
        ax_base.autoscale()
        ax_base.set_aspect('equal')
        ax_base.axis('off')

        fd, tmp_base = tempfile.mkstemp(suffix='_base.png')
        os.close(fd)
        # usa tight para crop somente o mapa
        fig_base.savefig(tmp_base, dpi=600, bbox_inches='tight', transparent=True)
        del fig_base

        # etapa 2: composite com overlay
        base = Image.open(tmp_base).convert('RGBA')
        overlay = Image.open(str(self.project_root / 'req_classes' / '[alpha_labeled]map_blank_highres.png')).convert('RGBA')

        # DEBUG: salvar mapa colorido antes do overlay
        #base.save(str(self.project_root / 'debug_base.png'))

        if base.size != overlay.size:
            overlay = overlay.resize(base.size, Image.Resampling.LANCZOS)
        base.alpha_composite(overlay)
        os.remove(tmp_base)

        # etapa 3: desenhar título e legenda sobre o combinado
        arr = np.array(base)
        fig_final = Figure(figsize=(10,10))
        ax = fig_final.add_subplot(111)
        ax.imshow(arr)
        ax.axis('off')
        ax.set_title(self.input_titulo.text(), fontsize=16, fontweight='bold', pad=16)
        legend_handles2 = [MplPatch(facecolor=col, edgecolor='black', label=lbl) for lbl, col in self.state_colors.items()]
        ax.legend(handles=legend_handles2, loc='lower left', title='Legenda')

        # salva sem tight para manter alinhamento
        fig_final.savefig(path, dpi=600, bbox_inches="tight", pad_inches=0, transparent=False)
        del fig_final

        QMessageBox.information(self, 'Sucesso', f'Imagem salva em:\n{path}')

    def _save_state(self):
        data = {
            'title': self.input_titulo.text(),
            'items': [{'index': it['index'], 'state': it['state']} for it in self.items]
        }
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.warning(self, 'Erro ao salvar estado', str(e))

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MapColoringApp()
    win.show()
    sys.exit(app.exec_())
