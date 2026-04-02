import sys
import json
import requests
import pyqtgraph as pg
from requests.auth import HTTPBasicAuth
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLineEdit, QLabel,
                             QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QMessageBox,
                             QHeaderView, QComboBox, QAbstractItemView)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

# ==========================================
# 1. API 客戶端模組 (全面升級為 tw 台灣區網域)
# ==========================================
class WCLClient:
    def __init__(self):
        self.CLIENT_ID = 'a15fb0e5-e5b7-4b18-ad20-13fa2ac45d0d'
        self.CLIENT_SECRET = 'yR75c14r0JO4yiPLoNFOQs6zqDgX53vEy4ws1TEJ'
        self.token = None

    def authenticate(self):
        url = "https://www.warcraftlogs.com/oauth/token"
        response = requests.post(url, data={'grant_type': 'client_credentials'},
                                 auth=HTTPBasicAuth(self.CLIENT_ID, self.CLIENT_SECRET))
        if response.status_code == 200:
            self.token = response.json().get('access_token')
            return True
        return False

    def fetch_report_fights(self, report_id):
        if not self.token and not self.authenticate():
            raise Exception("無法獲取 API Token，請檢查金鑰。")
        api_url = "https://tw.warcraftlogs.com/api/v2/client"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        query = """
        query($code: String!) {
            reportData {
                report(code: $code) {
                    fights(killType: Kills) {
                        id
                        name
                        difficulty
                        startTime
                        endTime
                    }
                }
            }
        }
        """
        variables = {"code": report_id}
        response = requests.post(api_url, json={'query': query, 'variables': variables}, headers=headers)
        if response.status_code == 200:
            return response.json()
        raise Exception(f"API 請求失敗: {response.status_code}")

    def fetch_fight_data(self, report_id, fight_id, start_time, end_time):
        if not self.token and not self.authenticate():
            raise Exception("無法獲取 API Token，請檢查金鑰。")
        api_url = "https://tw.warcraftlogs.com/api/v2/client"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        query = """
        query($code: String!, $fightId: Int!, $start: Float!, $end: Float!) {
            reportData {
                report(code: $code) {
                    masterData {
                        actors(type: "Player") { id name subType }
                        abilities { gameID name }
                    }
                    events(fightIDs: [$fightId], dataType: Casts, hostilityType: Enemies, limit: 10000) { data }
                    graph(startTime: $start, endTime: $end, dataType: DamageTaken, hostilityType: Friendlies)
                    playerDetails(fightIDs: [$fightId])
                }
            }
        }
        """
        variables = {
            "code": report_id,
            "fightId": int(fight_id),
            "start": float(start_time),
            "end": float(end_time)
        }
        response = requests.post(api_url, json={'query': query, 'variables': variables}, headers=headers)
        if response.status_code == 200:
            result = response.json()
            if 'errors' in result:
                error_msg = result['errors'][0].get('message', '未知 GraphQL 錯誤')
                raise Exception(f"WCL 回報語法錯誤:\n{error_msg}")
            return result
        raise Exception(f"API 請求失敗: {response.status_code}")

# ==========================================
# 2. GUI 主視窗模組
# ==========================================
class ViserioCloneApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mythic Raid Tactical Planner (WCL Integration)")
        self.setGeometry(100, 100, 1400, 900)
        self.api_client = WCLClient()

        self.class_translation = {
            "DeathKnight": "死亡騎士", "DemonHunter": "惡魔獵人", "Druid": "德魯伊",
            "Evoker": "喚魔師", "Hunter": "獵人", "Mage": "法師", "Monk": "武僧",
            "Paladin": "聖騎士", "Priest": "牧師", "Rogue": "盜賊", "Shaman": "薩滿",
            "Warlock": "術士", "Warrior": "戰士"
        }

        self.class_colors = {
            "DeathKnight": "#C41E3A", "DemonHunter": "#A330C9", "Druid": "#FF7C0A",
            "Evoker": "#33937F", "Hunter": "#AAD372", "Mage": "#3FC7EB",
            "Monk": "#00FF98", "Paladin": "#F48CBA", "Priest": "#FFFFFF",
            "Rogue": "#FFF468", "Shaman": "#0070DD", "Warlock": "#8788EE",
            "Warrior": "#C69B6D"
        }

        # 治療職業大招 CD (依職業分組)
        self.healer_cooldowns = {
            "Priest": [
                {"name": "神聖讚美詩", "spell_id": 64843, "cd": 180},
                {"name": "救贖", "spell_id": 265202, "cd": 240},
                {"name": "真言術：障", "spell_id": 62618, "cd": 180},
                {"name": "福音傳播", "spell_id": 246287, "cd": 90},
                {"name": "狂喜", "spell_id": 47536, "cd": 90},
            ],
            "Paladin": [
                {"name": "光環精通", "spell_id": 31821, "cd": 120},
            ],
            "Shaman": [
                {"name": "靈魂鏈接圖騰", "spell_id": 98008, "cd": 180},
                {"name": "治療之潮圖騰", "spell_id": 108280, "cd": 180},
            ],
            "Druid": [
                {"name": "寧靜", "spell_id": 740, "cd": 180},
            ],
            "Monk": [
                {"name": "還魂術", "spell_id": 115310, "cd": 180},
            ],
            "Evoker": [
                {"name": "倒轉", "spell_id": 363534, "cd": 240},
            ],
        }
        self.druid_utility = {"name": "奔竄咆哮", "spell_id": 106898, "cd": 120}

        # 圖表上的時間軸標記
        self.timeline_markers = []
        self.graph_times = []
        self.graph_damages = []

        # ---- UI 排版 ----
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # 頂部工具列
        top_layout = QHBoxLayout()
        self.input_report = QLineEdit()
        self.input_report.setPlaceholderText("輸入 Report ID")
        self.input_report.setText("2mYrpayGhN1PLRfF")
        self.input_report.setFixedWidth(200)

        self.btn_load_fights = QPushButton("1. 取得首領列表")
        self.btn_load_fights.clicked.connect(self.load_fights_list)

        self.combo_fight = QComboBox()
        self.combo_fight.setMinimumWidth(300)

        self.btn_load_data = QPushButton("2. 載入戰鬥數據")
        self.btn_load_data.clicked.connect(self.load_data)
        self.btn_load_data.setEnabled(False)

        self.btn_export = QPushButton("匯出 NSRT Note")
        self.btn_export.clicked.connect(self.export_nsrt)

        top_layout.addWidget(QLabel("WCL 報告 ID:"))
        top_layout.addWidget(self.input_report)
        top_layout.addWidget(self.btn_load_fights)
        top_layout.addSpacing(20)
        top_layout.addWidget(QLabel("選擇戰鬥:"))
        top_layout.addWidget(self.combo_fight)
        top_layout.addWidget(self.btn_load_data)
        top_layout.addSpacing(20)
        top_layout.addWidget(self.btn_export)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        # 主內容區
        content_layout = QHBoxLayout()
        layout.addLayout(content_layout)

        # --- 左側面板 ---
        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("團隊陣容 (Roster)"))
        self.list_roster = QListWidget()
        self.list_roster.setFixedWidth(300)
        left_layout.addWidget(self.list_roster)

        left_layout.addWidget(QLabel("治療大招分配 (Healer CD Assignment)"))
        self.table_healer_cds = QTableWidget(0, 3)
        self.table_healer_cds.setHorizontalHeaderLabels(["玩家", "技能", "分配時間 (MM:SS)"])
        self.table_healer_cds.setFixedWidth(300)
        self.table_healer_cds.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table_healer_cds.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_healer_cds.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_healer_cds.setColumnWidth(0, 80)
        self.table_healer_cds.setColumnWidth(1, 100)
        left_layout.addWidget(self.table_healer_cds)

        content_layout.addLayout(left_layout)

        # --- 右側面板 ---
        right_layout = QVBoxLayout()

        # 承傷圖表
        self.graph_widget = pg.PlotWidget(title="團隊總承傷 (Total Damage Taken)")
        self.graph_widget.setLabel('bottom', '時間 (秒)')
        self.graph_widget.setLabel('left', '傷害量')
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setBackground('#1e1e1e')

        # 十字準線 (Crosshair)
        self.vLine = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen('#FFD700', width=1, style=Qt.PenStyle.DashLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False,
                                     pen=pg.mkPen('#FFD700', width=1, style=Qt.PenStyle.DashLine))
        self.graph_widget.addItem(self.vLine, ignoreBounds=True)
        self.graph_widget.addItem(self.hLine, ignoreBounds=True)
        self.crosshair_label = pg.TextItem(color='#FFD700', anchor=(0, 1))
        self.graph_widget.addItem(self.crosshair_label, ignoreBounds=True)
        self.proxy = pg.SignalProxy(self.graph_widget.scene().sigMouseMoved,
                                   rateLimit=60, slot=self.mouse_moved)

        right_layout.addWidget(self.graph_widget, stretch=2)

        # 時間軸表格標題列
        timeline_header = QHBoxLayout()
        timeline_header.addWidget(QLabel("首領技能時間軸 (點擊可在圖表上標記)"))
        self.btn_clear_markers = QPushButton("清除標記")
        self.btn_clear_markers.clicked.connect(self.clear_markers)
        timeline_header.addWidget(self.btn_clear_markers)
        right_layout.addLayout(timeline_header)

        self.table_timeline = QTableWidget(0, 2)
        self.table_timeline.setHorizontalHeaderLabels(["時間", "施放技能"])
        self.table_timeline.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_timeline.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_timeline.cellClicked.connect(self.on_timeline_clicked)
        right_layout.addWidget(self.table_timeline, stretch=1)

        content_layout.addLayout(right_layout)

    # ==========================================
    # 工具方法
    # ==========================================
    def format_time(self, ms):
        seconds = int(ms // 1000)
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def format_time_sec(self, total_seconds):
        total_seconds = max(0, total_seconds)
        minutes = int(total_seconds) // 60
        secs = int(total_seconds) % 60
        return f"{minutes:02d}:{secs:02d}"

    # ==========================================
    # 十字準線 (Crosshair) — 滑鼠移動時顯示座標
    # ==========================================
    def mouse_moved(self, evt):
        pos = evt[0]
        if not self.graph_widget.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.graph_widget.plotItem.vb.mapSceneToView(pos)
        x, y = mouse_point.x(), mouse_point.y()
        self.vLine.setPos(x)
        self.hLine.setPos(y)
        time_str = self.format_time_sec(x)
        self.crosshair_label.setText(f"時間: {time_str}  傷害: {y:,.0f}")
        self.crosshair_label.setPos(x, y)

    # ==========================================
    # 點擊時間軸 → 在圖表上標記
    # ==========================================
    def on_timeline_clicked(self, row, _col):
        time_item = self.table_timeline.item(row, 0)
        skill_item = self.table_timeline.item(row, 1)
        if not time_item:
            return
        parts = time_item.text().split(":")
        if len(parts) != 2:
            return
        total_seconds = int(parts[0]) * 60 + int(parts[1])

        # 垂直標記線
        line = pg.InfiniteLine(pos=total_seconds, angle=90,
                               pen=pg.mkPen('#00FFFF', width=2, style=Qt.PenStyle.DashDotLine))
        self.graph_widget.addItem(line)
        self.timeline_markers.append(line)

        # 技能名稱標籤
        if skill_item:
            skill_name = skill_item.text().split(' (')[0]
            y_max = max(self.graph_damages) * 0.95 if self.graph_damages else 0
            label = pg.TextItem(text=skill_name, color='#00FFFF', anchor=(0.5, 1))
            label.setPos(total_seconds, y_max)
            self.graph_widget.addItem(label)
            self.timeline_markers.append(label)

    def clear_markers(self):
        for item in self.timeline_markers:
            self.graph_widget.removeItem(item)
        self.timeline_markers.clear()

    # ==========================================
    # 載入首領列表
    # ==========================================
    def load_fights_list(self):
        report_id = self.input_report.text().strip()
        if not report_id:
            return
        self.btn_load_fights.setEnabled(False)
        self.btn_load_fights.setText("讀取中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_report_fights(report_id)
            fights = data.get('data', {}).get('reportData', {}).get('report', {}).get('fights', [])
            self.combo_fight.clear()
            for fight in fights:
                diff = "傳奇" if fight['difficulty'] == 5 else ("英雄" if fight['difficulty'] == 4 else "普通")
                fight_data = {'id': fight['id'], 'start': fight['startTime'], 'end': fight['endTime']}
                self.combo_fight.addItem(f"[{diff}] {fight['name']} (ID: {fight['id']})", userData=fight_data)
            if fights:
                self.btn_load_data.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", str(e))
        finally:
            self.btn_load_fights.setEnabled(True)
            self.btn_load_fights.setText("1. 取得首領列表")

    # ==========================================
    # 載入戰鬥數據
    # ==========================================
    def load_data(self):
        report_id = self.input_report.text().strip()
        fight_info = self.combo_fight.currentData()
        if not report_id or not fight_info:
            return
        self.btn_load_data.setEnabled(False)
        self.btn_load_data.setText("載入中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_fight_data(
                report_id, fight_info['id'], fight_info['start'], fight_info['end']
            )
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})

            # 1. 處理陣容
            self.list_roster.clear()
            actors = report_data.get('masterData', {}).get('actors', [])
            for p in actors:
                eng_class = p.get('subType', 'Unknown')
                cht_class = self.class_translation.get(eng_class, eng_class)
                item = QListWidgetItem(f"[{cht_class}] {p['name']}")
                item.setForeground(QColor(self.class_colors.get(eng_class, "#FFFFFF")))
                self.list_roster.addItem(item)

            # 2. 處理時間軸
            ability_map = {a['gameID']: a['name'] for a in report_data.get('masterData', {}).get('abilities', [])}
            self.table_timeline.setRowCount(0)
            events = report_data.get('events', {}).get('data', [])
            cast_events = [e for e in events if e.get('type') == 'cast']
            if cast_events:
                start_time = cast_events[0]['timestamp']
                for i, event in enumerate(cast_events):
                    rel_time = event['timestamp'] - start_time
                    spell_id = event.get('abilityGameID', 0)
                    cht_name = ability_map.get(spell_id, "未知技能")
                    self.table_timeline.insertRow(i)
                    self.table_timeline.setItem(i, 0, QTableWidgetItem(self.format_time(rel_time)))
                    self.table_timeline.setItem(i, 1, QTableWidgetItem(f"{cht_name} ({spell_id})"))

            # 3. 處理與畫出圖表
            self.clear_markers()
            raw_graph = report_data.get('graph', {})
            if isinstance(raw_graph, str):
                try:
                    raw_graph = json.loads(raw_graph)
                except Exception:
                    raw_graph = {}

            graph_data = raw_graph if isinstance(raw_graph, dict) else {}
            series_list = graph_data.get('series', [])
            if not series_list and isinstance(graph_data.get('data'), dict):
                series_list = graph_data['data'].get('series', [])

            time_buckets = {}
            for series in series_list:
                if not isinstance(series, dict) or 'data' not in series:
                    continue
                pts = series['data']
                point_start = series.get('pointStart', graph_data.get('pointStart', 0))
                point_interval = series.get('pointInterval', graph_data.get('pointInterval', 1000))
                for idx, pt in enumerate(pts):
                    if isinstance(pt, (int, float)):
                        t_ms = point_start + idx * point_interval
                        time_buckets[t_ms] = time_buckets.get(t_ms, 0) + pt
                    elif isinstance(pt, list) and len(pt) >= 2:
                        t_ms, dmg = pt[0], pt[1]
                        time_buckets[t_ms] = time_buckets.get(t_ms, 0) + dmg

            self.graph_widget.clear()
            # 重新加回十字準線 (clear 會移除所有物件)
            self.graph_widget.addItem(self.vLine, ignoreBounds=True)
            self.graph_widget.addItem(self.hLine, ignoreBounds=True)
            self.graph_widget.addItem(self.crosshair_label, ignoreBounds=True)

            self.graph_times, self.graph_damages = [], []
            if time_buckets:
                sorted_times = sorted(time_buckets.keys())
                graph_start_time = sorted_times[0]
                for t in sorted_times:
                    self.graph_times.append((t - graph_start_time) / 1000.0)
                    self.graph_damages.append(time_buckets[t])
                self.graph_widget.plot(self.graph_times, self.graph_damages,
                                       pen=pg.mkPen('r', width=2), fillLevel=0, brush=(255, 0, 0, 50))

            # 4. 填充治療大招分配表
            player_details = report_data.get('playerDetails', {})
            self.populate_healer_cds(actors, player_details)

        except Exception as e:
            QMessageBox.critical(self, "載入失敗", f"發生錯誤: {str(e)}")
        finally:
            self.btn_load_data.setEnabled(True)
            self.btn_load_data.setText("2. 載入戰鬥數據")

    # ==========================================
    # 填充治療大招分配表
    # ==========================================
    def populate_healer_cds(self, actors, player_details):
        self.table_healer_cds.setRowCount(0)

        # 收集所有德魯伊 (不管角色定位)
        all_druids = {a['name'] for a in actors if a.get('subType') == 'Druid'}

        # 嘗試從 playerDetails 辨識治療者
        healers = []
        if isinstance(player_details, dict):
            pd = player_details
            if 'data' in pd and isinstance(pd['data'], dict):
                pd = pd['data']
            if 'playerDetails' in pd and isinstance(pd['playerDetails'], dict):
                pd = pd['playerDetails']
            healer_list = pd.get('healers', [])
            for h in healer_list:
                if isinstance(h, dict):
                    healers.append({'name': h.get('name', ''), 'class': h.get('type', '')})

        # 備援：若 playerDetails 無法取得，依職業判斷
        if not healers:
            healer_classes = {"Priest", "Paladin", "Shaman", "Druid", "Monk", "Evoker"}
            for actor in actors:
                if actor.get('subType') in healer_classes:
                    healers.append({'name': actor['name'], 'class': actor['subType']})

        healer_names_set = set()
        row = 0
        for healer in healers:
            h_name, h_class = healer['name'], healer['class']
            healer_names_set.add(h_name)

            # 該職業的治療大招
            cds = self.healer_cooldowns.get(h_class, [])
            for cd in cds:
                self._add_healer_cd_row(row, h_name, h_class, cd['name'], cd['spell_id'])
                row += 1

            # 德魯伊額外加奔竄咆哮
            if h_class == 'Druid':
                self._add_healer_cd_row(row, h_name, h_class,
                                        self.druid_utility['name'], self.druid_utility['spell_id'])
                row += 1

        # 非治療的德魯伊也加奔竄咆哮
        for druid_name in sorted(all_druids - healer_names_set):
            self._add_healer_cd_row(row, druid_name, 'Druid',
                                    self.druid_utility['name'], self.druid_utility['spell_id'])
            row += 1

    def _add_healer_cd_row(self, row, player_name, player_class, skill_name, spell_id):
        self.table_healer_cds.insertRow(row)

        name_item = QTableWidgetItem(player_name)
        name_item.setForeground(QColor(self.class_colors.get(player_class, "#FFFFFF")))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table_healer_cds.setItem(row, 0, name_item)

        skill_item = QTableWidgetItem(skill_name)
        skill_item.setFlags(skill_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        skill_item.setData(Qt.ItemDataRole.UserRole, spell_id)
        self.table_healer_cds.setItem(row, 1, skill_item)

        time_item = QTableWidgetItem("")
        time_item.setToolTip("輸入時間，格式 MM:SS (例如 01:30)")
        self.table_healer_cds.setItem(row, 2, time_item)

    # ==========================================
    # 匯出 NSRT Note 格式
    # ==========================================
    def export_nsrt(self):
        entries = []
        for row in range(self.table_healer_cds.rowCount()):
            time_item = self.table_healer_cds.item(row, 2)
            if not time_item or not time_item.text().strip():
                continue
            player_item = self.table_healer_cds.item(row, 0)
            skill_item = self.table_healer_cds.item(row, 1)
            time_str = time_item.text().strip()
            player_name = player_item.text() if player_item else ""
            spell_id = skill_item.data(Qt.ItemDataRole.UserRole) if skill_item else 0
            # 解析時間以便排序
            parts = time_str.split(":")
            sort_key = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() else 9999
            entries.append((sort_key, time_str, spell_id, player_name))

        if not entries:
            QMessageBox.information(self, "匯出", "沒有已分配時間的減傷技能可匯出。\n請先在「分配時間」欄填入 MM:SS 格式的時間。")
            return

        entries.sort(key=lambda x: x[0])
        lines = [f"{{time:{t},SCC}} {{spell:{sid}}} {name}" for _, t, sid, name in entries]
        note_text = "\n".join(lines)

        clipboard = QApplication.clipboard()
        clipboard.setText(note_text)
        QMessageBox.information(self, "匯出成功", f"已複製到剪貼簿！\n\n{note_text}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ViserioCloneApp()
    window.show()
    sys.exit(app.exec())