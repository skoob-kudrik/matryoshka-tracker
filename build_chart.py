#!/usr/bin/env python3
"""
Генератор автономного HTML-графика сравнения доходности.

Читает SQLite (см. collect.py), считает две серии — стоимость пая фонда и
индекс MCFTR — и рендерит самодостаточный chart.html:
  * переключение интервалов (1М / 3М / 6М / 1Г / YTD / Всё);
  * доходность в % с ребейзом к началу выбранного интервала (обе линии
    стартуют от 0 %, честное сравнение динамики);
  * crosshair + единый тултип на обе серии;
  * светлая/тёмная тема (авто + переключатель);
  * табличное представление для доступности.

Данные встраиваются в файл при генерации — интернет для просмотра не нужен.
"""
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "matryoshka.db"
OUT_PATH = HERE / "chart.html"
LOGO_PATH = HERE / "logo.png"
INDEX_SECID = "MCFTR"

FUND_LABEL = "Фонд «Матрёшка а-ля Рус» (пай)"
INDEX_LABEL = "Индекс МосБиржи полной доходности (MCFTR)"


def load_series(db: str):
    conn = sqlite3.connect(db)
    fund = [
        {"date": d, "v": c, "nav": nav}
        for d, c, nav in conn.execute(
            "SELECT date, share_cost, nav FROM fund ORDER BY date"
        ).fetchall()
    ]
    fund_dates = {p["date"] for p in fund}
    # Индекс выравниваем по дням фонда: у MCFTR есть значения в отдельные
    # праздничные дни, когда УК не считает СЧА. Для сравнения оставляем только
    # общие даты, чтобы обе серии совпадали по количеству точек.
    idx = [
        {"date": d, "v": c}
        for d, c in conn.execute(
            "SELECT date, close FROM index_value WHERE secid=? ORDER BY date",
            (INDEX_SECID,),
        ).fetchall()
        if d in fund_dates
    ]
    conn.close()
    return fund, idx


def logo_css_value(path: Path) -> str:
    """Логотип (logo.png) как data-URI для CSS-переменной, либо 'none'."""
    if not path.exists():
        return "none"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f'url("data:image/png;base64,{b64}")'


def build_html(fund, idx) -> str:
    payload = json.dumps(
        {
            "fund": {"label": FUND_LABEL, "points": fund},
            "index": {"label": INDEX_LABEL, "points": idx},
            "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        HTML_TEMPLATE
        .replace("/*__DATA__*/", payload)
        .replace("__LOGO_URL__", logo_css_value(LOGO_PATH))
    )


# --------------------------------------------------------------------------- #
# HTML-шаблон. Плейсхолдер /*__DATA__*/ заменяется на JSON с данными.
# Палитра — из data-viz reference (slot1 blue = фонд, slot2 orange = индекс).
# --------------------------------------------------------------------------- #
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Доходность: Матрёшка а-ля Рус vs MCFTR</title>
<style>
  .viz-root{
    color-scheme:light;
    --surface-1:#fcfcfb; --page:#f9f9f7;
    --text-primary:#0b0b0b; --text-secondary:#52514e; --muted:#898781;
    --grid:#e1e0d9; --baseline:#c3c2b7; --border:rgba(11,11,11,.10);
    --series-fund:#2a78d6; --series-index:#eb6834; --series-diff:#0f9140;
    --good:#006300;
  }
  @media (prefers-color-scheme:dark){
    :root:where(:not([data-theme="light"])) .viz-root{
      color-scheme:dark;
      --surface-1:#1a1a19; --page:#0d0d0d;
      --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
      --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,.10);
      --series-fund:#3987e5; --series-index:#d95926; --series-diff:#33c06d;
      --good:#0ca30c;
    }
  }
  :root[data-theme="dark"] .viz-root{
    color-scheme:dark;
    --surface-1:#1a1a19; --page:#0d0d0d;
    --text-primary:#fff; --text-secondary:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,.10);
    --series-fund:#3987e5; --series-index:#d95926; --series-diff:#33c06d;
    --good:#0ca30c;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--page)}
  .viz-root{
    font-family:ui-rounded,"SF Pro Rounded","Nunito","Segoe UI Rounded",system-ui,-apple-system,"Segoe UI",sans-serif;
    --logo:__LOGO_URL__;
    background:var(--page); color:var(--text-primary);
    min-height:100vh; padding:24px;
  }
  .head{display:flex; align-items:center; gap:14px; margin-bottom:18px}
  .logo{
    width:71px; height:71px; flex:none;
    background:var(--logo) center/contain no-repeat;
  }
  h1{font-size:20px; font-weight:700; margin:0 0 2px}
  .sub{color:var(--text-secondary); font-size:13px; margin:0}
  /* контейнер-клиппер: обрезает подложку по высоте области графика */
  .wm-clip{position:absolute; inset:0; overflow:hidden; z-index:0; pointer-events:none}
  /* подложка во всю ширину, квадратная (по ширине) — выровнена по верху клипа,
     видна верхняя часть логотипа; низ (с надписью) уходит за пределы клипа */
  .watermark{
    position:absolute; left:0; top:0; transform:translateY(-10%);
    width:100%; aspect-ratio:1/1;
    background:var(--logo) center/contain no-repeat;
    opacity:.05;
  }
  @media (prefers-color-scheme:dark){
    :root:where(:not([data-theme="light"])) .viz-root .watermark{opacity:.07}
  }
  :root[data-theme="dark"] .viz-root .watermark{opacity:.07}
  .card{
    background:var(--surface-1); border:1px solid var(--border);
    border-radius:12px; padding:18px 18px 8px;
  }
  .toolbar{
    display:flex; flex-wrap:wrap; gap:8px; align-items:center;
    margin-bottom:14px;
  }
  .ranges{display:flex; gap:4px; flex-wrap:wrap}
  .ranges button, .theme-btn, .tbl-btn{
    font:inherit; font-size:13px; cursor:pointer;
    background:transparent; color:var(--text-secondary);
    border:1px solid var(--border); border-radius:8px;
    padding:5px 11px; line-height:1;
  }
  .ranges button[aria-pressed="true"]{
    background:var(--text-primary); color:var(--surface-1);
    border-color:var(--text-primary); font-weight:600;
  }
  .modes button[aria-pressed="true"]{
    background:var(--series-fund); color:#fff; border-color:var(--series-fund);
  }
  .sep{width:1px; height:22px; background:var(--border); margin:0 2px}
  .chk{display:inline-flex; align-items:center; gap:6px; font-size:13px;
    color:var(--text-secondary); cursor:pointer; user-select:none}
  .chk input{accent-color:var(--series-diff); cursor:pointer; margin:0}
  .legend .key.dashed{
    background:repeating-linear-gradient(90deg,var(--series-diff) 0 5px,transparent 5px 9px);
  }
  .spacer{flex:1}
  .legend{display:flex; gap:16px; margin:2px 0 12px; flex-wrap:wrap}
  .legend .item{display:flex; align-items:center; gap:7px; font-size:13px; color:var(--text-secondary)}
  .legend .key{width:18px; height:2px; border-radius:2px}
  figure{margin:0}
  svg{display:block; width:100%; height:auto; overflow:visible}
  .grid line{stroke:var(--grid); stroke-width:1}
  .axis text{fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums}
  .zero{stroke:var(--baseline); stroke-width:1.5}
  .yttl{font-size:12px}
  .endlbl{font-size:15px; font-weight:700}
  .line{fill:none; stroke-width:2; stroke-linejoin:round; stroke-linecap:round}
  .cross{stroke:var(--baseline); stroke-width:1; stroke-dasharray:3 3}
  .tip{
    position:absolute; pointer-events:none; z-index:5;
    background:var(--surface-1); border:1px solid var(--border);
    border-radius:9px; padding:9px 11px; font-size:12px;
    box-shadow:0 4px 16px rgba(0,0,0,.12); min-width:150px;
    transform:translate(-50%,calc(-100% - 14px)); opacity:0; transition:opacity .08s;
  }
  .tip .d{color:var(--muted); font-size:11px; margin-bottom:6px}
  .tip .row{display:flex; align-items:center; gap:7px; margin:3px 0}
  .tip .k{width:14px; height:2px; border-radius:2px; flex:none}
  .tip .nm{color:var(--text-secondary); flex:1; white-space:nowrap}
  .tip .v{font-weight:650; font-variant-numeric:tabular-nums}
  .stats{display:flex; gap:26px; flex-wrap:wrap; margin:14px 2px 4px}
  .stat .lab{font-size:12px; color:var(--text-secondary); display:flex; align-items:center; gap:6px}
  .stat .num{font-size:22px; font-weight:650; font-variant-numeric:tabular-nums; margin-top:2px}
  .pos{color:var(--good)} .neg{color:#d03b3b}
  table{border-collapse:collapse; width:100%; font-size:13px; font-variant-numeric:tabular-nums}
  th,td{text-align:right; padding:5px 10px; border-bottom:1px solid var(--grid)}
  th:first-child,td:first-child{text-align:left}
  .datawrap{display:none; margin-top:8px; max-height:340px; overflow:auto}
  .datawrap.open{display:block}
  .note{color:var(--muted); font-size:12px; margin:16px 2px 0}
</style>
</head>
<body>
<div class="viz-root" id="root">
  <div class="head">
    <div class="logo" role="img" aria-label="Логотип фонда «Матрёшка а-ля Рус»"></div>
    <div>
      <h1>Доходность фонда «Матрёшка а-ля Рус» vs бенчмарк</h1>
      <p class="sub">Стоимость пая ОПИФ «Матрёшка а-ля Рус» против Индекса МосБиржи полной доходности (MCFTR). Обе линии приведены к 0 % на старте выбранного интервала.</p>
    </div>
  </div>

  <div class="card">
    <div class="toolbar">
      <div class="ranges modes" id="modes" role="group" aria-label="Режим"></div>
      <span class="sep"></span>
      <div class="ranges" id="ranges" role="group" aria-label="Интервал"></div>
      <label class="chk" id="diffChk"><input type="checkbox" id="diffToggle" checked>Разница</label>
      <div class="spacer"></div>
      <button class="tbl-btn" id="tblBtn" aria-expanded="false">Таблица</button>
      <button class="theme-btn" id="themeBtn">Тема</button>
    </div>

    <div class="legend">
      <div class="item" id="lgFundItem"><span class="key" style="background:var(--series-fund)"></span><span id="lgFund"></span></div>
      <div class="item" id="lgIndexItem"><span class="key" style="background:var(--series-index)"></span><span id="lgIndex"></span></div>
      <div class="item" id="lgDiffItem"><span class="key dashed"></span><span>Разница (фонд − индекс)</span></div>
    </div>

    <figure style="position:relative">
      <div class="wm-clip" aria-hidden="true"><div class="watermark"></div></div>
      <svg id="chart" viewBox="0 0 960 420" preserveAspectRatio="xMidYMid meet" role="img" aria-label="График доходности" style="position:relative;z-index:1"></svg>
      <div class="tip" id="tip"></div>
    </figure>

    <div class="stats" id="stats"></div>

    <div class="datawrap" id="datawrap">
      <table id="dtable"><thead></thead><tbody></tbody></table>
    </div>
  </div>

  <p class="note" id="note"></p>
</div>

<script>
const DATA = /*__DATA__*/;

// ---- утилиты дат -----------------------------------------------------------
const DAY = 86400000;
const toTs = s => { const [y,m,d]=s.split('-').map(Number); return Date.UTC(y,m-1,d); };
const fmtD = ts => { const dt=new Date(ts); const p=n=>String(n).padStart(2,'0');
  return `${p(dt.getUTCDate())}.${p(dt.getUTCMonth()+1)}.${dt.getUTCFullYear()}`; };
const fmtPct = v => v.toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2,signDisplay:'exceptZero'})+'%';

const FUND_NAV_LABEL = 'СЧА фонда «Матрёшка а-ля Рус»';
const fund = DATA.fund.points.map(p=>({t:toTs(p.date), v:p.v, nav:p.nav}));
const index = DATA.index.points.map(p=>({t:toTs(p.date), v:p.v}));

const allTs = [...fund, ...index].map(p=>p.t);
const DMAX = Math.max(...allTs);
const DMIN = Math.min(...allTs);

const RANGES = [
  {id:'1m', label:'1М', days:30},
  {id:'3m', label:'3М', days:91},
  {id:'6m', label:'6М', days:182},
  {id:'1y', label:'1Г', days:365},
  {id:'ytd',label:'YTD', ytd:true},
  {id:'all',label:'Всё', all:true},
];
const MODES = [
  {id:'return', label:'Доходность'},
  {id:'nav', label:'СЧА'},
];
let current = 'all';
let mode = 'return';
let showDiff = true;   // показывать линию «Разница (фонд − индекс)»

function windowStart(r){
  if(r.all) return DMIN;
  if(r.ytd) return Date.UTC(new Date(DMAX).getUTCFullYear(),0,1);
  return Math.max(DMIN, DMAX - r.days*DAY);
}

const fmtNum = v => v.toLocaleString('ru-RU',{minimumFractionDigits:2, maximumFractionDigits:2});
const fmtRub = v => fmtNum(v)+' ₽';
const fmtMln = v => (v/1e6).toLocaleString('ru-RU',{maximumFractionDigits:1});

// приводим серию к % относительно базовой точки.
// priorBase=true — база берётся из последней точки ДО начала окна
// (для YTD это последнее значение прошлого года, т.е. рост от закрытия 31.12);
// иначе — первая точка внутри окна.
function rebase(series, from, priorBase){
  const win = series.filter(p=>p.t>=from && p.t<=DMAX);
  if(!win.length) return [];
  let base = win[0].v;
  if(priorBase){
    const before = series.filter(p=>p.t<from);
    if(before.length) base = before[before.length-1].v;
  }
  return win.map(p=>{const pct=(p.v/base-1)*100; return {t:p.t, y:pct, s:fmtPct(pct), raw:p.v};});
}

// спецификация графика под текущий режим
function prep(){
  const from = windowStart(RANGES.find(x=>x.id===current));
  if(mode==='nav'){
    // динамика СЧА фонда в ₽ — одна серия, без сравнения и без ребейза
    const N = fund.filter(p=>p.t>=from && p.t<=DMAX && p.nav!=null)
                  .map(p=>({t:p.t, y:p.nav, s:fmtRub(p.nav)}));
    return {series:[{name:'СЧА фонда', color:'var(--series-fund)', pts:N}],
            yfmt:fmtMln, ytitle:'СЧА, млн ₽', forceZero:false,
            endfmt:v=>fmtMln(v)+' млн ₽'};
  }
  const priorBase = current==='ytd';  // YTD: база — последнее значение прошлого года
  const F = rebase(fund, from, priorBase), I = rebase(index, from, priorBase);
  const series=[
    {name:'Фонд', color:'var(--series-fund)', pts:F},
    {name:'Индекс', color:'var(--series-index)', pts:I},
  ];
  if(showDiff && F.length && I.length){
    const im=new Map(I.map(p=>[p.t,p.y]));
    const D=F.filter(p=>im.has(p.t)).map(p=>{const d=p.y-im.get(p.t); return {t:p.t, y:d, s:fmtPct(d)};});
    if(D.length) series.push({name:'Разница', color:'var(--series-diff)', pts:D, dash:true});
  }
  return {series, yfmt:v=>v.toLocaleString('ru-RU',{minimumFractionDigits:2,maximumFractionDigits:2})+'%',
          ytitle:'Доходность, %', forceZero:true};
}

// ---- рендер SVG ------------------------------------------------------------
const SVG='http://www.w3.org/2000/svg';
const W=960, H=420, M={t:16,r:64,b:34,l:64};
const PW=W-M.l-M.r, PH=H-M.t-M.b;
const svg=document.getElementById('chart');
const tip=document.getElementById('tip');
let view=null; // текущее состояние для тултипа

function el(name, attrs, txt){
  const e=document.createElementNS(SVG,name);
  for(const k in attrs) e.setAttribute(k, attrs[k]);
  if(txt!=null) e.textContent=txt;
  return e;
}
function niceStep(range, target){
  const raw=range/target, mag=Math.pow(10,Math.floor(Math.log10(raw)));
  const n=raw/mag; const s=n>=5?5:n>=2?2:1; return s*mag;
}

function updateLegend(){
  const indexItem=document.getElementById('lgIndexItem');
  const diffItem=document.getElementById('lgDiffItem');
  const diffChk=document.getElementById('diffChk');
  if(mode==='nav'){
    document.getElementById('lgFund').textContent = FUND_NAV_LABEL;
    indexItem.style.display='none';
    diffItem.style.display='none';
    diffChk.style.display='none';   // разница неприменима в режиме СЧА
  } else {
    document.getElementById('lgFund').textContent = DATA.fund.label;
    document.getElementById('lgIndex').textContent = DATA.index.label;
    indexItem.style.display='';
    diffChk.style.display='';
    diffItem.style.display = showDiff ? '' : 'none';
  }
}

function render(){
  const spec=prep();
  svg.textContent='';
  view=null;
  updateLegend();
  const pts=spec.series.flatMap(s=>s.pts);
  if(!pts.length){ svg.appendChild(el('text',{x:W/2,y:H/2,'text-anchor':'middle',fill:'var(--muted)'},'Нет данных за интервал')); renderStats(spec); return; }

  const t0=Math.min(...pts.map(p=>p.t)), t1=Math.max(...pts.map(p=>p.t));
  const ys=pts.map(p=>p.y);
  let lo=Math.min(...ys), hi=Math.max(...ys);
  if(spec.forceZero){ lo=Math.min(0,lo); hi=Math.max(0,hi); }
  const pad=(hi-lo)*0.08||Math.abs(hi)*0.08||1; lo-=pad; hi+=pad;
  const x=t=> M.l + (t1===t0?0:(t-t0)/(t1-t0))*PW;
  const y=v=> M.t + (1-(v-lo)/(hi-lo))*PH;

  // сетка + ось Y
  const g=el('g',{class:'grid'}); const ax=el('g',{class:'axis'});
  const stepY=niceStep(hi-lo,5);
  for(let v=Math.ceil(lo/stepY)*stepY; v<=hi; v+=stepY){
    const yy=y(v);
    g.appendChild(el('line',{x1:M.l,y1:yy,x2:M.l+PW,y2:yy}));
    ax.appendChild(el('text',{x:M.l-8,y:yy+4,'text-anchor':'end'},spec.yfmt(v)));
  }
  // ось X (даты) + вертикальная сетка
  const span=t1-t0; const ticks=5;
  for(let i=0;i<=ticks;i++){
    const t=t0+span*i/ticks; const xx=x(t);
    g.appendChild(el('line',{x1:xx,y1:M.t,x2:xx,y2:M.t+PH}));
    ax.appendChild(el('text',{x:xx,y:H-12,'text-anchor':'middle'},fmtD(t)));
  }
  svg.appendChild(g);
  svg.appendChild(ax);
  // нулевая линия (только в режиме доходности)
  if(spec.forceZero) svg.appendChild(el('line',{class:'zero',x1:M.l,y1:y(0),x2:M.l+PW,y2:y(0)}));
  // подпись оси Y
  svg.appendChild(el('text',{class:'yttl',x:M.l,y:M.t-4,fill:'var(--muted)'},spec.ytitle));

  const path=pp=>pp.map((p,i)=>(i?'L':'M')+x(p.t).toFixed(1)+' '+y(p.y).toFixed(1)).join(' ');
  // рисуем в обратном порядке, чтобы первая серия (фонд) была сверху
  [...spec.series].reverse().forEach(s=>{ if(!s.pts.length) return;
    const attrs={class:'line',d:path(s.pts),stroke:s.color};
    if(s.dash) attrs['stroke-dasharray']='6 5';
    svg.appendChild(el('path',attrs)); });
  // прямые подписи в конце линий
  spec.series.forEach(s=>{ if(!s.pts.length) return; const last=s.pts[s.pts.length-1];
    const cx=x(last.t), cy=y(last.y);
    svg.appendChild(el('circle',{cx:cx, cy:cy, r:5, fill:s.color, stroke:'var(--surface-1)', 'stroke-width':1.5}));
    const txt=spec.endfmt?spec.endfmt(last.y):last.s;
    svg.appendChild(el('text',{class:'endlbl',x:cx+11,y:cy+5,fill:s.color},txt)); });

  view={series:spec.series, x, y, t0, t1};
  const cross=el('line',{class:'cross',x1:0,y1:M.t,x2:0,y2:M.t+PH,opacity:0}); cross.id='cross';
  svg.appendChild(cross);
  renderStats(spec);
}

function nearest(series, t){
  if(!series.length) return null;
  let best=series[0], bd=Math.abs(series[0].t-t);
  for(const p of series){ const d=Math.abs(p.t-t); if(d<bd){bd=d;best=p;} }
  return best;
}

// crosshair + единый тултип
svg.addEventListener('pointermove', ev=>{
  if(!view) return;
  const rect=svg.getBoundingClientRect();
  const sx=(ev.clientX-rect.left)/rect.width*W;
  const t=view.t0+(view.t1-view.t0)*Math.min(1,Math.max(0,(sx-M.l)/PW));
  const union=view.series.flatMap(s=>s.pts); if(!union.length) return;
  const snap=nearest(union,t);
  const cross=document.getElementById('cross');
  cross.setAttribute('x1',view.x(snap.t)); cross.setAttribute('x2',view.x(snap.t)); cross.setAttribute('opacity',1);
  tip.textContent='';
  const dd=document.createElement('div'); dd.className='d'; dd.textContent=fmtD(snap.t); tip.appendChild(dd);
  const pys=[];
  view.series.forEach(s=>{ const p=nearest(s.pts,snap.t); if(!p) return;
    const r=document.createElement('div'); r.className='row';
    const k=document.createElement('span'); k.className='k'; k.style.background=s.color;
    const nm=document.createElement('span'); nm.className='nm'; nm.textContent=s.name;
    const v=document.createElement('span'); v.className='v'; v.textContent=p.s;
    r.append(k,nm,v); tip.appendChild(r); pys.push(view.y(p.y)); });
  tip.style.opacity=1;
  const px=view.x(snap.t)/W*rect.width;
  const py=Math.min(...pys)/H*rect.height;
  tip.style.left=px+'px'; tip.style.top=py+'px';
});
svg.addEventListener('pointerleave', ()=>{ tip.style.opacity=0; const c=document.getElementById('cross'); if(c)c.setAttribute('opacity',0); });

// ---- статы + таблица -------------------------------------------------------
function statTile(box, label, text, cls, color){
  const d=document.createElement('div'); d.className='stat';
  const lab=document.createElement('div'); lab.className='lab';
  if(color){ const k=document.createElement('span'); k.className='key';
    k.style.cssText='width:12px;height:2px;border-radius:2px;background:'+color; lab.append(k); }
  lab.append(document.createTextNode(label));
  const num=document.createElement('div'); num.className='num '+(cls||''); num.textContent=text;
  d.append(lab,num); box.appendChild(d);
}

function renderStats(spec){
  const box=document.getElementById('stats'); box.textContent='';
  if(mode==='nav'){
    const N=spec.series[0].pts;
    const last=N.length?N[N.length-1].y:null, first=N.length?N[0].y:null;
    statTile(box,'СЧА на конец', last==null?'—':fmtRub(last),'');
    if(last!=null && first!=null){
      const dv=last-first, pc=(last/first-1)*100;
      statTile(box,'Изменение за интервал',(dv>=0?'+':'')+fmtRub(dv)+'  ('+fmtPct(pc)+')', dv>=0?'pos':'neg');
    }
    buildTable(spec); return;
  }
  const F=spec.series[0].pts, I=spec.series[1].pts;
  const lastPct=s=>s.length?s[s.length-1].y:null;
  const fv=lastPct(F), iv=lastPct(I);
  statTile(box,'Фонд', fv==null?'—':fmtPct(fv), fv==null?'':fv>=0?'pos':'neg','var(--series-fund)');
  statTile(box,'Индекс', iv==null?'—':fmtPct(iv), iv==null?'':iv>=0?'pos':'neg','var(--series-index)');
  if(fv!=null && iv!=null){
    const diff=fv-iv;
    statTile(box,'Разница (фонд − индекс)', fmtPct(diff), diff>=0?'pos':'neg');
  }
  buildTable(spec);
}

function buildTable(spec){
  const thead=document.querySelector('#dtable thead'); const tbody=document.querySelector('#dtable tbody');
  thead.textContent=''; tbody.textContent='';
  const headers = mode==='nav'
    ? ['Дата','СЧА, ₽','Изм. от старта, %']
    : ['Дата','Пай, ₽','Фонд, %','Индекс MCFTR','Индекс, %'].concat(showDiff?['Разница, %']:[]);
  const hr=document.createElement('tr');
  headers.forEach(h=>{const th=document.createElement('th');th.textContent=h;hr.appendChild(th);});
  thead.appendChild(hr);
  const addRow=vals=>{const tr=document.createElement('tr');
    vals.forEach(v=>{const td=document.createElement('td'); td.textContent=v; tr.appendChild(td);});
    tbody.appendChild(tr);};

  if(mode==='nav'){
    const N=spec.series[0].pts; if(!N.length) return;
    const base=N[0].y;
    [...N].reverse().forEach(p=>addRow([fmtD(p.t), fmtNum(p.y), fmtPct((p.y/base-1)*100)]));
    return;
  }
  // режим доходности: сырые значения (пай/индекс) + доходность в %
  const F=spec.series[0].pts, I=spec.series[1].pts;
  const fm=new Map(F.map(p=>[p.t,p])), im=new Map(I.map(p=>[p.t,p]));
  const dates=[...new Set([...fm.keys(),...im.keys()])].sort((a,b)=>b-a);
  for(const t of dates){
    const f=fm.get(t), i=im.get(t);
    const row=[fmtD(t),
      f?fmtNum(f.raw):'—', f?fmtPct(f.y):'—',
      i?fmtNum(i.raw):'—', i?fmtPct(i.y):'—'];
    if(showDiff) row.push((f&&i)?fmtPct(f.y-i.y):'—');
    addRow(row);
  }
}

// ---- контролы --------------------------------------------------------------
const mbox=document.getElementById('modes');
MODES.forEach(m=>{
  const b=document.createElement('button'); b.textContent=m.label; b.dataset.id=m.id;
  b.setAttribute('aria-pressed', m.id===mode);
  b.onclick=()=>{ mode=m.id; [...mbox.children].forEach(c=>c.setAttribute('aria-pressed', c.dataset.id===mode)); render(); };
  mbox.appendChild(b);
});
const rbox=document.getElementById('ranges');
RANGES.forEach(r=>{
  const b=document.createElement('button'); b.textContent=r.label; b.dataset.id=r.id;
  b.setAttribute('aria-pressed', r.id===current);
  b.onclick=()=>{ current=r.id; [...rbox.children].forEach(c=>c.setAttribute('aria-pressed', c.dataset.id===current)); render(); };
  rbox.appendChild(b);
});
document.getElementById('diffToggle').onchange=e=>{ showDiff=e.target.checked; render(); };
document.getElementById('tblBtn').onclick=e=>{
  const w=document.getElementById('datawrap'); const open=w.classList.toggle('open');
  e.target.setAttribute('aria-expanded', open);
};
document.getElementById('themeBtn').onclick=()=>{
  const root=document.documentElement;
  const cur=root.getAttribute('data-theme');
  const dark=cur? cur==='dark' : matchMedia('(prefers-color-scheme:dark)').matches;
  root.setAttribute('data-theme', dark?'light':'dark');
};

document.getElementById('note').textContent =
  'Данные на '+DATA.generated+'. Фонд: alfacapital.ru · Индекс MCFTR: iss.moex.com. '+
  'Доходность = изменение к первому дню интервала.';

render();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Генерация HTML-графика доходности")
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()

    fund, idx = load_series(args.db)
    if not fund and not idx:
        print("В базе нет данных. Сначала запусти collect.py.")
        return 1
    html = build_html(fund, idx)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"График: {args.out}  (фонд {len(fund)} точек, индекс {len(idx)} точек)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
