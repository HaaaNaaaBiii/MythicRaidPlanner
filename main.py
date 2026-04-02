import sys
import json
import os
import requests
import pyqtgraph as pg
from requests.auth import HTTPBasicAuth
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLineEdit, QLabel,
                             QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QMessageBox,
                             QHeaderView, QComboBox, QAbstractItemView, QFileDialog, QMenu,
                             QSplitter)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QAction, QFont, QIcon

# ==========================================
# 1. API 客戶端模組
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

    def _ensure_token(self):
        if not self.token and not self.authenticate():
            raise Exception("無法獲取 API Token，請檢查金鑰。")

    def _post(self, query, variables):
        self._ensure_token()
        api_url = "https://tw.warcraftlogs.com/api/v2/client"
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        response = requests.post(api_url, json={'query': query, 'variables': variables}, headers=headers)
        if response.status_code == 200:
            result = response.json()
            if 'errors' in result:
                error_msg = result['errors'][0].get('message', '未知 GraphQL 錯誤')
                raise Exception(f"WCL 回報語法錯誤:\n{error_msg}")
            return result
        raise Exception(f"API 請求失敗: {response.status_code}")

    def fetch_report_fights(self, report_id):
        query = """
        query($code: String!) {
            reportData {
                report(code: $code) {
                    fights {
                        id
                        name
                        difficulty
                        kill
                        startTime
                        endTime
                    }
                }
            }
        }
        """
        return self._post(query, {"code": report_id})

    def fetch_fight_data(self, report_id, fight_id, start_time, end_time):
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
            "code": report_id, "fightId": int(fight_id),
            "start": float(start_time), "end": float(end_time)
        }
        return self._post(query, variables)

    def fetch_friendly_casts(self, report_id, fight_id, start_time, end_time):
        """抓取友方施法事件 (治療大招、爆發、團隊減傷)"""
        query = """
        query($code: String!, $fightId: Int!, $start: Float!, $end: Float!) {
            reportData {
                report(code: $code) {
                    masterData {
                        actors(type: "Player") { id name subType }
                    }
                    events(fightIDs: [$fightId], startTime: $start, endTime: $end,
                           dataType: Casts, hostilityType: Friendlies,
                           limit: 10000) { data }
                }
            }
        }
        """
        variables = {
            "code": report_id, "fightId": int(fight_id),
            "start": float(start_time), "end": float(end_time)
        }
        return self._post(query, variables)

    def fetch_reference_data(self, report_id, fight_id, start_time, end_time):
        """只抓圖表 + 時間軸 (不需 playerDetails)"""
        query = """
        query($code: String!, $fightId: Int!, $start: Float!, $end: Float!) {
            reportData {
                report(code: $code) {
                    masterData {
                        abilities { gameID name }
                    }
                    events(fightIDs: [$fightId], dataType: Casts, hostilityType: Enemies, limit: 10000) { data }
                    graph(startTime: $start, endTime: $end, dataType: DamageTaken, hostilityType: Friendlies)
                }
            }
        }
        """
        variables = {
            "code": report_id, "fightId": int(fight_id),
            "start": float(start_time), "end": float(end_time)
        }
        return self._post(query, variables)


# ==========================================
# 自定義時間軸 (mm:ss)
# ==========================================
class TimeAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [f"{int(max(0,v))//60:02d}:{int(max(0,v))%60:02d}" for v in values]

# ==========================================
# 2. GUI 主視窗模組
# ==========================================
class ViserioCloneApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mythic Raid Tactical Planner (WCL Integration)")
        self.setGeometry(100, 100, 1400, 950)
        # 設定視窗圖示
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dmc.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.api_client = WCLClient()

        self.class_translation = {
            "DeathKnight": "死亡騎士", "DemonHunter": "惡魔獵人", "Druid": "德魯伊",
            "Evoker": "喚能師", "Hunter": "獵人", "Mage": "法師", "Monk": "武僧",
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
        self.healer_cooldowns = {
            "Priest": [
                {"name": "神聖禮頌", "spell_id": 64843, "cd": 180, "dur": 8},
                {"name": "群體驅魔", "spell_id": 32375, "cd": 120, "dur": 1},
                {"name": "神化", "spell_id": 200183, "cd": 120, "dur": 20},
                {"name": "聖言術：救贖", "spell_id": 265202, "cd": 720, "dur": 1},
                {"name": "心靈狂喜", "spell_id": 47536, "cd": 90, "dur": 30},
                {"name": "真言術：壁", "spell_id": 62618, "cd": 180, "dur": 10},
            ],
            "Paladin": [
                {"name": "精通光環", "spell_id": 31821, "cd": 180, "dur": 8},
                {"name": "復仇之怒", "spell_id": 31884, "cd": 120, "dur": 20},
            ],
            "Shaman": [
                {"name": "靈魂連結圖騰", "spell_id": 98008, "cd": 180, "dur": 6},
                {"name": "療癒之潮圖騰", "spell_id": 108280, "cd": 180, "dur": 10},
                {"name": "升騰", "spell_id": 114052, "cd": 180, "dur": 15},
            ],
            "Druid": [
                {"name": "寧靜", "spell_id": 740, "cd": 180, "dur": 6},
                {"name": "召喚眾靈", "spell_id": 391528, "cd": 120, "dur": 4},
                {"name": "化身：生命之樹", "spell_id": 33891, "cd": 180, "dur": 30},
            ],
            "Monk": [
                {"name": "五氣歸元", "spell_id": 115310, "cd": 180, "dur": 6},
                {"name": "喚醒玉珑", "spell_id": 322118, "cd": 120, "dur": 25},
                {"name": "喚醒赤精", "spell_id": 325197, "cd": 120, "dur": 25},
            ],
            "Evoker": [
                {"name": "時光倒轉", "spell_id": 363534, "cd": 240, "dur": 4},
                {"name": "夢境飛行", "spell_id": 359816, "cd": 120, "dur": 6},
            ],
        }
        self.druid_utility = {"name": "奔竄咆哮", "spell_id": 106898, "cd": 120, "dur": 8}
        # 非治療職業的團隊減傷技能
        self.extra_raid_cds = {
            "DeathKnight": [{"name": "反魔法力場", "spell_id": 51052, "cd": 240, "dur": 6}],
            "Warrior": [{"name": "振奮咆哮", "spell_id": 97462, "cd": 180, "dur": 10}],
            "DemonHunter": [{"name": "黑暗", "spell_id": 196718, "cd": 300, "dur": 8}],
        }

        # Tracked spell mapping (for timeline feature)
        self.tracked_spells = {}
        for cls, cds in self.healer_cooldowns.items():
            for cd in cds:
                self.tracked_spells[cd['spell_id']] = {
                    'name': cd['name'], 'class': cls,
                    'cd': cd['cd'], 'dur': cd['dur'],
                    'type': '大招' if cd['cd'] >= 180 else '爆發',
                }
        self.tracked_spells[self.druid_utility['spell_id']] = {
            'name': self.druid_utility['name'], 'class': 'Druid',
            'cd': self.druid_utility['cd'], 'dur': self.druid_utility['dur'], 'type': '減傷',
        }
        for cls, cds in self.extra_raid_cds.items():
            for cd in cds:
                self.tracked_spells[cd['spell_id']] = {
                    'name': cd['name'], 'class': cls,
                    'cd': cd['cd'], 'dur': cd['dur'], 'type': '減傷',
                }
        # 彙整所有技能的 cd/dur 查詢表 (spell_id → {cd, dur})
        self._build_cd_lookup()

        # 首領技能描述標籤 (spell_id → 簡短說明)
        self.boss_ability_tags = {
            # ── Boss 1: 元首阿福扎恩 (Imperator Averzian) ──
            1249262: "分攤",           # 幽影坍縮
            1261249: "躲避",           # 虛空割裂
            1258883: "躲避",           # 虛空墜落
            1260712: "躲避",           # 湮滅之怒
            1284786: "躲避",           # 暗影方陣
            1249251: "團傷",           # 黑暗顛覆
            1265540: "坦克DOT",        # 黑化創傷
            1251361: "佔領",           # 暗影進軍
            1280035: "驅散",           # 宇宙殼壁
            1265490: "站位",           # 元首的榮耀
            # ── Boss 2: 弗拉希烏斯 (Vorasius) ──
            1260052: "拉人擊退",       # 始源咆哮
            1241692: "坦克分攤",       # 影爪重擊
            1259186: "小怪",           # 氣泡爆裂
            1256855: "光束",           # 虛空吐息
            1244419: "滅團",           # 壓制脈衝
            # ── Boss 3: 威厄高爾 與 艾佐拉克 (Vaelgor & Ezzorak) ──
            1244672: "遠離",           # 虛界
            1262623: "光束",           # 虛無光束
            1244221: "恐懼",           # 亡者吐息
            1245391: "分攤球",         # 陰霾
            1244917: "分散+小怪",      # 虛空嚎叫
            1270189: "分坦",           # 暮光羈絆
            1265131: "坦克",           # 威厄之翼
            1245645: "坦克",           # 拉克獠牙
            1264467: "躲避",           # 龍尾掃擊
            1255763: "團傷DOT",        # 午夜化身
            1249748: "過場團傷",       # 午夜烈焰
            1248847: "過場",           # 輻光屏障
            1263623: "史詩機制",       # 宇宙滲透
            1251686: "小怪",           # 無縛暗影
            # ── Boss 4: 隕落之王薩哈達爾 (Fallen-King Salhadaar) ──
            1247738: "寶珠",           # 虛空融合
            1254081: "打斷",           # 破碎投影
            1275056: "史詩機制",       # 聯結屏障
            1248697: "地面區域",       # 專制命令
            1246175: "團傷+躲避",      # 熵能瓦解
            1250803: "躲避",           # 粉碎暮光
            1250686: "團傷DOT",        # 扭曲遮蔽
            1271577: "坦克DOT",        # 影蝕打擊
            # ── Boss 5: 光盲先鋒軍 (Lightblinded Vanguard) ──
            1276243: "史詩強化",       # 狂熱之魂
            1246384: "驅散",           # 聖盾術
            1248449: "強化",           # 光環
            1246155: "地面區域",       # 神聖奉獻
            1248983: "分攤",           # 處決宣判
            1246765: "範圍傷害",       # 神聖風暴
            1246485: "分散",           # 復仇者之盾
            1255738: "團傷DOT",        # 灼熱光輝
            1248644: "躲避",           # 聖潔鳴鐘
            1248674: "躲避",           # 聖潔護盾
            1251857: "坦克",           # 審判
            1258514: "打斷",           # 盲目之光
            1246749: "團傷",           # 神聖鳴罪
            1258659: "團傷DOT",        # 聖光灌注
            1246745: "坦克",           # 驅邪術
            # ── Boss 6: 宇宙之冠 (Crown of the Cosmos) ──
            1233602: "瞄準",           # 銀擊箭
            1232467: "瞄準",           # 空虛之握 P1
            1232470: "瞄準",           # 空虛之握 P3
            1255368: "躲避",           # 虛空噴發
            1243743: "沉默",           # 震顫打斷
            1243753: "躲避",           # 貪噬深淵
            1261531: "小怪",           # 腐蝕精華
            1233865: "治療吸收",       # 虛無冕冠
            1233787: "坦克",           # 暗之手
            1234569: "過場",           # 恆星放射
            1243982: "躲避",           # 銀擊彈幕
            1237729: "瞄準",           # 銀擊跳彈
            1246918: "護盾",           # 宇宙屏障
            1237038: "DOT",            # 虛蹤者之刺
            1246461: "坦克",           # 裂隙斬擊
            1238206: "地面",           # 不穩裂隙
            1239080: "連線",           # 終結之相
            1238843: "換平台",         # 吞噬宇宙
            # ── Boss 7: 奇美魯斯 (Chimaerus the Undreamt God) ──
            1267201: "遠離",           # 不諧
            1262289: "分攤",           # 艾林之塵劇變
            1258610: "召喚小怪",       # 裂隙湧現
            1245727: "吸收護盾",       # 艾林帷幕
            1264756: "遠離",           # 裂隙瘋狂
            1257087: "驅散",           # 吞噬瘴氣
            1272726: "坦克",           # 撕裂開裂
            1245396: "團傷",           # 吞噬
            1246621: "團傷DOT",        # 腐蝕黏痰
            1250953: "治療吸收",       # 裂隙疲弊
            1249207: "團傷",           # 不諧咆哮
            1262020: "坦克",           # 巨像打擊
            1249017: "打斷",           # 可怖戰吼
            1261997: "打斷",           # 精華箭矢
            1245486: "躲避+小怪",      # 腐化毀滅
            1245406: "團傷",           # 貪食俯衝
            # ── Boss 8: 貝洛倫 (Belo'ren) — 攻略尚未發布 ──
            # ── Boss 9: 午夜降臨 (Midnight Falls) — 攻略尚未發布 ──
        }

        # 狀態資料
        self.timeline_markers = []
        self.timeline_row_markers = {}   # row → [marker_items]  用於 toggle
        self.boss_graph_items = []       # 圖表上的 boss 技能標籤
        self.healer_cd_graph_items = []    # 圖表上的治療/減傷技能標籤
        self.actual_cd_graph_items = []  # 圖表上的實際 CD 使用標籤
        self.actual_cooldowns = []       # 我的團隊實際 CD
        self.ref_cooldowns = []          # 參考 WCL 實際 CD
        self.merged_timeline = []        # [(start_ms, end_ms, spell_id, name)]
        self.graph_times = []
        self.graph_damages = []
        self.current_actors = []
        self.current_timeline = []

        self._build_ui()
        # 圖表左鍵點擊 → 開啟技能分配選單
        self.graph_widget.scene().sigMouseClicked.connect(self.on_graph_clicked)

    def _build_cd_lookup(self):
        """建立 spell_id → {cd, dur} 對照表"""
        self.cd_lookup = {}
        for cds in self.healer_cooldowns.values():
            for s in cds:
                self.cd_lookup[s['spell_id']] = {'cd': s['cd'], 'dur': s['dur']}
        self.cd_lookup[self.druid_utility['spell_id']] = {
            'cd': self.druid_utility['cd'], 'dur': self.druid_utility['dur']}
        for cds in self.extra_raid_cds.values():
            for s in cds:
                self.cd_lookup[s['spell_id']] = {'cd': s['cd'], 'dur': s['dur']}

    # ==========================================
    # UI 建構
    # ==========================================
    def _build_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # ── Row 1: 我的團隊 WCL ──
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("我的團隊 WCL:"))
        self.input_report = QLineEdit()
        self.input_report.setPlaceholderText("輸入 Report ID")
        self.input_report.setText("2mYrpayGhN1PLRfF")
        self.input_report.setFixedWidth(200)
        row1.addWidget(self.input_report)
        self.btn_load_fights = QPushButton("取得首領列表")
        self.btn_load_fights.clicked.connect(self.load_fights_list)
        row1.addWidget(self.btn_load_fights)
        self.combo_fight = QComboBox()
        self.combo_fight.setMinimumWidth(300)
        row1.addWidget(self.combo_fight)
        self.btn_load_roster = QPushButton("載入陣容")
        self.btn_load_roster.clicked.connect(self.load_roster)
        self.btn_load_roster.setEnabled(False)
        row1.addWidget(self.btn_load_roster)
        self.btn_load_own_damage = QPushButton("載入承傷數據")
        self.btn_load_own_damage.clicked.connect(self.load_own_damage_data)
        self.btn_load_own_damage.setEnabled(False)
        row1.addWidget(self.btn_load_own_damage)
        self.btn_load_own_timeline = QPushButton("載入技能時間軸")
        self.btn_load_own_timeline.clicked.connect(lambda: self.load_cooldown_timeline('own'))
        self.btn_load_own_timeline.setEnabled(False)
        row1.addWidget(self.btn_load_own_timeline)
        self.btn_export_own_timeline = QPushButton("匯出時間軸 MRT")
        self.btn_export_own_timeline.clicked.connect(lambda: self.export_timeline_mrt('own'))
        row1.addWidget(self.btn_export_own_timeline)
        row1.addStretch()
        layout.addLayout(row1)

        # ── Row 2: 參考 WCL ──
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("參考 WCL:       "))
        self.input_ref_report = QLineEdit()
        self.input_ref_report.setPlaceholderText("輸入參考 Report ID (別人的 WCL)")
        self.input_ref_report.setFixedWidth(200)
        row2.addWidget(self.input_ref_report)
        self.btn_ref_fights = QPushButton("取得首領列表")
        self.btn_ref_fights.clicked.connect(self.load_ref_fights_list)
        row2.addWidget(self.btn_ref_fights)
        self.combo_ref_fight = QComboBox()
        self.combo_ref_fight.setMinimumWidth(300)
        row2.addWidget(self.combo_ref_fight)
        self.btn_load_ref = QPushButton("導入承傷數據")
        self.btn_load_ref.clicked.connect(self.load_reference_data)
        self.btn_load_ref.setEnabled(False)
        row2.addWidget(self.btn_load_ref)
        self.btn_load_ref_timeline = QPushButton("導入技能時間軸")
        self.btn_load_ref_timeline.clicked.connect(lambda: self.load_cooldown_timeline('ref'))
        self.btn_load_ref_timeline.setEnabled(False)
        row2.addWidget(self.btn_load_ref_timeline)
        self.btn_export_ref_timeline = QPushButton("匯出時間軸 MRT")
        self.btn_export_ref_timeline.clicked.connect(lambda: self.export_timeline_mrt('ref'))
        row2.addWidget(self.btn_export_ref_timeline)
        row2.addStretch()
        layout.addLayout(row2)

        # ── Row 3: 動作按鈕 ──
        row3 = QHBoxLayout()
        self.btn_save = QPushButton("💾 儲存方案")
        self.btn_save.clicked.connect(self.save_plan)
        row3.addWidget(self.btn_save)
        self.btn_load_plan = QPushButton("📂 載入方案")
        self.btn_load_plan.clicked.connect(self.load_plan)
        row3.addWidget(self.btn_load_plan)
        self.btn_export = QPushButton("匯出 MRT Note")
        self.btn_export.clicked.connect(self.export_mrt)
        row3.addWidget(self.btn_export)
        self.btn_import_mrt = QPushButton("匯入 MRT Note")
        self.btn_import_mrt.clicked.connect(self.import_mrt)
        row3.addWidget(self.btn_import_mrt)
        row3.addStretch()
        version_label = QLabel("Ver 1.0.0 (For WoW12.0)  |  Developer NC  |  Discord HaaaNaaaBiii")
        version_label.setStyleSheet("color: #888888; font-size: 10px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row3.addWidget(version_label)
        layout.addLayout(row3)

        # ── 主內容區 (QSplitter 可拖動調整大小) ──
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(main_splitter, stretch=1)

        # --- 左側面板 ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("團隊陣容 (Roster)"))
        self.list_roster = QListWidget()
        left_layout.addWidget(self.list_roster)

        left_layout.addWidget(QLabel("治療大招分配 (Healer CD Assignment)"))
        self.table_healer_cds = QTableWidget(0, 3)
        self.table_healer_cds.setHorizontalHeaderLabels(["玩家", "技能", "分配時間 (MM:SS)"])
        self.table_healer_cds.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table_healer_cds.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.table_healer_cds.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table_healer_cds.setColumnWidth(0, 80)
        self.table_healer_cds.setColumnWidth(1, 100)
        self.table_healer_cds.cellChanged.connect(self._on_healer_cd_changed)
        left_layout.addWidget(self.table_healer_cds)
        main_splitter.addWidget(left_panel)

        # --- 右側面板 (圖表 + 時間軸，上下可拖動) ---
        right_splitter = QSplitter(Qt.Orientation.Vertical)

        time_axis = TimeAxisItem(orientation='bottom')
        self.graph_widget = pg.PlotWidget(title="團隊總承傷 (Total Damage Taken)", axisItems={'bottom': time_axis})
        self.graph_widget.setLabel('bottom', '時間')
        self.graph_widget.setLabel('left', '傷害量')
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setBackground('#1e1e1e')

        # 十字準線
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
        right_splitter.addWidget(self.graph_widget)

        # 時間軸
        timeline_panel = QWidget()
        timeline_layout = QVBoxLayout(timeline_panel)
        timeline_layout.setContentsMargins(0, 0, 0, 0)
        timeline_header = QHBoxLayout()
        timeline_header.addWidget(QLabel("首領技能時間軸 (點擊可在圖表上標記)"))
        self.btn_clear_markers = QPushButton("清除標記")
        self.btn_clear_markers.clicked.connect(self.clear_markers)
        timeline_header.addWidget(self.btn_clear_markers)
        timeline_layout.addLayout(timeline_header)

        self.table_timeline = QTableWidget(0, 2)
        self.table_timeline.setHorizontalHeaderLabels(["時間", "施放技能"])
        self.table_timeline.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_timeline.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_timeline.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_timeline.cellClicked.connect(self.on_timeline_clicked)
        timeline_layout.addWidget(self.table_timeline)
        right_splitter.addWidget(timeline_panel)

        # 設定右側 splitter 初始比例 (圖表 2/3, 時間軸 1/3)
        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)
        main_splitter.addWidget(right_splitter)

        # 設定左右 splitter 初始比例 (左 1/4, 右 3/4)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)

    # ==========================================
    # 工具方法
    # ==========================================
    def format_time(self, ms):
        seconds = int(ms // 1000)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def format_time_sec(self, total_seconds):
        total_seconds = max(0, total_seconds)
        return f"{int(total_seconds) // 60:02d}:{int(total_seconds) % 60:02d}"

    # ==========================================
    # 十字準線
    # ==========================================
    def mouse_moved(self, evt):
        pos = evt[0]
        if not self.graph_widget.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.graph_widget.plotItem.vb.mapSceneToView(pos)
        x, y = mouse_point.x(), mouse_point.y()
        self.vLine.setPos(x)
        self.hLine.setPos(y)
        self.crosshair_label.setText(f"時間: {self.format_time_sec(x)}  傷害: {y:,.0f}")
        self.crosshair_label.setPos(x, y)

    # ==========================================
    # 點擊時間軸 → 圖表標記
    # ==========================================
    @staticmethod
    def _parse_timeline_seconds(time_text):
        """解析時間軸文字，支援 'MM:SS' 及 'MM:SS - MM:SS' 兩種格式，回傳 (start_sec, end_sec)"""
        text = time_text.strip()
        if ' - ' in text:
            left, right = text.split(' - ', 1)
        else:
            left = right = text
        def _to_sec(s):
            p = s.strip().split(':')
            if len(p) == 2 and p[0].isdigit() and p[1].isdigit():
                return int(p[0]) * 60 + int(p[1])
            return None
        return _to_sec(left), _to_sec(right)

    def on_timeline_clicked(self, row, _col):
        time_item = self.table_timeline.item(row, 0)
        skill_item = self.table_timeline.item(row, 1)
        if not time_item:
            return
        start_sec, end_sec = self._parse_timeline_seconds(time_item.text())
        if start_sec is None:
            return

        # Toggle: 若該列已有標記則移除，否則新增
        if row in self.timeline_row_markers:
            for item in self.timeline_row_markers[row]:
                self.graph_widget.removeItem(item)
                if item in self.timeline_markers:
                    self.timeline_markers.remove(item)
            del self.timeline_row_markers[row]
            return

        items_added = []
        line = pg.InfiniteLine(pos=start_sec, angle=90,
                               pen=pg.mkPen('#00FFFF', width=2, style=Qt.PenStyle.DashDotLine))
        self.graph_widget.addItem(line)
        self.timeline_markers.append(line)
        items_added.append(line)
        # 若為時間範圍，加一條結束線
        if end_sec is not None and end_sec != start_sec:
            line2 = pg.InfiniteLine(pos=end_sec, angle=90,
                                    pen=pg.mkPen('#00FFFF', width=1, style=Qt.PenStyle.DotLine))
            self.graph_widget.addItem(line2)
            self.timeline_markers.append(line2)
            items_added.append(line2)
        if skill_item:
            skill_name = skill_item.text().split(' (')[0]
            y_max = max(self.graph_damages) * 0.95 if self.graph_damages else 0
            label = pg.TextItem(text=skill_name, color='#00FFFF', anchor=(0.5, 1))
            label.setPos(start_sec, y_max)
            self.graph_widget.addItem(label)
            self.timeline_markers.append(label)
            items_added.append(label)
        self.timeline_row_markers[row] = items_added

    def clear_markers(self):
        # 檢查是否有已分配的時間
        has_assignments = False
        for row in range(self.table_healer_cds.rowCount()):
            t_item = self.table_healer_cds.item(row, 2)
            if t_item and t_item.text().strip():
                has_assignments = True
                break

        if has_assignments:
            reply = QMessageBox.question(
                self, "確認清除",
                "目前有已分配的減傷/治療時間，清除標記將同時清除所有分配時間。\n確定要清除嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._do_clear_markers()

    def _do_clear_markers(self):
        """內部清除，不彈確認框"""
        for item in self.timeline_markers:
            self.graph_widget.removeItem(item)
        self.timeline_markers.clear()
        self.timeline_row_markers.clear()

        # 清除所有分配時間
        self.table_healer_cds.blockSignals(True)
        for row in range(self.table_healer_cds.rowCount()):
            t_item = self.table_healer_cds.item(row, 2)
            if t_item:
                t_item.setText("")
        self.table_healer_cds.blockSignals(False)
        self._draw_healer_cds_on_graph()

    # ==========================================
    # 圖表左鍵點擊 → 彈出技能分配選單
    # ==========================================
    def on_graph_clicked(self, evt):
        if evt.button() != Qt.MouseButton.LeftButton:
            return
        pos = evt.scenePos()
        if not self.graph_widget.sceneBoundingRect().contains(pos):
            return
        mouse_point = self.graph_widget.plotItem.vb.mapSceneToView(pos)
        click_sec = mouse_point.x()
        if click_sec < 0:
            return
        time_str = self.format_time_sec(click_sec)

        # 收集所有可用技能 (排除冷卻中的)
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { background-color: #2b2b2b; color: #ffffff; }"
                           "QMenu::item:selected { background-color: #3d6fa5; }")
        has_items = False
        for row in range(self.table_healer_cds.rowCount()):
            p_item = self.table_healer_cds.item(row, 0)
            s_item = self.table_healer_cds.item(row, 1)
            if not p_item or not s_item:
                continue
            player_name = p_item.text()
            player_class = p_item.data(Qt.ItemDataRole.UserRole) or ""
            skill_name = s_item.text()
            spell_id = s_item.data(Qt.ItemDataRole.UserRole) or 0

            # 檢查該技能是否在冷卻中
            if self._is_on_cooldown(row, spell_id, click_sec):
                continue

            color_hex = self.class_colors.get(player_class, "#FFFFFF")
            action = QAction(f"{player_name} — {skill_name}", menu)
            action.setData(row)
            # 用樣式上色
            action.setToolTip(f"分配至 {time_str}")
            menu.addAction(action)
            has_items = True

        if not has_items:
            action = QAction("(此時間點無可用技能)", menu)
            action.setEnabled(False)
            menu.addAction(action)

        chosen = menu.exec(evt.screenPos().toPoint())
        if chosen and chosen.data() is not None:
            target_row = chosen.data()
            t_item = self.table_healer_cds.item(target_row, 2)
            existing = t_item.text().strip()
            if existing:
                t_item.setText(f"{existing}, {time_str}")
            else:
                t_item.setText(time_str)
            self._draw_healer_cds_on_graph()

    def _on_healer_cd_changed(self, row, col):
        """當分配時間欄被編輯（包含刪除）時，刷新圖表上的治療技能標示"""
        if col == 2:
            self._draw_healer_cds_on_graph()

    @staticmethod
    def _parse_multi_times(text):
        """解析逗號分隔的多個 MM:SS 時間，回傳秒數列表"""
        result = []
        for seg in text.split(','):
            seg = seg.strip()
            parts = seg.split(':')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                result.append(int(parts[0]) * 60 + int(parts[1]))
        return result

    def _is_on_cooldown(self, row, spell_id, click_sec):
        """檢查某列技能在 click_sec 時是否仍在冷卻中"""
        t_item = self.table_healer_cds.item(row, 2)
        if not t_item or not t_item.text().strip():
            return False  # 尚未分配，不在冷卻
        info = self.cd_lookup.get(spell_id)
        if not info:
            return False
        for assigned_sec in self._parse_multi_times(t_item.text()):
            cd_end = assigned_sec + info['cd']
            if assigned_sec <= click_sec < cd_end:
                return True
        return False

    # ==========================================
    # 解析 graph 共用邏輯
    # ==========================================
    def _parse_graph(self, raw_graph):
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
                    time_buckets[pt[0]] = time_buckets.get(pt[0], 0) + pt[1]
        return time_buckets

    def _draw_graph(self, time_buckets):
        self.graph_widget.clear()
        self.boss_graph_items.clear()
        self.graph_widget.addItem(self.vLine, ignoreBounds=True)
        self.graph_widget.addItem(self.hLine, ignoreBounds=True)
        self.graph_widget.addItem(self.crosshair_label, ignoreBounds=True)
        self.graph_times, self.graph_damages = [], []
        if time_buckets:
            sorted_times = sorted(time_buckets.keys())
            t0 = sorted_times[0]
            for t in sorted_times:
                self.graph_times.append((t - t0) / 1000.0)
                self.graph_damages.append(time_buckets[t])
            self.graph_widget.plot(self.graph_times, self.graph_damages,
                                   pen=pg.mkPen('r', width=2), fillLevel=0, brush=(255, 0, 0, 50))

    def _fill_timeline(self, report_data):
        ability_map = {a['gameID']: a['name']
                       for a in report_data.get('masterData', {}).get('abilities', [])}
        self.table_timeline.setRowCount(0)
        self.current_timeline = []
        events = report_data.get('events', {}).get('data', [])
        cast_events = [e for e in events if e.get('type') == 'cast']
        if not cast_events:
            return

        start_time = cast_events[0]['timestamp']

        # 將連續相同 spell_id 的施放合併為時間範圍
        merged = []  # [(start_ms, end_ms, spell_id, name)]
        for event in cast_events:
            rel_time = event['timestamp'] - start_time
            spell_id = event.get('abilityGameID', 0)
            cht_name = ability_map.get(spell_id, "未知技能")
            if merged and merged[-1][2] == spell_id:
                # 同一技能連續施放 → 更新結束時間
                merged[-1] = (merged[-1][0], rel_time, spell_id, cht_name)
            else:
                merged.append((rel_time, rel_time, spell_id, cht_name))

        self.merged_timeline = merged
        for i, (t_start, t_end, spell_id, cht_name) in enumerate(merged):
            if t_start == t_end:
                time_str = self.format_time(t_start)
            else:
                time_str = f"{self.format_time(t_start)} - {self.format_time(t_end)}"
            tag = self.boss_ability_tags.get(spell_id, "")
            tag_suffix = f" [{tag}]" if tag else ""
            skill_str = f"{cht_name} ({spell_id}){tag_suffix}"
            self.current_timeline.append((time_str, skill_str))
            self.table_timeline.insertRow(i)
            t_item = QTableWidgetItem(time_str)
            t_item.setFlags(t_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_timeline.setItem(i, 0, t_item)
            s_item = QTableWidgetItem(skill_str)
            s_item.setFlags(s_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table_timeline.setItem(i, 1, s_item)

    # 只在圖表上顯示「造成團隊傷害」的標籤，排除純機制類
    DAMAGE_TAGS = {
        "分攤", "團傷", "團傷DOT", "範圍傷害", "分散", "分散+小怪",
        "滅團", "過場團傷", "團傷+躲避", "治療吸收", "DOT",
        "分攤球", "拉人擊退", "分坦", "瞄準", "驅散",
    }

    def _add_boss_labels_to_graph(self):
        """在圖表上以垂直虛線 + 文字標籤顯示會造成團隊傷害的首領技能"""
        for item in self.boss_graph_items:
            self.graph_widget.removeItem(item)
        self.boss_graph_items.clear()
        if not self.merged_timeline or not self.graph_damages or not self.graph_times:
            return

        # 建立時間→傷害的查詢函式 (找最近的數據點)
        import bisect
        times = self.graph_times
        damages = self.graph_damages

        def damage_at(sec):
            i = bisect.bisect_left(times, sec)
            if i >= len(times):
                return damages[-1]
            if i == 0:
                return damages[0]
            # 取較近的那個點
            if abs(times[i] - sec) < abs(times[i - 1] - sec):
                return damages[i]
            return damages[i - 1]

        for _idx, (t_start_ms, _t_end_ms, spell_id, name) in enumerate(self.merged_timeline):
            tag = self.boss_ability_tags.get(spell_id, "")
            if tag not in self.DAMAGE_TAGS:
                continue  # 跳過機制類標籤 (打斷/坦克/躲避/遠離…)
            x_sec = t_start_ms / 1000.0
            y_val = damage_at(x_sec)
            display = f"{name} [{tag}]"
            # 垂直虛線
            line = pg.InfiniteLine(
                pos=x_sec, angle=90,
                pen=pg.mkPen('#AAAAAA', width=1, style=Qt.PenStyle.DotLine))
            self.graph_widget.addItem(line, ignoreBounds=True)
            self.boss_graph_items.append(line)
            # 文字標籤 (Y 位置對齊該時間點的實際傷害值)
            label = pg.TextItem(text=display, color='#FFA500', anchor=(0.5, 0))
            label.setFont(QFont("Microsoft JhengHei", 10))
            label.setPos(x_sec, y_val)
            self.graph_widget.addItem(label, ignoreBounds=True)
            self.boss_graph_items.append(label)

    def _draw_healer_cds_on_graph(self):
        """在圖表上顯示已分配的治療/減傷技能，用水平線條表示持續時間"""
        import bisect
        for item in self.healer_cd_graph_items:
            self.graph_widget.removeItem(item)
        self.healer_cd_graph_items.clear()
        if not self.graph_times or not self.graph_damages:
            return

        times = self.graph_times
        damages = self.graph_damages
        y_max = max(damages)

        def damage_at(sec):
            i = bisect.bisect_left(times, sec)
            if i >= len(times):
                return damages[-1]
            if i == 0:
                return damages[0]
            if abs(times[i] - sec) < abs(times[i - 1] - sec):
                return damages[i]
            return damages[i - 1]

        lane_offset = 0  # 用於堆疊偏移避免重疊
        for row in range(self.table_healer_cds.rowCount()):
            t_item = self.table_healer_cds.item(row, 2)
            if not t_item or not t_item.text().strip():
                continue
            p_item = self.table_healer_cds.item(row, 0)
            s_item = self.table_healer_cds.item(row, 1)
            if not p_item or not s_item:
                continue
            player_name = p_item.text()
            player_class = p_item.data(Qt.ItemDataRole.UserRole) or ""
            skill_name = s_item.text()
            spell_id = s_item.data(Qt.ItemDataRole.UserRole) or 0
            color_hex = self.class_colors.get(player_class, "#FFFFFF")
            info = self.cd_lookup.get(spell_id)
            dur = info['dur'] if info else 0

            for assigned_sec in self._parse_multi_times(t_item.text()):
                end_sec = assigned_sec + dur
                y_val = damage_at(assigned_sec)
                # 堆疊偏移，讓多個技能不完全重疊
                y_draw = y_val - y_max * 0.03 * lane_offset

                # 持續時間水平線條
                if dur > 0:
                    bar = pg.PlotDataItem(
                        [assigned_sec, end_sec], [y_draw, y_draw],
                        pen=pg.mkPen(color_hex, width=4))
                    self.graph_widget.addItem(bar)
                    self.healer_cd_graph_items.append(bar)
                else:
                    # 無持續時間的技能畫一個短豎線
                    tick = pg.PlotDataItem(
                        [assigned_sec, assigned_sec], [y_draw - y_max * 0.02, y_draw + y_max * 0.02],
                        pen=pg.mkPen(color_hex, width=3))
                    self.graph_widget.addItem(tick)
                    self.healer_cd_graph_items.append(tick)

                # 文字標籤
                label = pg.TextItem(
                    text=f"{player_name} {skill_name}",
                    color=color_hex, anchor=(0, 1))
                label.setFont(QFont("Microsoft JhengHei", 8))
                label.setPos(assigned_sec, y_draw)
                self.graph_widget.addItem(label, ignoreBounds=True)
                self.healer_cd_graph_items.append(label)
                lane_offset += 1

    # ==========================================
    # 我的團隊: 取得首領列表
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
                if not fight.get('difficulty'):
                    continue  # 跳過 Trash Fights
                diff = "傳奇" if fight['difficulty'] == 5 else ("英雄" if fight['difficulty'] == 4 else "普通")
                kill_str = "擊殺" if fight.get('kill') else "滅團"
                fight_data = {'id': fight['id'], 'start': fight['startTime'], 'end': fight['endTime']}
                self.combo_fight.addItem(
                    f"[{diff}] {fight['name']} ({kill_str}) (ID: {fight['id']})", userData=fight_data)
            if fights:
                self.btn_load_roster.setEnabled(True)
                self.btn_load_own_damage.setEnabled(True)
                self.btn_load_own_timeline.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", str(e))
        finally:
            self.btn_load_fights.setEnabled(True)
            self.btn_load_fights.setText("取得首領列表")

    # ==========================================
    # 我的團隊: 載入承傷數據 (只更新右側圖表+時間軸)
    # ==========================================
    def load_own_damage_data(self):
        report_id = self.input_report.text().strip()
        fight_info = self.combo_fight.currentData()
        if not report_id or not fight_info:
            return
        self.btn_load_own_damage.setEnabled(False)
        self.btn_load_own_damage.setText("載入中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_reference_data(
                report_id, fight_info['id'], fight_info['start'], fight_info['end'])
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})
            self._do_clear_markers()
            time_buckets = self._parse_graph(report_data.get('graph', {}))
            self._draw_graph(time_buckets)
            self._fill_timeline(report_data)
            self._add_boss_labels_to_graph()
            self._draw_healer_cds_on_graph()
            self.graph_widget.setTitle(f"我的團隊承傷 — {self.combo_fight.currentText()}")
        except Exception as e:
            QMessageBox.critical(self, "載入失敗", f"發生錯誤: {str(e)}")
        finally:
            self.btn_load_own_damage.setEnabled(True)
            self.btn_load_own_damage.setText("載入承傷數據")

    # ==========================================
    # 我的團隊: 載入陣容 (只更新左側面板)
    # ==========================================
    def load_roster(self):
        report_id = self.input_report.text().strip()
        fight_info = self.combo_fight.currentData()
        if not report_id or not fight_info:
            return
        self.btn_load_roster.setEnabled(False)
        self.btn_load_roster.setText("載入中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_fight_data(
                report_id, fight_info['id'], fight_info['start'], fight_info['end']
            )
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})

            # 陣容
            self.list_roster.clear()
            actors = report_data.get('masterData', {}).get('actors', [])
            self.current_actors = [{'name': p['name'], 'class': p.get('subType', 'Unknown')}
                                   for p in actors]
            for p in self.current_actors:
                cht_class = self.class_translation.get(p['class'], p['class'])
                item = QListWidgetItem(f"[{cht_class}] {p['name']}")
                item.setForeground(QColor(self.class_colors.get(p['class'], "#FFFFFF")))
                self.list_roster.addItem(item)

            # 治療大招
            player_details = report_data.get('playerDetails', {})
            self.populate_healer_cds(actors, player_details)

            # 如果右側還沒有參考數據，也載入自己的圖表+時間軸
            if not self.graph_times:
                self._do_clear_markers()
                time_buckets = self._parse_graph(report_data.get('graph', {}))
                self._draw_graph(time_buckets)
                self._fill_timeline(report_data)
                self._add_boss_labels_to_graph()
                self._draw_healer_cds_on_graph()

        except Exception as e:
            QMessageBox.critical(self, "載入失敗", f"發生錯誤: {str(e)}")
        finally:
            self.btn_load_roster.setEnabled(True)
            self.btn_load_roster.setText("載入陣容")

    # ==========================================
    # 參考 WCL: 取得首領列表
    # ==========================================
    def load_ref_fights_list(self):
        report_id = self.input_ref_report.text().strip()
        if not report_id:
            return
        self.btn_ref_fights.setEnabled(False)
        self.btn_ref_fights.setText("讀取中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_report_fights(report_id)
            fights = data.get('data', {}).get('reportData', {}).get('report', {}).get('fights', [])
            self.combo_ref_fight.clear()
            for fight in fights:
                if not fight.get('difficulty'):
                    continue  # 跳過 Trash Fights
                diff = "傳奇" if fight['difficulty'] == 5 else ("英雄" if fight['difficulty'] == 4 else "普通")
                kill_str = "擊殺" if fight.get('kill') else "滅團"
                fight_data = {'id': fight['id'], 'start': fight['startTime'], 'end': fight['endTime']}
                self.combo_ref_fight.addItem(
                    f"[{diff}] {fight['name']} ({kill_str}) (ID: {fight['id']})", userData=fight_data)
            if fights:
                self.btn_load_ref.setEnabled(True)
                self.btn_load_ref_timeline.setEnabled(True)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", str(e))
        finally:
            self.btn_ref_fights.setEnabled(True)
            self.btn_ref_fights.setText("取得首領列表")

    # ==========================================
    # 參考 WCL: 導入承傷數據 (只更新右側面板)
    # ==========================================
    def load_reference_data(self):
        report_id = self.input_ref_report.text().strip()
        fight_info = self.combo_ref_fight.currentData()
        if not report_id or not fight_info:
            return
        self.btn_load_ref.setEnabled(False)
        self.btn_load_ref.setText("載入中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_reference_data(
                report_id, fight_info['id'], fight_info['start'], fight_info['end']
            )
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})

            self._do_clear_markers()
            time_buckets = self._parse_graph(report_data.get('graph', {}))
            self._draw_graph(time_buckets)
            self._fill_timeline(report_data)
            self._add_boss_labels_to_graph()
            self._draw_healer_cds_on_graph()

            self.graph_widget.setTitle(f"參考承傷 — {self.combo_ref_fight.currentText()}")
        except Exception as e:
            QMessageBox.critical(self, "載入失敗", f"發生錯誤: {str(e)}")
        finally:
            self.btn_load_ref.setEnabled(True)
            self.btn_load_ref.setText("導入承傷數據")

    # ==========================================
    # 填充治療大招分配表
    # ==========================================
    def populate_healer_cds(self, actors, player_details):
        self.table_healer_cds.setRowCount(0)
        all_druids = {a['name'] for a in actors if a.get('subType') == 'Druid'}

        healers = []
        if isinstance(player_details, dict):
            pd = player_details
            if 'data' in pd and isinstance(pd['data'], dict):
                pd = pd['data']
            if 'playerDetails' in pd and isinstance(pd['playerDetails'], dict):
                pd = pd['playerDetails']
            for h in pd.get('healers', []):
                if isinstance(h, dict):
                    healers.append({'name': h.get('name', ''), 'class': h.get('type', '')})
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
            for cd in self.healer_cooldowns.get(h_class, []):
                self._add_healer_cd_row(row, h_name, h_class, cd['name'], cd['spell_id'])
                row += 1
            if h_class == 'Druid':
                self._add_healer_cd_row(row, h_name, h_class,
                                        self.druid_utility['name'], self.druid_utility['spell_id'])
                row += 1
        for druid_name in sorted(all_druids - healer_names_set):
            self._add_healer_cd_row(row, druid_name, 'Druid',
                                    self.druid_utility['name'], self.druid_utility['spell_id'])
            row += 1

        # 死亡騎士、戰士的團隊減傷
        all_dks = {a['name'] for a in actors if a.get('subType') == 'DeathKnight'}
        all_warriors = {a['name'] for a in actors if a.get('subType') == 'Warrior'}
        for dk_name in sorted(all_dks):
            for cd in self.extra_raid_cds.get('DeathKnight', []):
                self._add_healer_cd_row(row, dk_name, 'DeathKnight', cd['name'], cd['spell_id'])
                row += 1
        for war_name in sorted(all_warriors):
            for cd in self.extra_raid_cds.get('Warrior', []):
                self._add_healer_cd_row(row, war_name, 'Warrior', cd['name'], cd['spell_id'])
                row += 1
        all_dhs = {a['name'] for a in actors if a.get('subType') == 'DemonHunter'}
        for dh_name in sorted(all_dhs):
            for cd in self.extra_raid_cds.get('DemonHunter', []):
                self._add_healer_cd_row(row, dh_name, 'DemonHunter', cd['name'], cd['spell_id'])
                row += 1

        # 個人減傷 (單一列，不綁定玩家)
        self._add_healer_cd_row(row, '', '', '個減', 0)
        row += 1

    def _add_healer_cd_row(self, row, player_name, player_class, skill_name, spell_id):
        self.table_healer_cds.insertRow(row)
        name_item = QTableWidgetItem(player_name)
        name_item.setForeground(QColor(self.class_colors.get(player_class, "#FFFFFF")))
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        name_item.setData(Qt.ItemDataRole.UserRole, player_class)
        self.table_healer_cds.setItem(row, 0, name_item)

        skill_item = QTableWidgetItem(skill_name)
        skill_item.setFlags(skill_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        skill_item.setData(Qt.ItemDataRole.UserRole, spell_id)
        self.table_healer_cds.setItem(row, 1, skill_item)

        time_item = QTableWidgetItem("")
        time_item.setToolTip("格式 MM:SS，多次使用逗號分隔 (例如 01:30, 04:00)")
        self.table_healer_cds.setItem(row, 2, time_item)

    # ==========================================
    # 載入實際技能時間軸 (own / ref)
    # ==========================================
    def load_cooldown_timeline(self, which='own'):
        if which == 'own':
            report_id = self.input_report.text().strip()
            fight_info = self.combo_fight.currentData()
            btn = self.btn_load_own_timeline
            label = "載入技能時間軸"
        else:
            report_id = self.input_ref_report.text().strip()
            fight_info = self.combo_ref_fight.currentData()
            btn = self.btn_load_ref_timeline
            label = "導入技能時間軸"
        if not report_id or not fight_info:
            QMessageBox.warning(self, "提示", "請先選擇報告與戰鬥")
            return
        btn.setEnabled(False)
        btn.setText("載入中...")
        QApplication.processEvents()
        try:
            data = self.api_client.fetch_friendly_casts(
                report_id, fight_info['id'], fight_info['start'], fight_info['end'])
            report_data = data.get('data', {}).get('reportData', {}).get('report', {})
            actors = report_data.get('masterData', {}).get('actors', [])
            actor_map = {a['id']: a for a in actors}
            events = report_data.get('events', {}).get('data', [])
            start_time = fight_info['start']
            cooldowns = []
            for ev in events:
                if ev.get('type') != 'cast':
                    continue
                spell_id = ev.get('abilityGameID', 0)
                if spell_id not in self.tracked_spells:
                    continue
                info = self.tracked_spells[spell_id]
                source_id = ev.get('sourceID')
                actor = actor_map.get(source_id, {})
                player_name = actor.get('name', '???')
                player_class = actor.get('subType', '')
                time_sec = (ev['timestamp'] - start_time) / 1000.0
                cooldowns.append({
                    'time_sec': time_sec,
                    'player_name': player_name,
                    'player_class': player_class,
                    'spell_name': info['name'],
                    'spell_id': spell_id,
                    'duration': info['dur'],
                    'type': info['type'],
                })
            if which == 'own':
                self.actual_cooldowns = cooldowns
            else:
                self.ref_cooldowns = cooldowns
            self._draw_actual_cds_on_graph()
            players = set(cd['player_name'] for cd in cooldowns)
            btn.setText(f"已載入 {len(cooldowns)} 筆 ({len(players)} 人)")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(3000, lambda: btn.setText(label))
        except Exception as e:
            QMessageBox.critical(self, "載入失敗", f"發生錯誤: {str(e)}")
        finally:
            btn.setEnabled(True)

    def _draw_actual_cds_on_graph(self):
        """在圖表上疊加顯示實際 CD 使用 (own + ref)"""
        for item in self.actual_cd_graph_items:
            self.graph_widget.removeItem(item)
        self.actual_cd_graph_items.clear()
        if not self.graph_times or not self.graph_damages:
            return
        y_max = max(self.graph_damages)

        all_cds = [(cd, 'own') for cd in self.actual_cooldowns] + \
                  [(cd, 'ref') for cd in self.ref_cooldowns]
        if not all_cds:
            return

        lane = 0
        for cd, source in all_cds:
            sec = cd['time_sec']
            dur = cd['duration']
            end_sec = sec + dur
            color_hex = self.class_colors.get(cd['player_class'], '#FFFFFF')
            y_draw = y_max * (0.92 - 0.035 * (lane % 20))
            opacity = 0.4 if source == 'ref' else 0.65
            source_tag = '(參考)' if source == 'ref' else ''

            if dur > 1:
                bar = pg.PlotDataItem(
                    [sec, end_sec], [y_draw, y_draw],
                    pen=pg.mkPen(color_hex, width=3,
                                 style=Qt.PenStyle.DashLine if source == 'own'
                                 else Qt.PenStyle.DotLine))
                bar.setOpacity(opacity)
                self.graph_widget.addItem(bar)
                self.actual_cd_graph_items.append(bar)
            else:
                tick = pg.PlotDataItem(
                    [sec, sec], [y_draw - y_max * 0.015, y_draw + y_max * 0.015],
                    pen=pg.mkPen(color_hex, width=2,
                                 style=Qt.PenStyle.DashLine))
                tick.setOpacity(opacity)
                self.graph_widget.addItem(tick)
                self.actual_cd_graph_items.append(tick)

            label = pg.TextItem(
                text=f"▸{cd['player_name']} {cd['spell_name']}{source_tag}",
                color=color_hex, anchor=(0, 1))
            label.setFont(QFont("Microsoft JhengHei", 7))
            label.setPos(sec, y_draw)
            label.setOpacity(opacity)
            self.graph_widget.addItem(label, ignoreBounds=True)
            self.actual_cd_graph_items.append(label)
            lane += 1

    # ==========================================
    # 匯出時間軸 MRT Note
    # ==========================================
    def export_timeline_mrt(self, which='own'):
        cds = self.actual_cooldowns if which == 'own' else self.ref_cooldowns
        label = '我的團隊' if which == 'own' else '參考 WCL'
        if not cds:
            QMessageBox.information(self, "匯出", f"尚未載入{label}的技能時間軸資料。")
            return
        entries = [self._cd_to_entry(cd) for cd in cds]
        entries.sort(key=lambda x: x[0])
        lines = []
        for sort_sec, time_str, spell_id, player, spell_name in entries:
            lines.append(f"{{time:{time_str}}} {player} {spell_name} {{spell:{spell_id}}}")
        note_text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        clipboard.setText(note_text)
        QMessageBox.information(self, f"匯出成功 ({label})", f"已複製到剪貼簿！\n共 {len(lines)} 筆\n\n{note_text}")

    @staticmethod
    def _cd_to_entry(cd):
        sec = int(cd['time_sec'])
        time_str = f"{sec // 60:02d}:{sec % 60:02d}"
        return (sec, time_str, cd['spell_id'], cd['player_name'], cd['spell_name'])

    # ==========================================
    # 匯出 MRT Note
    # ==========================================
    def export_mrt(self):
        entries = []
        for row in range(self.table_healer_cds.rowCount()):
            time_item = self.table_healer_cds.item(row, 2)
            if not time_item or not time_item.text().strip():
                continue
            player_item = self.table_healer_cds.item(row, 0)
            skill_item = self.table_healer_cds.item(row, 1)
            player_name = player_item.text() if player_item else ""
            spell_id = skill_item.data(Qt.ItemDataRole.UserRole) if skill_item else 0
            skill_name = skill_item.text() if skill_item else ""
            for sort_sec in self._parse_multi_times(time_item.text()):
                t = f"{sort_sec // 60:02d}:{sort_sec % 60:02d}"
                entries.append((sort_sec, t, spell_id, player_name, skill_name))
        if not entries:
            QMessageBox.information(self, "匯出",
                                    "沒有已分配時間的減傷技能可匯出。\n請先在「分配時間」欄填入 MM:SS 格式的時間。")
            return
        entries.sort(key=lambda x: x[0])
        lines = []
        for sort_sec, t, sid, name, skill_name in entries:
            if sid:
                lines.append(f"{{time:{t}}} {name} {skill_name} {{spell:{sid}}}")
            else:
                lines.append(f"{{time:{t}}} {name} {skill_name}")
        note_text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        clipboard.setText(note_text)
        QMessageBox.information(self, "匯出成功", f"已複製到剪貼簿！\n\n{note_text}")

    # ==========================================
    # 匯入 MRT Note
    # ==========================================
    # MRT 技能別名 → (正式技能名, spell_id)
    MRT_SKILL_ALIASES = {
        # 牧師
        "交招": ("神聖禮頌", 64843),
        "神聖禮頌": ("神聖禮頌", 64843),
        "群驅": ("群體驅魔", 32375),
        "群體驅魔": ("群體驅魔", 32375),
        "神化": ("神化", 200183),
        "救贖": ("聖言術：救贖", 265202),
        "聖言術：救贖": ("聖言術：救贖", 265202),
        "心靈狂喜": ("心靈狂喜", 47536),
        "狂喜": ("心靈狂喜", 47536),
        "真言術：壁": ("真言術：壁", 62618),
        "壁": ("真言術：壁", 62618),
        "屏障": ("真言術：壁", 62618),
        # 聖騎士
        "光環精通": ("精通光環", 31821),
        "精通光環": ("精通光環", 31821),
        "精通": ("精通光環", 31821),
        "復仇之怒": ("復仇之怒", 31884),
        "翅膀": ("復仇之怒", 31884),
        # 薩滿
        "靈連": ("靈魂連結圖騰", 98008),
        "靈魂連結": ("靈魂連結圖騰", 98008),
        "靈魂連結圖騰": ("靈魂連結圖騰", 98008),
        "療癒之潮": ("療癒之潮圖騰", 108280),
        "療癒之潮圖騰": ("療癒之潮圖騰", 108280),
        "潮汐": ("療癒之潮圖騰", 108280),
        "升騰": ("升騰", 114052),
        # 德魯伊
        "寧靜": ("寧靜", 740),
        "召喚眾靈": ("召喚眾靈", 391528),
        "化身：生命之樹": ("化身：生命之樹", 33891),
        "生命之樹": ("化身：生命之樹", 33891),
        "樹人": ("化身：生命之樹", 33891),
        "奔竄咆哮": ("奔竄咆哮", 106898),
        "咆哮": ("奔竄咆哮", 106898),
        # 武僧
        "五氣歸元": ("五氣歸元", 115310),
        "五氣": ("五氣歸元", 115310),
        "復甦之霧": ("五氣歸元", 115310),
        "召喚玉蛟尤龍": ("喚醒玉珑", 322118),
        "喚醒玉珑": ("喚醒玉珑", 322118),
        "玉蛟": ("喚醒玉珑", 322118),
        "喚醒赤精": ("喚醒赤精", 325197),
        "赤精": ("喚醒赤精", 325197),
        # 喚能師
        "時光倒轉": ("時光倒轉", 363534),
        "倒轉": ("時光倒轉", 363534),
        "夢境飛行": ("夢境飛行", 359816),
        # 團隊減傷
        "反魔法領域": ("反魔法力場", 51052),
        "反魔法力場": ("反魔法力場", 51052),
        "大罩": ("反魔法力場", 51052),
        "AMZ": ("反魔法力場", 51052),
        "amz": ("反魔法力場", 51052),
        "集結吶喊": ("振奮咆哮", 97462),
        "振奮咆哮": ("振奮咆哮", 97462),
        "吼血": ("振奮咆哮", 97462),
        "集結吶喊(吼血)": ("振奮咆哮", 97462),
        "黑暗": ("黑暗", 196718),
    }

    def import_mrt(self):
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self, "匯入 MRT Note",
            "貼上 MRT Note 內容 (支援遊戲內格式，含顏色碼、階段標記等):")
        if not ok or not text.strip():
            return
        import re
        imported = []  # [(sec, time_str, player, skill_name, spell_id)]

        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue

            # 1. 解析 {time:M:SS} 或 {time:M:SS,pN}
            time_match = re.match(r'\{time:(\d{1,2}:\d{2})(?:,p\d+)?\}', line)
            if not time_match:
                continue
            time_str = time_match.group(1)
            parts = time_str.split(':')
            sec = int(parts[0]) * 60 + int(parts[1])
            rest = line[time_match.end():]

            # 2. 清理: 移除 {spell:ID}、{rtN}、顏色碼結束標記
            rest = re.sub(r'\{spell:\d+\}', '', rest)
            rest = re.sub(r'\{rt\d+\}', '', rest)
            # 提取 |cffXXXXXX...文字...|r 中的文字，或保留無顏色碼的文字
            # 先把 |cffXXXXXX...|r 替換成 其中的文字部分
            rest = re.sub(r'\|cff[0-9a-fA-F]{6}([^|]*)\|r', r'\1', rest)
            rest = rest.strip()
            if not rest:
                continue

            # 3. 拆分多個「玩家 技能」段落
            #    每段格式: 玩家名 技能名(可能含括號別名)
            #    用連續空白分割後重新組合
            segments = self._parse_mrt_segments(rest)

            for player, skill_text in segments:
                # 嘗試用別名表匹配
                # skill_text 可能是 "光環精通"、"集結吶喊(吼血)"、"召喚玉蛟尤龍+五氣歸元"
                # 處理 "+" 分隔的多技能
                sub_skills = [s.strip() for s in skill_text.split('+')]
                for sub in sub_skills:
                    # 去掉括號中的別名部分用於匹配: "集結吶喊(吼血)" → 先試完整匹配，再試主名
                    alias_info = self.MRT_SKILL_ALIASES.get(sub)
                    if not alias_info:
                        # 試去掉括號
                        clean = re.sub(r'\(.*?\)', '', sub).strip()
                        alias_info = self.MRT_SKILL_ALIASES.get(clean)
                    if not alias_info:
                        # 試括號內的文字
                        paren = re.search(r'\((.+?)\)', sub)
                        if paren:
                            alias_info = self.MRT_SKILL_ALIASES.get(paren.group(1))
                    if alias_info:
                        skill_name, spell_id = alias_info
                        imported.append((sec, time_str, player, skill_name, spell_id))

        if not imported:
            QMessageBox.warning(self, "匯入失敗",
                                "未能解析任何可匹配的減傷/治療技能。\n"
                                "請確認 MRT Note 中包含已知的技能名稱。")
            return

        # 嘗試匹配到 healer_cds 表中
        matched = 0
        for sec, time_str, player, skill_name, spell_id in imported:
            for row in range(self.table_healer_cds.rowCount()):
                p_item = self.table_healer_cds.item(row, 0)
                s_item = self.table_healer_cds.item(row, 1)
                if not p_item or not s_item:
                    continue
                row_spell_id = s_item.data(Qt.ItemDataRole.UserRole) or 0
                if p_item.text() == player and row_spell_id == spell_id:
                    t_item = self.table_healer_cds.item(row, 2)
                    existing = t_item.text().strip() if t_item else ""
                    fmt = f"{sec // 60:02d}:{sec % 60:02d}"
                    if existing:
                        t_item.setText(f"{existing}, {fmt}")
                    else:
                        t_item.setText(fmt)
                    matched += 1
                    break
                    matched += 1
                    break

        # 在圖表上標記匯入的時間點
        self._draw_healer_cds_on_graph()
        QMessageBox.information(self, "匯入完成",
                                f"共解析 {len(imported)} 筆，成功匹配 {matched} 筆到減傷表。")

    def _parse_mrt_segments(self, text):
        """從清理後的 MRT 行文字中拆分出 [(玩家名, 技能名)] 列表。
        一行可能有多個「玩家 技能」，中間用空格分隔。
        技能名可能帶括號別名或 + 號連接多技能。
        """
        # 建立所有已知玩家名集合 (從 healer_cds 表)
        known_players = set()
        for row in range(self.table_healer_cds.rowCount()):
            p_item = self.table_healer_cds.item(row, 0)
            if p_item and p_item.text():
                known_players.add(p_item.text())

        segments = []
        tokens = text.split()
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token in known_players:
                # 收集後續非玩家名的 token 作為技能名
                skill_parts = []
                j = i + 1
                while j < len(tokens) and tokens[j] not in known_players:
                    skill_parts.append(tokens[j])
                    j += 1
                if skill_parts:
                    segments.append((token, ' '.join(skill_parts)))
                i = j
            else:
                i += 1
        return segments

    # ==========================================
    # 儲存方案
    # ==========================================
    def save_plan(self):
        path, _ = QFileDialog.getSaveFileName(self, "儲存減傷方案", "", "JSON 檔案 (*.json)")
        if not path:
            return
        healer_assignments = []
        for row in range(self.table_healer_cds.rowCount()):
            p_item = self.table_healer_cds.item(row, 0)
            s_item = self.table_healer_cds.item(row, 1)
            t_item = self.table_healer_cds.item(row, 2)
            healer_assignments.append({
                "player": p_item.text() if p_item else "",
                "class": p_item.data(Qt.ItemDataRole.UserRole) if p_item else "",
                "skill": s_item.text() if s_item else "",
                "spell_id": s_item.data(Qt.ItemDataRole.UserRole) if s_item else 0,
                "time": t_item.text() if t_item else "",
            })
        plan = {
            "version": 1,
            "own_report_id": self.input_report.text().strip(),
            "own_fight_text": self.combo_fight.currentText(),
            "ref_report_id": self.input_ref_report.text().strip(),
            "ref_fight_text": self.combo_ref_fight.currentText(),
            "roster": self.current_actors,
            "healer_cds": healer_assignments,
            "timeline": self.current_timeline,
            "graph_times": self.graph_times,
            "graph_damages": self.graph_damages,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "儲存成功", f"方案已儲存至:\n{path}")

    # ==========================================
    # 載入方案
    # ==========================================
    def load_plan(self):
        path, _ = QFileDialog.getOpenFileName(self, "載入減傷方案", "", "JSON 檔案 (*.json)")
        if not path:
            return
        with open(path, 'r', encoding='utf-8') as f:
            plan = json.load(f)

        # 還原 Report ID
        self.input_report.setText(plan.get("own_report_id", ""))
        self.input_ref_report.setText(plan.get("ref_report_id", ""))

        # 還原陣容
        self.current_actors = plan.get("roster", [])
        self.list_roster.clear()
        for p in self.current_actors:
            cht_class = self.class_translation.get(p['class'], p['class'])
            item = QListWidgetItem(f"[{cht_class}] {p['name']}")
            item.setForeground(QColor(self.class_colors.get(p['class'], "#FFFFFF")))
            self.list_roster.addItem(item)

        # 還原治療 CD 分配
        self.table_healer_cds.setRowCount(0)
        for i, cd in enumerate(plan.get("healer_cds", [])):
            self.table_healer_cds.insertRow(i)
            name_item = QTableWidgetItem(cd.get("player", ""))
            p_class = cd.get("class", "")
            name_item.setForeground(QColor(self.class_colors.get(p_class, "#FFFFFF")))
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setData(Qt.ItemDataRole.UserRole, p_class)
            self.table_healer_cds.setItem(i, 0, name_item)

            skill_item = QTableWidgetItem(cd.get("skill", ""))
            skill_item.setFlags(skill_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            skill_item.setData(Qt.ItemDataRole.UserRole, cd.get("spell_id", 0))
            self.table_healer_cds.setItem(i, 1, skill_item)

            time_item = QTableWidgetItem(cd.get("time", ""))
            self.table_healer_cds.setItem(i, 2, time_item)

        # 還原時間軸
        self.current_timeline = [tuple(t) for t in plan.get("timeline", [])]
        self.table_timeline.setRowCount(0)
        for i, (t_str, s_str) in enumerate(self.current_timeline):
            self.table_timeline.insertRow(i)
            self.table_timeline.setItem(i, 0, QTableWidgetItem(t_str))
            self.table_timeline.setItem(i, 1, QTableWidgetItem(s_str))

        # 還原圖表
        self._do_clear_markers()
        self.graph_times = plan.get("graph_times", [])
        self.graph_damages = plan.get("graph_damages", [])
        self.graph_widget.clear()
        self.graph_widget.addItem(self.vLine, ignoreBounds=True)
        self.graph_widget.addItem(self.hLine, ignoreBounds=True)
        self.graph_widget.addItem(self.crosshair_label, ignoreBounds=True)
        if self.graph_times and self.graph_damages:
            self.graph_widget.plot(self.graph_times, self.graph_damages,
                                   pen=pg.mkPen('r', width=2), fillLevel=0, brush=(255, 0, 0, 50))

        ref_text = plan.get("ref_fight_text", "")
        if ref_text:
            self.graph_widget.setTitle(f"參考承傷 — {ref_text}")
        else:
            self.graph_widget.setTitle("團隊總承傷 (Total Damage Taken)")

        QMessageBox.information(self, "載入成功", f"方案已從下列檔案還原:\n{path}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ViserioCloneApp()
    window.show()
    sys.exit(app.exec())
