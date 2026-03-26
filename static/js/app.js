/* ============================================================
   Mythic Raid Tactical Planner — Frontend (Plotly.js)
   ============================================================ */

// ── Static data (mirrored from desktop app) ─────────────
const CLASS_TRANSLATION = {
    DeathKnight:"死亡騎士", DemonHunter:"惡魔獵人", Druid:"德魯伊",
    Evoker:"喚能師", Hunter:"獵人", Mage:"法師", Monk:"武僧",
    Paladin:"聖騎士", Priest:"牧師", Rogue:"盜賊", Shaman:"薩滿",
    Warlock:"術士", Warrior:"戰士"
};
const CLASS_COLORS = {
    DeathKnight:"#C41E3A", DemonHunter:"#A330C9", Druid:"#FF7C0A",
    Evoker:"#33937F", Hunter:"#AAD372", Mage:"#3FC7EB",
    Monk:"#00FF98", Paladin:"#F48CBA", Priest:"#FFFFFF",
    Rogue:"#FFF468", Shaman:"#0070DD", Warlock:"#8788EE",
    Warrior:"#C69B6D"
};
const HEALER_COOLDOWNS = {
    Priest:  [{name:"神聖禮頌",spell_id:64843,cd:180,dur:8},{name:"群體驅魔",spell_id:32375,cd:120,dur:1}],
    Paladin: [{name:"精通光環",spell_id:31821,cd:180,dur:8}],
    Shaman:  [{name:"靈魂連結圖騰",spell_id:98008,cd:180,dur:6},{name:"療癒之潮圖騰",spell_id:108280,cd:180,dur:10}],
    Druid:   [{name:"寧靜",spell_id:740,cd:180,dur:6}],
    Monk:    [{name:"五氣歸元",spell_id:115310,cd:180,dur:6}],
    Evoker:  [{name:"時光倒轉",spell_id:363534,cd:240,dur:4}],
};
const DRUID_UTILITY = {name:"奔竄咆哮",spell_id:106898,cd:120,dur:8};
const EXTRA_RAID_CDS = {
    DeathKnight:[{name:"反魔法力場",spell_id:51052,cd:240,dur:6}],
    Warrior:[{name:"振奮咆哮",spell_id:97462,cd:180,dur:10}],
};

// Build cd lookup
const CD_LOOKUP = {};
for (const cds of Object.values(HEALER_COOLDOWNS))
    for (const s of cds) CD_LOOKUP[s.spell_id] = {cd:s.cd, dur:s.dur};
CD_LOOKUP[DRUID_UTILITY.spell_id] = {cd:DRUID_UTILITY.cd, dur:DRUID_UTILITY.dur};
for (const cds of Object.values(EXTRA_RAID_CDS))
    for (const s of cds) CD_LOOKUP[s.spell_id] = {cd:s.cd, dur:s.dur};

const BOSS_ABILITY_TAGS = {
    1249262:"分攤",1261249:"躲避",1258883:"躲避",1260712:"躲避",1284786:"躲避",
    1249251:"團傷",1265540:"坦克DOT",1251361:"佔領",1280035:"驅散",1265490:"站位",
    1260052:"拉人擊退",1241692:"坦克分攤",1259186:"小怪",1256855:"光束",1244419:"滅團",
    1244672:"遠離",1262623:"光束",1244221:"恐懼",1245391:"分攤球",1244917:"分散+小怪",
    1270189:"分坦",1265131:"坦克",1245645:"坦克",1264467:"躲避",1255763:"團傷DOT",
    1249748:"過場團傷",1248847:"過場",1263623:"史詩機制",1251686:"小怪",
    1247738:"寶珠",1254081:"打斷",1275056:"史詩機制",1248697:"地面區域",
    1246175:"團傷+躲避",1250803:"躲避",1250686:"團傷DOT",1271577:"坦克DOT",
    1276243:"史詩強化",1246384:"驅散",1248449:"強化",1246155:"地面區域",
    1248983:"分攤",1246765:"範圍傷害",1246485:"分散",1255738:"團傷DOT",
    1248644:"躲避",1248674:"躲避",1251857:"坦克",1258514:"打斷",
    1246749:"團傷",1258659:"團傷DOT",1246745:"坦克",
    1233602:"瞄準",1232467:"瞄準",1232470:"瞄準",1255368:"躲避",
    1243743:"沉默",1243753:"躲避",1261531:"小怪",1233865:"治療吸收",
    1233787:"坦克",1234569:"過場",1243982:"躲避",1237729:"瞄準",
    1246918:"護盾",1237038:"DOT",1246461:"坦克",1238206:"地面",
    1239080:"連線",1238843:"換平台",
    1267201:"遠離",1262289:"分攤",1258610:"召喚小怪",1245727:"吸收護盾",
    1264756:"遠離",1257087:"驅散",1272726:"坦克",1245396:"團傷",
    1246621:"團傷DOT",1250953:"治療吸收",1249207:"團傷",1262020:"坦克",
    1249017:"打斷",1261997:"打斷",1245486:"躲避+小怪",1245406:"團傷",
};

const DAMAGE_TAGS = new Set([
    "分攤","團傷","團傷DOT","範圍傷害","分散","分散+小怪",
    "滅團","過場團傷","團傷+躲避","治療吸收","DOT",
    "分攤球","拉人擊退","分坦","瞄準","驅散",
]);

// ── State ───────────────────────────────────────────────
let ownFights = [];
let refFights = [];
let graphTimes = [];
let graphDamages = [];
let mergedTimeline = [];   // [[start_ms, end_ms, spell_id, name], ...]
let currentActors = [];
let currentTimeline = [];  // [{time, start_sec, end_sec, spell_id, name}]
let healerRows = [];       // [{player, playerClass, skill, spell_id, times:''}]
let markedRows = new Set();

// ── API helpers ─────────────────────────────────────────
async function apiPost(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
}

function fmtSec(s) {
    s = Math.max(0, Math.floor(s));
    return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
}

function parseMultiTimes(text) {
    const result = [];
    for (const seg of text.split(',')) {
        const p = seg.trim().split(':');
        if (p.length === 2 && /^\d+$/.test(p[0]) && /^\d+$/.test(p[1]))
            result.push(parseInt(p[0])*60 + parseInt(p[1]));
    }
    return result;
}

// ── Load fights ─────────────────────────────────────────
async function loadFights(which) {
    const inputId = which === 'own' ? 'ownReportId' : 'refReportId';
    const comboId = which === 'own' ? 'comboOwnFight' : 'comboRefFight';
    const btnId   = which === 'own' ? 'btnOwnFights'  : 'btnRefFights';
    const reportId = document.getElementById(inputId).value.trim();
    if (!reportId) return;

    const btn = document.getElementById(btnId);
    btn.disabled = true; btn.textContent = '讀取中...';
    try {
        const data = await apiPost('/api/fights', {report_id: reportId});
        const combo = document.getElementById(comboId);
        combo.innerHTML = '';
        const fights = data.fights;
        if (which === 'own') ownFights = fights; else refFights = fights;
        for (const f of fights) {
            const opt = document.createElement('option');
            opt.value = f.id;
            opt.textContent = f.label;
            opt.dataset.start = f.start;
            opt.dataset.end = f.end;
            combo.appendChild(opt);
        }
        if (which === 'own') {
            document.getElementById('btnLoadRoster').disabled = fights.length === 0;
            document.getElementById('btnLoadOwnDamage').disabled = fights.length === 0;
        } else {
            document.getElementById('btnLoadRef').disabled = fights.length === 0;
        }
    } catch(e) { alert('錯誤: ' + e.message); }
    finally {
        btn.disabled = false;
        btn.textContent = '取得首領列表';
    }
}

function getSelectedFight(which) {
    const comboId = which === 'own' ? 'comboOwnFight' : 'comboRefFight';
    const combo = document.getElementById(comboId);
    const opt = combo.selectedOptions[0];
    if (!opt) return null;
    return {id: parseInt(opt.value), start: parseFloat(opt.dataset.start), end: parseFloat(opt.dataset.end)};
}

// ── Load roster ─────────────────────────────────────────
async function loadRoster() {
    const reportId = document.getElementById('ownReportId').value.trim();
    const fight = getSelectedFight('own');
    if (!reportId || !fight) return;

    const btn = document.getElementById('btnLoadRoster');
    btn.disabled = true; btn.textContent = '載入中...';
    try {
        const data = await apiPost('/api/roster', {report_id: reportId, fight});
        currentActors = data.roster;
        renderRoster(data.roster);
        buildHealerCdTable(data.roster, data.healers);
        if (graphTimes.length === 0 && data.graph) {
            graphTimes = data.graph.times;
            graphDamages = data.graph.damages;
            mergedTimeline = data.merged || [];
            currentTimeline = data.timeline || [];
            renderTimeline();
            renderChart();
        }
    } catch(e) { alert('載入失敗: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = '載入陣容'; }
}

// ── Load own damage ─────────────────────────────────────
async function loadOwnDamage() {
    const reportId = document.getElementById('ownReportId').value.trim();
    const fight = getSelectedFight('own');
    if (!reportId || !fight) return;

    const btn = document.getElementById('btnLoadOwnDamage');
    btn.disabled = true; btn.textContent = '載入中...';
    try {
        const data = await apiPost('/api/damage', {report_id: reportId, fight});
        graphTimes = data.graph.times;
        graphDamages = data.graph.damages;
        mergedTimeline = data.merged || [];
        currentTimeline = data.timeline || [];
        markedRows.clear();
        renderTimeline();
        renderChart();
    } catch(e) { alert('載入失敗: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = '載入承傷數據'; }
}

// ── Load reference ──────────────────────────────────────
async function loadReference() {
    const reportId = document.getElementById('refReportId').value.trim();
    const fight = getSelectedFight('ref');
    if (!reportId || !fight) return;

    const btn = document.getElementById('btnLoadRef');
    btn.disabled = true; btn.textContent = '載入中...';
    try {
        const data = await apiPost('/api/reference', {report_id: reportId, fight});
        graphTimes = data.graph.times;
        graphDamages = data.graph.damages;
        mergedTimeline = data.merged || [];
        currentTimeline = data.timeline || [];
        markedRows.clear();
        renderTimeline();
        renderChart();
    } catch(e) { alert('載入失敗: ' + e.message); }
    finally { btn.disabled = false; btn.textContent = '導入承傷數據'; }
}

// ── Render roster ───────────────────────────────────────
function renderRoster(roster) {
    const ul = document.getElementById('rosterList');
    ul.innerHTML = '';
    for (const p of roster) {
        const li = document.createElement('li');
        const cls = CLASS_TRANSLATION[p.class] || p.class;
        li.textContent = `[${cls}] ${p.name}`;
        li.style.color = CLASS_COLORS[p.class] || '#fff';
        ul.appendChild(li);
    }
}

// ── Build healer CD table ───────────────────────────────
function buildHealerCdTable(actors, healers) {
    healerRows = [];
    const healerNames = new Set();
    for (const h of healers) {
        healerNames.add(h.name);
        const cds = HEALER_COOLDOWNS[h.class] || [];
        for (const cd of cds) {
            healerRows.push({player: h.name, playerClass: h.class,
                             skill: cd.name, spell_id: cd.spell_id, times: ''});
        }
        if (h.class === 'Druid') {
            healerRows.push({player: h.name, playerClass: 'Druid',
                             skill: DRUID_UTILITY.name, spell_id: DRUID_UTILITY.spell_id, times: ''});
        }
    }
    const allDruids = actors.filter(a => a.class === 'Druid').map(a => a.name);
    for (const name of allDruids.sort()) {
        if (!healerNames.has(name)) {
            healerRows.push({player: name, playerClass: 'Druid',
                             skill: DRUID_UTILITY.name, spell_id: DRUID_UTILITY.spell_id, times: ''});
        }
    }
    const dks = actors.filter(a => a.class === 'DeathKnight').map(a => a.name).sort();
    for (const name of dks) {
        for (const cd of (EXTRA_RAID_CDS.DeathKnight || []))
            healerRows.push({player: name, playerClass: 'DeathKnight',
                             skill: cd.name, spell_id: cd.spell_id, times: ''});
    }
    const wars = actors.filter(a => a.class === 'Warrior').map(a => a.name).sort();
    for (const name of wars) {
        for (const cd of (EXTRA_RAID_CDS.Warrior || []))
            healerRows.push({player: name, playerClass: 'Warrior',
                             skill: cd.name, spell_id: cd.spell_id, times: ''});
    }
    healerRows.push({player: '', playerClass: '', skill: '個減', spell_id: 0, times: ''});
    renderHealerTable();
}

function renderHealerTable() {
    const tbody = document.getElementById('healerCdBody');
    tbody.innerHTML = '';
    for (let i = 0; i < healerRows.length; i++) {
        const r = healerRows[i];
        const tr = document.createElement('tr');
        const td0 = document.createElement('td');
        td0.textContent = r.player;
        td0.style.color = CLASS_COLORS[r.playerClass] || '#fff';
        tr.appendChild(td0);
        const td1 = document.createElement('td');
        td1.textContent = r.skill;
        tr.appendChild(td1);
        const td2 = document.createElement('td');
        const inp = document.createElement('input');
        inp.type = 'text';
        inp.value = r.times;
        inp.placeholder = 'MM:SS, MM:SS';
        inp.title = '格式 MM:SS，多次使用逗號分隔 (例如 01:30, 04:00)';
        inp.dataset.row = i;
        inp.addEventListener('change', onCdTimeChanged);
        td2.appendChild(inp);
        tr.appendChild(td2);
        tbody.appendChild(tr);
    }
}

function onCdTimeChanged(e) {
    const idx = parseInt(e.target.dataset.row);
    healerRows[idx].times = e.target.value;
    renderChart();
}

// ── Render timeline ─────────────────────────────────────
function renderTimeline() {
    const tbody = document.getElementById('timelineBody');
    tbody.innerHTML = '';
    for (let i = 0; i < currentTimeline.length; i++) {
        const t = currentTimeline[i];
        const tag = BOSS_ABILITY_TAGS[t.spell_id] || '';
        const tagSuffix = tag ? ` [${tag}]` : '';
        const tr = document.createElement('tr');
        tr.dataset.row = i;
        tr.addEventListener('click', () => toggleTimelineMark(i));
        const td0 = document.createElement('td');
        td0.textContent = t.time;
        tr.appendChild(td0);
        const td1 = document.createElement('td');
        td1.textContent = `${t.name} (${t.spell_id})${tagSuffix}`;
        tr.appendChild(td1);
        if (markedRows.has(i)) tr.classList.add('marked');
        tbody.appendChild(tr);
    }
}

function toggleTimelineMark(row) {
    if (markedRows.has(row)) markedRows.delete(row);
    else markedRows.add(row);
    // update row style
    const tr = document.querySelector(`#timelineBody tr[data-row="${row}"]`);
    if (tr) tr.classList.toggle('marked');
    renderChart();
}

function clearMarkers() {
    const hasAssignment = healerRows.some(r => r.times.trim() !== '');
    if (hasAssignment) {
        if (!confirm('目前有已分配的減傷/治療時間，清除標記將同時清除所有分配時間。\n確定要清除嗎？'))
            return;
        for (const r of healerRows) r.times = '';
        renderHealerTable();
    }
    markedRows.clear();
    renderTimeline();
    renderChart();
}

// ── Render chart (Plotly) ───────────────────────────────
function renderChart() {
    const div = document.getElementById('damageChart');
    const traces = [];
    const shapes = [];
    const annotations = [];

    // Main damage trace
    if (graphTimes.length) {
        traces.push({
            x: graphTimes, y: graphDamages,
            type: 'scatter', mode: 'lines',
            fill: 'tozeroy',
            fillcolor: 'rgba(255,0,0,0.15)',
            line: {color: 'red', width: 2},
            hovertemplate: '時間: %{text}<br>傷害: %{y:,.0f}<extra></extra>',
            text: graphTimes.map(t => fmtSec(t)),
        });
    }

    const yMax = graphDamages.length ? Math.max(...graphDamages) : 0;

    // Boss ability labels on chart
    if (mergedTimeline.length && graphTimes.length) {
        for (const m of mergedTimeline) {
            const sid = m[2];
            const tag = BOSS_ABILITY_TAGS[sid] || '';
            if (!DAMAGE_TAGS.has(tag)) continue;
            const xSec = m[0] / 1000.0;
            const yVal = damageAt(xSec);
            shapes.push({
                type: 'line', x0: xSec, x1: xSec, y0: 0, y1: yMax,
                line: {color: '#AAAAAA', width: 1, dash: 'dot'},
            });
            annotations.push({
                x: xSec, y: yVal, text: `${m[3]} [${tag}]`,
                showarrow: false, font: {color: '#FFA500', size: 11},
                yshift: 12,
            });
        }
    }

    // Timeline markers
    for (const row of markedRows) {
        const t = currentTimeline[row];
        if (!t) continue;
        shapes.push({
            type: 'line', x0: t.start_sec, x1: t.start_sec, y0: 0, y1: yMax,
            line: {color: '#00FFFF', width: 2, dash: 'dashdot'},
        });
        if (t.end_sec !== t.start_sec) {
            shapes.push({
                type: 'line', x0: t.end_sec, x1: t.end_sec, y0: 0, y1: yMax,
                line: {color: '#00FFFF', width: 1, dash: 'dot'},
            });
        }
        annotations.push({
            x: t.start_sec, y: yMax * 0.95,
            text: t.name.split(' (')[0],
            showarrow: false, font: {color: '#00FFFF', size: 11},
        });
    }

    // Healer CD bars on chart
    let lane = 0;
    for (let i = 0; i < healerRows.length; i++) {
        const r = healerRows[i];
        if (!r.times.trim()) continue;
        const color = CLASS_COLORS[r.playerClass] || '#FFFFFF';
        const info = CD_LOOKUP[r.spell_id];
        const dur = info ? info.dur : 0;
        for (const sec of parseMultiTimes(r.times)) {
            const endSec = sec + dur;
            const yVal = damageAt(sec);
            const yDraw = yVal - yMax * 0.03 * lane;
            if (dur > 0) {
                traces.push({
                    x: [sec, endSec], y: [yDraw, yDraw],
                    type: 'scatter', mode: 'lines',
                    line: {color, width: 4},
                    showlegend: false,
                    hoverinfo: 'skip',
                });
            } else {
                traces.push({
                    x: [sec, sec], y: [yDraw - yMax*0.02, yDraw + yMax*0.02],
                    type: 'scatter', mode: 'lines',
                    line: {color, width: 3},
                    showlegend: false,
                    hoverinfo: 'skip',
                });
            }
            annotations.push({
                x: sec, y: yDraw,
                text: `${r.player} ${r.skill}`,
                showarrow: false,
                font: {color, size: 9},
                xanchor: 'left', yshift: -10,
            });
            lane++;
        }
    }

    const layout = {
        paper_bgcolor: '#1e1e1e',
        plot_bgcolor: '#1e1e1e',
        title: {text: '團隊總承傷 (Total Damage Taken)', font: {color: '#ddd', size: 14}},
        xaxis: {
            title: '時間',
            color: '#aaa', gridcolor: '#333',
            tickvals: graphTimes.length ? generateTimeTicks(graphTimes) : [],
            ticktext: graphTimes.length ? generateTimeTicks(graphTimes).map(t => fmtSec(t)) : [],
        },
        yaxis: {title: '傷害量', color: '#aaa', gridcolor: '#333'},
        shapes, annotations,
        showlegend: false,
        margin: {l: 70, r: 20, t: 40, b: 40},
        hovermode: 'x unified',
    };

    Plotly.react(div, traces, layout, {
        responsive: true,
        displayModeBar: false,
    });

    // Click handler for skill assignment
    div.removeAllListeners && div.removeAllListeners('plotly_click');
    div.on('plotly_click', onChartClick);
}

function generateTimeTicks(times) {
    if (!times.length) return [];
    const max = times[times.length - 1];
    const ticks = [];
    const step = max > 600 ? 60 : (max > 120 ? 30 : 15);
    for (let t = 0; t <= max + step; t += step) ticks.push(t);
    return ticks;
}

function damageAt(sec) {
    if (!graphTimes.length) return 0;
    let lo = 0, hi = graphTimes.length - 1;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (graphTimes[mid] < sec) lo = mid + 1; else hi = mid;
    }
    if (lo === 0) return graphDamages[0];
    if (Math.abs(graphTimes[lo] - sec) < Math.abs(graphTimes[lo-1] - sec))
        return graphDamages[lo];
    return graphDamages[lo-1];
}

// ── Chart click → skill assignment popup ────────────────
function onChartClick(data) {
    if (!data.points || !data.points.length) return;
    const clickSec = data.points[0].x;
    if (clickSec < 0) return;
    const timeStr = fmtSec(clickSec);
    showSkillPopup(data.event, clickSec, timeStr);
}

function showSkillPopup(event, clickSec, timeStr) {
    const popup = document.getElementById('skillPopup');
    const list = document.getElementById('skillPopupList');
    list.innerHTML = '';
    let hasItems = false;

    for (let i = 0; i < healerRows.length; i++) {
        const r = healerRows[i];
        if (!r.player && !r.skill) continue;
        const onCd = isOnCooldown(i, clickSec);
        const div = document.createElement('div');
        div.className = 'skill-popup-item' + (onCd ? ' disabled' : '');
        div.textContent = `${r.player} — ${r.skill}`;
        div.style.color = onCd ? '#555' : (CLASS_COLORS[r.playerClass] || '#fff');
        if (!onCd) {
            div.addEventListener('click', () => {
                assignSkill(i, timeStr);
                popup.style.display = 'none';
            });
            hasItems = true;
        }
        list.appendChild(div);
    }
    if (!hasItems) {
        const div = document.createElement('div');
        div.className = 'skill-popup-item disabled';
        div.textContent = '(此時間點無可用技能)';
        list.appendChild(div);
    }

    popup.style.left = event.clientX + 'px';
    popup.style.top = event.clientY + 'px';
    popup.style.display = 'block';
}

function assignSkill(rowIdx, timeStr) {
    const r = healerRows[rowIdx];
    r.times = r.times.trim() ? `${r.times}, ${timeStr}` : timeStr;
    // Update input
    const inp = document.querySelector(`#healerCdBody input[data-row="${rowIdx}"]`);
    if (inp) inp.value = r.times;
    renderChart();
}

function isOnCooldown(rowIdx, clickSec) {
    const r = healerRows[rowIdx];
    if (!r.times.trim()) return false;
    const info = CD_LOOKUP[r.spell_id];
    if (!info) return false;
    for (const sec of parseMultiTimes(r.times)) {
        if (sec <= clickSec && clickSec < sec + info.cd) return true;
    }
    return false;
}

// Close popup on outside click
document.addEventListener('click', (e) => {
    const popup = document.getElementById('skillPopup');
    if (popup.style.display === 'block' && !popup.contains(e.target)) {
        popup.style.display = 'none';
    }
});

// ── MRT Export/Import ───────────────────────────────────
async function exportMRT() {
    const assignments = healerRows.map(r => ({
        player: r.player, skill: r.skill, spell_id: r.spell_id,
        times: r.times.trim() ? r.times.split(',').map(s => s.trim()) : [],
    })).filter(a => a.times.length > 0);
    if (!assignments.length) {
        alert('沒有已分配時間的減傷技能可匯出。');
        return;
    }
    try {
        const data = await apiPost('/api/export-mrt', {assignments});
        document.getElementById('mrtExportTextarea').value = data.note;
        document.getElementById('mrtExportDialog').style.display = 'flex';
    } catch(e) { alert('匯出失敗: ' + e.message); }
}

function copyMRTExport() {
    const ta = document.getElementById('mrtExportTextarea');
    ta.select();
    navigator.clipboard.writeText(ta.value).then(() => {
        alert('已複製到剪貼簿！');
    });
}

function importMRT() {
    document.getElementById('mrtTextarea').value = '';
    document.getElementById('mrtDialog').style.display = 'flex';
}
function closeMRTDialog() {
    document.getElementById('mrtDialog').style.display = 'none';
}
async function doImportMRT() {
    const text = document.getElementById('mrtTextarea').value;
    if (!text.trim()) return;
    try {
        const data = await apiPost('/api/import-mrt', {text});
        closeMRTDialog();
        let matched = 0;
        for (const imp of data.imported) {
            for (let i = 0; i < healerRows.length; i++) {
                const r = healerRows[i];
                if (r.player === imp.player &&
                    (r.spell_id === imp.spell_id || (imp.skill && r.skill === imp.skill))) {
                    const fmt = fmtSec(imp.sec);
                    r.times = r.times.trim() ? `${r.times}, ${fmt}` : fmt;
                    matched++;
                    break;
                }
            }
        }
        renderHealerTable();
        renderChart();
        alert(`共解析 ${data.imported.length} 筆，成功匹配 ${matched} 筆到減傷表。`);
    } catch(e) { alert('匯入失敗: ' + e.message); }
}

// ── Save / Load plan ────────────────────────────────────
function savePlan() {
    const plan = {
        version: 1,
        own_report_id: document.getElementById('ownReportId').value.trim(),
        ref_report_id: document.getElementById('refReportId').value.trim(),
        roster: currentActors,
        healer_cds: healerRows.map(r => ({
            player: r.player, class: r.playerClass,
            skill: r.skill, spell_id: r.spell_id, time: r.times,
        })),
        timeline: currentTimeline,
        graph_times: graphTimes,
        graph_damages: graphDamages,
        merged_timeline: mergedTimeline,
    };
    const blob = new Blob([JSON.stringify(plan, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'raid_plan.json';
    a.click();
    URL.revokeObjectURL(a.href);
}

function loadPlan(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const plan = JSON.parse(e.target.result);
            document.getElementById('ownReportId').value = plan.own_report_id || '';
            document.getElementById('refReportId').value = plan.ref_report_id || '';
            currentActors = plan.roster || [];
            renderRoster(currentActors);

            healerRows = (plan.healer_cds || []).map(c => ({
                player: c.player || '', playerClass: c.class || '',
                skill: c.skill || '', spell_id: c.spell_id || 0,
                times: c.time || '',
            }));
            renderHealerTable();

            currentTimeline = plan.timeline || [];
            graphTimes = plan.graph_times || [];
            graphDamages = plan.graph_damages || [];
            mergedTimeline = plan.merged_timeline || [];
            markedRows.clear();
            renderTimeline();
            renderChart();
            alert('方案載入成功！');
        } catch(err) { alert('載入失敗: ' + err.message); }
    };
    reader.readAsText(file);
    event.target.value = '';
}

// ── Resizer logic ───────────────────────────────────────
(function initResizers() {
    // Vertical resizer (left ↔ right)
    const resizer = document.getElementById('resizer');
    const left = document.getElementById('leftPanel');
    let startX, startW;
    resizer.addEventListener('mousedown', (e) => {
        startX = e.clientX;
        startW = left.offsetWidth;
        document.addEventListener('mousemove', onMouseMoveV);
        document.addEventListener('mouseup', onMouseUpV);
        e.preventDefault();
    });
    function onMouseMoveV(e) {
        left.style.width = (startW + e.clientX - startX) + 'px';
        left.style.flexShrink = 0;
    }
    function onMouseUpV() {
        document.removeEventListener('mousemove', onMouseMoveV);
        document.removeEventListener('mouseup', onMouseUpV);
        Plotly.Plots.resize(document.getElementById('damageChart'));
    }

    // Horizontal resizer (chart ↔ timeline)
    const resizerH = document.getElementById('resizerH');
    const chartC = document.getElementById('chartContainer');
    let startY, startH;
    resizerH.addEventListener('mousedown', (e) => {
        startY = e.clientY;
        startH = chartC.offsetHeight;
        document.addEventListener('mousemove', onMouseMoveH);
        document.addEventListener('mouseup', onMouseUpH);
        e.preventDefault();
    });
    function onMouseMoveH(e) {
        chartC.style.flexGrow = 0;
        chartC.style.height = (startH + e.clientY - startY) + 'px';
    }
    function onMouseUpH() {
        document.removeEventListener('mousemove', onMouseMoveH);
        document.removeEventListener('mouseup', onMouseUpH);
        Plotly.Plots.resize(document.getElementById('damageChart'));
    }
})();

// ── Responsive chart resize ─────────────────────────────
window.addEventListener('resize', () => {
    const div = document.getElementById('damageChart');
    if (div && div.data) Plotly.Plots.resize(div);
});

// ── Init empty chart ────────────────────────────────────
renderChart();
