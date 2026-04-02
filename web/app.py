"""
Mythic Raid Tactical Planner — Web Edition
Flask backend: proxies WCL API calls and serves the SPA.
"""
import os
import re
import json
import requests
from requests.auth import HTTPBasicAuth
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ── WCL API Client ──────────────────────────────────────
class WCLClient:
    def __init__(self):
        self.CLIENT_ID = os.environ.get(
            'WCL_CLIENT_ID', 'a15fb0e5-e5b7-4b18-ad20-13fa2ac45d0d')
        self.CLIENT_SECRET = os.environ.get(
            'WCL_CLIENT_SECRET', 'yR75c14r0JO4yiPLoNFOQs6zqDgX53vEy4ws1TEJ')
        self.token = None

    def authenticate(self):
        url = "https://www.warcraftlogs.com/oauth/token"
        resp = requests.post(
            url,
            data={'grant_type': 'client_credentials'},
            auth=HTTPBasicAuth(self.CLIENT_ID, self.CLIENT_SECRET),
            timeout=15,
        )
        if resp.status_code == 200:
            self.token = resp.json().get('access_token')
            return True
        return False

    def _ensure_token(self):
        if not self.token and not self.authenticate():
            raise Exception("無法獲取 API Token，請檢查金鑰。")

    def _post(self, query, variables):
        self._ensure_token()
        api_url = "https://tw.warcraftlogs.com/api/v2/client"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        resp = requests.post(
            api_url,
            json={'query': query, 'variables': variables},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            result = resp.json()
            if 'errors' in result:
                msg = result['errors'][0].get('message', '未知 GraphQL 錯誤')
                raise Exception(f"WCL 回報語法錯誤:\n{msg}")
            return result
        raise Exception(f"API 請求失敗: {resp.status_code}")

    def fetch_report_fights(self, report_id):
        query = """
        query($code: String!) {
            reportData {
                report(code: $code) {
                    fights { id name difficulty kill startTime endTime }
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
                    events(fightIDs: [$fightId], dataType: Casts,
                           hostilityType: Enemies, limit: 10000) { data }
                    graph(startTime: $start, endTime: $end,
                          dataType: DamageTaken, hostilityType: Friendlies)
                    playerDetails(fightIDs: [$fightId])
                }
            }
        }
        """
        return self._post(query, {
            "code": report_id,
            "fightId": int(fight_id),
            "start": float(start_time),
            "end": float(end_time),
        })

    def fetch_reference_data(self, report_id, fight_id, start_time, end_time):
        query = """
        query($code: String!, $fightId: Int!, $start: Float!, $end: Float!) {
            reportData {
                report(code: $code) {
                    masterData { abilities { gameID name } }
                    events(fightIDs: [$fightId], dataType: Casts,
                           hostilityType: Enemies, limit: 10000) { data }
                    graph(startTime: $start, endTime: $end,
                          dataType: DamageTaken, hostilityType: Friendlies)
                }
            }
        }
        """
        return self._post(query, {
            "code": report_id,
            "fightId": int(fight_id),
            "start": float(start_time),
            "end": float(end_time),
        })

    def fetch_friendly_casts(self, report_id, fight_id, start_time, end_time):
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
        return self._post(query, {
            "code": report_id,
            "fightId": int(fight_id),
            "start": float(start_time),
            "end": float(end_time),
        })


wcl = WCLClient()

# ── Tracked healing / raid cooldown spells ──────────────
TRACKED_SPELLS = {
    # Priest (Holy)
    64843:  {"name": "神聖禮頌",     "class": "Priest",      "cd": 180, "dur": 8,  "type": "大招"},
    32375:  {"name": "群體驅魔",     "class": "Priest",      "cd": 120, "dur": 1,  "type": "大招"},
    200183: {"name": "神化",         "class": "Priest",      "cd": 120, "dur": 20, "type": "爆發"},
    265202: {"name": "聖言術：救贖", "class": "Priest",      "cd": 720, "dur": 1,  "type": "大招"},
    # Priest (Discipline)
    47536:  {"name": "心靈狂喜",     "class": "Priest",      "cd": 90,  "dur": 30, "type": "爆發"},
    62618:  {"name": "真言術：壁",   "class": "Priest",      "cd": 180, "dur": 10, "type": "減傷"},
    # Paladin (Holy)
    31821:  {"name": "精通光環",     "class": "Paladin",     "cd": 180, "dur": 8,  "type": "大招"},
    31884:  {"name": "復仇之怒",     "class": "Paladin",     "cd": 120, "dur": 20, "type": "爆發"},
    # Shaman (Restoration)
    98008:  {"name": "靈魂連結圖騰", "class": "Shaman",      "cd": 180, "dur": 6,  "type": "大招"},
    108280: {"name": "療癒之潮圖騰", "class": "Shaman",      "cd": 180, "dur": 10, "type": "大招"},
    114052: {"name": "升騰",         "class": "Shaman",      "cd": 180, "dur": 15, "type": "爆發"},
    # Druid (Restoration)
    740:    {"name": "寧靜",         "class": "Druid",       "cd": 180, "dur": 6,  "type": "大招"},
    391528: {"name": "召喚眾靈",     "class": "Druid",       "cd": 120, "dur": 4,  "type": "爆發"},
    33891:  {"name": "化身：生命之樹","class": "Druid",       "cd": 180, "dur": 30, "type": "爆發"},
    106898: {"name": "奔竄咆哮",     "class": "Druid",       "cd": 120, "dur": 8,  "type": "減傷"},
    # Monk (Mistweaver)
    115310: {"name": "五氣歸元",     "class": "Monk",        "cd": 180, "dur": 6,  "type": "大招"},
    322118: {"name": "喚醒玉珑",     "class": "Monk",        "cd": 120, "dur": 25, "type": "爆發"},
    325197: {"name": "喚醒赤精",     "class": "Monk",        "cd": 120, "dur": 25, "type": "爆發"},
    # Evoker (Preservation)
    363534: {"name": "時光倒轉",     "class": "Evoker",      "cd": 240, "dur": 4,  "type": "大招"},
    359816: {"name": "夢境飛行",     "class": "Evoker",      "cd": 120, "dur": 6,  "type": "大招"},
    # Raid defensives
    51052:  {"name": "反魔法力場",   "class": "DeathKnight", "cd": 240, "dur": 6,  "type": "減傷"},
    97462:  {"name": "振奮咆哮",     "class": "Warrior",     "cd": 180, "dur": 10, "type": "減傷"},
    196718: {"name": "黑暗",         "class": "DemonHunter", "cd": 300, "dur": 8,  "type": "減傷"},
}
TRACKED_SPELL_IDS = set(TRACKED_SPELLS.keys())

# ── Helper: parse graph series ──────────────────────────
def parse_graph(raw_graph):
    if isinstance(raw_graph, str):
        try:
            raw_graph = json.loads(raw_graph)
        except Exception:
            raw_graph = {}
    gd = raw_graph if isinstance(raw_graph, dict) else {}
    series_list = gd.get('series', [])
    if not series_list and isinstance(gd.get('data'), dict):
        series_list = gd['data'].get('series', [])
    buckets = {}
    for s in series_list:
        if not isinstance(s, dict) or 'data' not in s:
            continue
        pts = s['data']
        ps = s.get('pointStart', gd.get('pointStart', 0))
        pi = s.get('pointInterval', gd.get('pointInterval', 1000))
        for idx, pt in enumerate(pts):
            if isinstance(pt, (int, float)):
                t = ps + idx * pi
                buckets[t] = buckets.get(t, 0) + pt
            elif isinstance(pt, list) and len(pt) >= 2:
                buckets[pt[0]] = buckets.get(pt[0], 0) + pt[1]
    return buckets


def build_graph_arrays(buckets):
    if not buckets:
        return [], []
    st = sorted(buckets.keys())
    t0 = st[0]
    times = [(t - t0) / 1000.0 for t in st]
    damages = [buckets[t] for t in st]
    return times, damages


def build_timeline(report_data):
    ability_map = {
        a['gameID']: a['name']
        for a in report_data.get('masterData', {}).get('abilities', [])
    }
    events = report_data.get('events', {}).get('data', [])
    casts = [e for e in events if e.get('type') == 'cast']
    if not casts:
        return [], []
    start_time = casts[0]['timestamp']
    merged = []
    for ev in casts:
        rel = ev['timestamp'] - start_time
        sid = ev.get('abilityGameID', 0)
        name = ability_map.get(sid, "未知技能")
        if merged and merged[-1][2] == sid:
            merged[-1] = (merged[-1][0], rel, merged[-1][2], merged[-1][3])
        else:
            merged.append((rel, rel, sid, name))
    timeline_rows = []
    for t_start, t_end, sid, name in merged:
        if t_start == t_end:
            ts = fmt_ms(t_start)
        else:
            ts = f"{fmt_ms(t_start)} - {fmt_ms(t_end)}"
        timeline_rows.append({
            'time': ts,
            'start_sec': t_start / 1000.0,
            'end_sec': t_end / 1000.0,
            'spell_id': sid,
            'name': name,
        })
    return merged, timeline_rows


def fmt_ms(ms):
    s = int(ms // 1000)
    return f"{s // 60:02d}:{s % 60:02d}"


# ── Flask Routes ────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/fights', methods=['POST'])
def api_fights():
    body = request.get_json(force=True)
    report_id = body.get('report_id', '').strip()
    if not report_id:
        return jsonify({'error': '請輸入 Report ID'}), 400
    try:
        data = wcl.fetch_report_fights(report_id)
        fights = (data.get('data', {}).get('reportData', {})
                      .get('report', {}).get('fights', []))
        result = []
        for f in fights:
            if not f.get('difficulty'):
                continue
            diff = "傳奇" if f['difficulty'] == 5 else (
                "英雄" if f['difficulty'] == 4 else "普通")
            kill = "擊殺" if f.get('kill') else "滅團"
            result.append({
                'id': f['id'],
                'start': f['startTime'],
                'end': f['endTime'],
                'label': f"[{diff}] {f['name']} ({kill}) (ID: {f['id']})",
            })
        return jsonify({'fights': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/roster', methods=['POST'])
def api_roster():
    body = request.get_json(force=True)
    report_id = body.get('report_id', '').strip()
    fight = body.get('fight')
    if not report_id or not fight:
        return jsonify({'error': '缺少參數'}), 400
    try:
        data = wcl.fetch_fight_data(
            report_id, fight['id'], fight['start'], fight['end'])
        rd = data.get('data', {}).get('reportData', {}).get('report', {})
        actors = rd.get('masterData', {}).get('actors', [])
        roster = [{'name': p['name'], 'class': p.get('subType', 'Unknown')}
                  for p in actors]
        pd_raw = rd.get('playerDetails', {})
        healers = _extract_healers(actors, pd_raw)

        # Also return graph + timeline for initial load
        buckets = parse_graph(rd.get('graph', {}))
        times, damages = build_graph_arrays(buckets)
        merged, timeline = build_timeline(rd)

        return jsonify({
            'roster': roster,
            'healers': healers,
            'graph': {'times': times, 'damages': damages},
            'timeline': timeline,
            'merged': [list(m) for m in merged],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/damage', methods=['POST'])
def api_damage():
    """Load graph + timeline only (own WCL)."""
    body = request.get_json(force=True)
    report_id = body.get('report_id', '').strip()
    fight = body.get('fight')
    if not report_id or not fight:
        return jsonify({'error': '缺少參數'}), 400
    try:
        data = wcl.fetch_reference_data(
            report_id, fight['id'], fight['start'], fight['end'])
        rd = data.get('data', {}).get('reportData', {}).get('report', {})
        buckets = parse_graph(rd.get('graph', {}))
        times, damages = build_graph_arrays(buckets)
        merged, timeline = build_timeline(rd)
        return jsonify({
            'graph': {'times': times, 'damages': damages},
            'timeline': timeline,
            'merged': [list(m) for m in merged],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/reference', methods=['POST'])
def api_reference():
    body = request.get_json(force=True)
    report_id = body.get('report_id', '').strip()
    fight = body.get('fight')
    if not report_id or not fight:
        return jsonify({'error': '缺少參數'}), 400
    try:
        data = wcl.fetch_reference_data(
            report_id, fight['id'], fight['start'], fight['end'])
        rd = data.get('data', {}).get('reportData', {}).get('report', {})
        buckets = parse_graph(rd.get('graph', {}))
        times, damages = build_graph_arrays(buckets)
        merged, timeline = build_timeline(rd)
        return jsonify({
            'graph': {'times': times, 'damages': damages},
            'timeline': timeline,
            'merged': [list(m) for m in merged],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/export-mrt', methods=['POST'])
def api_export_mrt():
    body = request.get_json(force=True)
    assignments = body.get('assignments', [])
    entries = []
    for a in assignments:
        if not a.get('times'):
            continue
        for t in a['times']:
            parts = t.strip().split(':')
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                sec = int(parts[0]) * 60 + int(parts[1])
                fmt = f"{sec // 60:02d}:{sec % 60:02d}"
                entries.append((sec, fmt, a.get('spell_id', 0),
                                a.get('player', ''), a.get('skill', '')))
    entries.sort(key=lambda x: x[0])
    lines = []
    for _, t, sid, name, skill in entries:
        if sid:
            lines.append(f"{{time:{t}}} {name} {skill} {{spell:{sid}}}")
        else:
            lines.append(f"{{time:{t}}} {name} {skill}")
    return jsonify({'note': '\n'.join(lines)})


@app.route('/api/import-mrt', methods=['POST'])
def api_import_mrt():
    body = request.get_json(force=True)
    text = body.get('text', '')
    pat_full = re.compile(
        r'\{time:(\d{1,2}:\d{2})\}\s+(\S+)\s+(.+?)\s+\{spell:(\d+)\}\s*$')
    pat_short = re.compile(
        r'\{time:(\d{1,2}:\d{2})\}\s+(\S+)\s+\{spell:(\d+)\}\s*$')
    imported = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = pat_full.match(line)
        if m:
            ts, player, skill, sid = m.groups()
            p = ts.split(':')
            sec = int(p[0]) * 60 + int(p[1])
            imported.append({'sec': sec, 'time': ts, 'player': player,
                             'skill': skill, 'spell_id': int(sid)})
            continue
        m = pat_short.match(line)
        if m:
            ts, player, sid = m.groups()
            p = ts.split(':')
            sec = int(p[0]) * 60 + int(p[1])
            imported.append({'sec': sec, 'time': ts, 'player': player,
                             'skill': None, 'spell_id': int(sid)})
    return jsonify({'imported': imported})


@app.route('/api/save-plan', methods=['POST'])
def api_save_plan():
    """Return JSON plan as download."""
    body = request.get_json(force=True)
    return jsonify(body)


@app.route('/api/cooldown-timeline', methods=['POST'])
def api_cooldown_timeline():
    """Return actual healing/raid CD usage from a fight."""
    body = request.get_json(force=True)
    report_id = body.get('report_id', '').strip()
    fight = body.get('fight')
    if not report_id or not fight:
        return jsonify({'error': '缺少參數'}), 400
    try:
        data = wcl.fetch_friendly_casts(
            report_id, fight['id'], fight['start'], fight['end'])
        rd = data.get('data', {}).get('reportData', {}).get('report', {})

        # Build actor lookup: id → {name, class}
        actors = rd.get('masterData', {}).get('actors', [])
        actor_map = {a['id']: {'name': a['name'], 'class': a.get('subType', 'Unknown')}
                     for a in actors}

        events = rd.get('events', {}).get('data', [])
        fight_start = float(fight['start'])
        results = []
        for ev in events:
            if ev.get('type') != 'cast':
                continue
            sid = ev.get('abilityGameID', 0)
            if sid not in TRACKED_SPELL_IDS:
                continue
            spell = TRACKED_SPELLS[sid]
            source = actor_map.get(ev.get('sourceID', 0), {})
            player_name = source.get('name', '未知')
            player_class = source.get('class', 'Unknown')
            time_sec = (ev['timestamp'] - fight_start) / 1000.0
            results.append({
                'time_sec': round(time_sec, 2),
                'player_name': player_name,
                'player_class': player_class,
                'spell_name': spell['name'],
                'spell_id': sid,
                'duration': spell['dur'],
                'type': spell['type'],
            })
        return jsonify({'cooldowns': results})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _extract_healers(actors, pd_raw):
    healers = []
    if isinstance(pd_raw, dict):
        pd = pd_raw
        if 'data' in pd and isinstance(pd['data'], dict):
            pd = pd['data']
        if 'playerDetails' in pd and isinstance(pd['playerDetails'], dict):
            pd = pd['playerDetails']
        for h in pd.get('healers', []):
            if isinstance(h, dict):
                healers.append({'name': h.get('name', ''),
                                'class': h.get('type', '')})
    if not healers:
        hc = {"Priest", "Paladin", "Shaman", "Druid", "Monk", "Evoker"}
        for a in actors:
            if a.get('subType') in hc:
                healers.append({'name': a['name'], 'class': a['subType']})
    return healers


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
