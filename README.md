import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import requests, threading, time, traceback
import ccxt
import numpy as np
from datetime import datetime

###############################################################################
# KONFİG
###############################################################################
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
BINANCE_INFO_URL   = "https://api.binance.com/api/v3/exchangeInfo"

TIMEFRAMES = [
    ("1 Dakika","1m"),
    ("5 Dakika","5m"),
    ("15 Dakika","15m"),
    ("1 Saat","1h"),
    ("4 Saat","4h"),
    ("Günlük","1d"),
]

MAX_SYMBOLS_FOR_SIGNALS = 25
OHLC_LIMIT = 250
MIN_BARS_FOR_SIGNAL = 120
SIGNAL_REFRESH_SECONDS = 60
TICKER_REFRESH_SECONDS = 8
LOG_MAX_LINES = 900
ANALYSIS_MAX_ROWS = 80
SIGNAL_MAX_ROWS = 80
POSITION_AUTO_UPDATE_INTERVAL = 4

# Portföy & Risk
START_EQUITY = 10_000.0
RISK_PER_TRADE = 0.01
PARTIAL_TP_RATIOS = [0.4, 0.3, 0.3]
MOVE_SL_TO_BE_AFTER_TP1 = True
ADVANCED_SL_AFTER_TP2 = True

# Backtest
BACKTEST_BARS = 400
BACKTEST_LOOKAHEAD = 30

# Pozisyon satır font boyutu (istek: 5)
POS_ROW_FONT_SIZE = 5  # Çok küçük; gerekirse 7-8 yap

RISK_PARAMS = {
    "rr_tiers": [1.5, 2.5, 3.5],
    "atr_period": 14,
    "ema_fast": 50,
    "ema_slow": 200,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "rsi_period": 14,
    "stoch_rsi_period": 14,
}

###############################################################################
# İNDİKATÖRLER
###############################################################################
def ema_np(arr, period):
    if len(arr) == 0: return np.array([])
    k = 2/(period+1)
    out = np.empty_like(arr, dtype=float)
    out[0] = arr[0]
    for i in range(1,len(arr)):
        out[i] = arr[i]*k + out[i-1]*(1-k)
    return out

def rsi_np(arr, period=14):
    if len(arr) < period+1:
        return np.full_like(arr, 50.0)
    diff = np.diff(arr, prepend=arr[0])
    up = np.where(diff>0, diff, 0)
    dn = np.where(diff<0, -diff, 0)
    rs_up = np.zeros_like(up)
    rs_dn = np.zeros_like(dn)
    rs_up[period-1] = up[:period].mean()
    rs_dn[period-1] = dn[:period].mean()
    for i in range(period, len(arr)):
        rs_up[i] = (rs_up[i-1]*(period-1) + up[i]) / period
        rs_dn[i] = (rs_dn[i-1]*(period-1) + dn[i]) / period
    rs = np.divide(rs_up, rs_dn, out=np.full_like(rs_up, np.nan), where=rs_dn!=0)
    rsi = 100 - (100/(1+rs))
    rsi[:period] = 50
    return np.nan_to_num(rsi, nan=50)

def macd_np(arr, fast=12, slow=26, signal=9):
    if len(arr)==0:
        return np.array([]), np.array([]), np.array([])
    ema_fast = ema_np(arr, fast)
    ema_slow = ema_np(arr, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema_np(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def atr_np(high, low, close, period=14):
    if len(close) == 0: return np.array([])
    tr = np.zeros_like(close)
    tr[0] = high[0]-low[0]
    for i in range(1,len(close)):
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
    atr = np.empty_like(tr)
    atr[:period] = tr[:period].mean() if len(tr)>=period else tr.mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i-1]*(period-1)+tr[i])/period
    return atr

def stoch_rsi_np(rsi, period=14):
    if len(rsi)==0: return np.array([])
    st = np.zeros_like(rsi, dtype=float)
    for i in range(len(rsi)):
        start = max(0, i-period+1)
        window = rsi[start:i+1]
        mn = window.min(); mx = window.max(); rng = mx-mn
        st[i] = 0.5 if rng==0 else (rsi[i]-mn)/rng
    return st

###############################################################################
# DESTEK / DİRENÇ
###############################################################################
def swing_levels(high, low, lookback=3):
    resistances, supports = [], []
    n = len(high)
    for i in range(lookback, n - lookback):
        is_res = True
        is_sup = True
        for j in range(i-lookback, i+lookback+1):
            if j==i: continue
            if high[i] <= high[j]: is_res=False
            if low[i]  >= low[j]: is_sup=False
            if not is_res and not is_sup: break
        if is_res: resistances.append(high[i])
        if is_sup: supports.append(low[i])
    def uniq(seq, prec=8):
        return sorted({round(x,prec) for x in seq})
    return uniq(supports), uniq(resistances)

###############################################################################
# SİNYAL
###############################################################################
def generate_signals(ohlc, config=RISK_PARAMS, lev=5):
    close = np.array(ohlc['close'], dtype=float)
    high  = np.array(ohlc['high'], dtype=float)
    low   = np.array(ohlc['low'], dtype=float)
    vol   = np.array(ohlc['volume'], dtype=float)
    if len(close) < MIN_BARS_FOR_SIGNAL: return []
    ema_fast = ema_np(close, config["ema_fast"])
    ema_slow = ema_np(close, config["ema_slow"])
    macd_line, macd_sig, _ = macd_np(close, config["macd_fast"], config["macd_slow"], config["macd_signal"])
    rsi = rsi_np(close, config["rsi_period"])
    stoch_rsi = stoch_rsi_np(rsi, config["stoch_rsi_period"])
    atr = atr_np(high, low, close, config["atr_period"])
    supports, resistances = swing_levels(high, low, lookback=3)

    idx=-1
    last_close = close[idx]
    last_rsi = rsi[idx]
    last_macd = macd_line[idx]
    last_macd_sig = macd_sig[idx]
    last_stoch = stoch_rsi[idx]
    last_ema_fast = ema_fast[idx]
    last_ema_slow = ema_slow[idx]
    last_atr = atr[idx] if len(atr) else None
    vol_ma = np.convolve(vol, np.ones(20)/20, 'same')
    last_vol = vol[idx]
    last_vol_ma = vol_ma[idx] if len(vol_ma) else None

    conditions_long=[]
    conditions_short=[]
    def add(lst, cond, label):
        if cond: lst.append(label)
    add(conditions_long, last_ema_fast > last_ema_slow, "EMA Bull")
    add(conditions_short,last_ema_fast < last_ema_slow, "EMA Bear")
    add(conditions_long, last_macd > last_macd_sig, "MACD Up")
    add(conditions_short,last_macd < last_macd_sig, "MACD Down")
    add(conditions_long, last_rsi < 32, "RSI Aş.Satım")
    add(conditions_short,last_rsi > 68, "RSI Aş.Alım")
    add(conditions_long, last_stoch < 0.2, "Stoch Low")
    add(conditions_short,last_stoch > 0.8, "Stoch High")
    add(conditions_long, (last_vol_ma and last_vol_ma>0 and last_vol > 1.2*last_vol_ma), "Hacim Artış")
    add(conditions_short,(last_vol_ma and last_vol_ma>0 and last_vol > 1.2*last_vol_ma), "Hacim Artış")

    sigs=[]
    rr_list = config["rr_tiers"]
    rr_abs = [last_close*0.01*r for r in [1,2,3]] if (not last_atr or last_atr<=0) else [last_atr*rr for rr in rr_list]

    if len(conditions_long)>=2 and supports and resistances:
        below=[s for s in supports if s < last_close]
        sl = max(below) if below else min(supports)
        tps=[last_close + x for x in rr_abs]
        tps_pct=[((tp-last_close)/last_close)*100*lev for tp in tps]
        sigs.append({"direction":"LONG","entry":float(last_close),"sl":float(sl),
                     "tps":[float(x) for x in tps],"tps_yuzde":[float(y) for y in tps_pct],
                     "reasons":conditions_long,"atr":float(last_atr) if last_atr else None,
                     "lev":lev,"supports":supports[-5:],"resistances":resistances[:5]})
    if len(conditions_short)>=2 and supports and resistances:
        above=[r for r in resistances if r > last_close]
        sl = min(above) if above else max(resistances)
        tps=[last_close - x for x in rr_abs]
        tps_pct=[((last_close-tp)/last_close)*100*lev for tp in tps]
        sigs.append({"direction":"SHORT","entry":float(last_close),"sl":float(sl),
                     "tps":[float(x) for x in tps],"tps_yuzde":[float(y) for y in tps_pct],
                     "reasons":conditions_short,"atr":float(last_atr) if last_atr else None,
                     "lev":lev,"supports":supports[-5:],"resistances":resistances[:5]})
    return sigs

###############################################################################
# VERİ
###############################################################################
def fetch_ohlcv_ccxt(exchange, symbol, timeframe, limit):
    try:
        raw=exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw: return None
        ts,o,h,l,c,v=[],[],[],[],[],[]
        for r in raw:
            ts.append(r[0]); o.append(float(r[1])); h.append(float(r[2]))
            l.append(float(r[3])); c.append(float(r[4])); v.append(float(r[5]))
        return {"ts":ts,"open":o,"high":h,"low":l,"close":c,"volume":v}
    except Exception:
        return None

###############################################################################
# UYGULAMA
###############################################################################
class SignalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Binance Sinyal / Analiz Botu (Demo)")
        try: self.geometry("930x1280")
        except: pass
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # State
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.active_usdt_pairs=[]
        self.ticker_map={}
        self.rises=[]
        self.falls=[]
        self.api_error=False
        self.selected_timeframe=tk.StringVar(value="1h")
        self.signals=[]
        self.analysis_signals=[]
        self.stop_event=threading.Event()
        self.signal_refresh_flag=threading.Event()

        self.log_lines=[]
        self.log_lock=threading.Lock()
        self.analysis_mode=tk.StringVar(value="AI")
        self.analysis_side=tk.StringVar(value="LONG")
        self.filter_min_reasons=tk.IntVar(value=0)
        self.search_log_var=tk.StringVar()
        self.coin_filter=tk.StringVar(value="Hepsi")
        self.current_detail_signal=None

        # Portföy
        self.base_equity = START_EQUITY
        self.realized_pnl = 0.0
        self.open_positions=[]

        self.build_ui()
        self.start_threads()
        self.after(1000, self.clock_update)
        self.after(POSITION_AUTO_UPDATE_INTERVAL*1000, self.position_auto_update_loop)

    ############################################################################
    # UI
    ############################################################################
    def build_ui(self):
        self.nb=ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_home=tk.Frame(self.nb, bg="#f8f8f8")
        self.tab_signals=tk.Frame(self.nb, bg="#f8f8f8")
        self.tab_detail=tk.Frame(self.nb, bg="#f8f8f8")
        self.tab_positions=tk.Frame(self.nb, bg="#f8f8f8")
        self.tab_analysis=tk.Frame(self.nb, bg="#f8f8f8")
        self.tab_logs=tk.Frame(self.nb, bg="#f8f8f8")
        for t, label in [
            (self.tab_home,"Anasayfa"),
            (self.tab_signals,"Sinyaller"),
            (self.tab_detail,"Detay"),
            (self.tab_positions,"Pozisyonlar"),
            (self.tab_analysis,"Analiz"),
            (self.tab_logs,"Log")
        ]:
            self.nb.add(t, text=label)
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        self.build_home()
        self.build_signals()
        self.build_detail()
        self.build_positions()
        self.build_analysis()
        self.build_logs()

    def build_home(self):
        top=tk.Frame(self.tab_home, bg="#f8f8f8"); top.pack(pady=6)
        self.time_label=tk.Label(top, text="", font=("Arial",11,"bold"), bg="#f8f8f8")
        self.time_label.pack()
        self.status_label=tk.Label(self.tab_home, text="Durum: -", font=("Arial",10,"bold"), fg="red", bg="#f8f8f8")
        self.status_label.pack(pady=3)
        self.btc_label=tk.Label(self.tab_home, text="BTCUSDT: -", font=("Arial",9,"bold"), bg="#f8f8f8"); self.btc_label.pack()
        self.usdttry_label=tk.Label(self.tab_home, text="USDTTRY: -", font=("Arial",9,"bold"), bg="#f8f8f8"); self.usdttry_label.pack()

        # Portföy Paneli
        portfolio_frame=tk.Frame(self.tab_home, bg="#eef7ff", bd=1, relief="groove")
        portfolio_frame.pack(pady=8, fill="x", padx=6)

        # Tüm Pozisyonları Kapat üstte ortalı
        close_all_btn = tk.Button(portfolio_frame, text="Tüm Pozisyonları Kapat",
                                  font=("Arial",9,"bold"), bg="#ffe0e0",
                                  command=self.close_all_positions)
        close_all_btn.pack(pady=(6,4))

        self.portfolio_label  = tk.Label(portfolio_frame, text="Portföy (USDT): -", font=("Arial",9,"bold"), bg="#eef7ff")
        self.portfolio_label.pack(anchor="w", padx=6)
        self.realized_label   = tk.Label(portfolio_frame, text="Gerçekleşen Kar/Zarar: -", font=("Arial",9), bg="#eef7ff")
        self.realized_label.pack(anchor="w", padx=6)
        self.unrealized_label = tk.Label(portfolio_frame, text="Gerçekleşmemiş Kar/Zarar: -", font=("Arial",9), bg="#eef7ff")
        self.unrealized_label.pack(anchor="w", padx=6, pady=(0,4))

        pf_btns=tk.Frame(portfolio_frame, bg="#eef7ff")
        pf_btns.pack(anchor="center", padx=4, pady=(0,6))
        tk.Button(pf_btns, text="Portföy Ayarla", font=("Arial",8),
                  command=self.set_portfolio_amount).pack(side="left", padx=4)
        tk.Button(pf_btns, text="Log Temizle", font=("Arial",8),
                  command=self.clear_logs).pack(side="left", padx=4)

        tf_frame=tk.Frame(self.tab_home, bg="#f8f8f8"); tf_frame.pack(pady=4)
        tk.Label(tf_frame, text="Zaman Dilimi:", font=("Arial",9,"bold"), bg="#f8f8f8").pack(side="left")
        self.tf_combo=ttk.Combobox(tf_frame, state="readonly", width=10, values=[t[0] for t in TIMEFRAMES])
        self.tf_combo.current(3); self.tf_combo.pack(side="left", padx=6)
        tk.Button(tf_frame, text="Uygula", command=self.on_timeframe_select, bg="#ddeeff").pack(side="left")

        counts=tk.Frame(self.tab_home, bg="#f8f8f8"); counts.pack(pady=4)
        self.long_btn=tk.Button(counts, text="Long: 0", bg="#2e7d32", fg="white",
                                command=lambda: self.goto_signals("LONG"), width=14)
        self.long_btn.pack(side="left", padx=6)
        self.short_btn=tk.Button(counts, text="Short: 0", bg="#b71c1c", fg="white",
                                 command=lambda: self.goto_signals("SHORT"), width=14)
        self.short_btn.pack(side="left", padx=6)

        refresh_frame=tk.Frame(self.tab_home, bg="#f8f8f8"); refresh_frame.pack(pady=4)
        tk.Button(refresh_frame, text="Sinyalleri Yenile (Manuel)", command=self.manual_signal_refresh,
                  bg="#e0ffe0").pack(side="left", padx=4)

        self.rise_table = self._mini_table(self.tab_home,"En Çok Yükselenler","#006400")
        self.fall_table = self._mini_table(self.tab_home,"En Çok Düşenler","#8B0000")

        coin_filter_frame=tk.Frame(self.tab_home, bg="#f8f8f8"); coin_filter_frame.pack(pady=8)
        tk.Label(coin_filter_frame, text="Coin Filtresi:", font=("Arial",9,"bold"), bg="#f8f8f8").pack(side="left")
        self.coin_filter_combo=ttk.Combobox(coin_filter_frame, state="readonly", width=12, values=["Hepsi"])
        self.coin_filter_combo.current(0); self.coin_filter_combo.pack(side="left", padx=5)
        tk.Button(coin_filter_frame, text="Ayarla", command=self.on_coin_filter).pack(side="left", padx=4)

        self.update_portfolio_labels(0.0)

    def _mini_table(self, parent, title, color):
        tk.Label(parent, text=title, font=("Arial",11,"bold"), fg=color, bg=parent["bg"]).pack(pady=(8,4))
        frame=tk.Frame(parent, bg=parent["bg"]); frame.pack()
        headers=["Coin","Fiyat","%"]; widths=[10,14,8]
        hr=tk.Frame(frame, bg=parent["bg"]); hr.pack()
        for i,h in enumerate(headers):
            tk.Label(hr, text=h, font=("Arial",9,"bold"), width=widths[i], bg=parent["bg"]).pack(side="left", padx=2)
        rows=[]
        for _ in range(5):
            r=tk.Frame(frame, bg=parent["bg"]); r.pack()
            labs=[]
            for i in range(3):
                lab=tk.Label(r, text="-", font=("Arial",9), width=widths[i], bg=parent["bg"])
                lab.pack(side="left", padx=2); labs.append(lab)
            rows.append(labs)
        return rows

    def build_signals(self):
        top=tk.Frame(self.tab_signals, bg="#f8f8f8"); top.pack(fill="x", pady=4)
        tk.Label(top, text="Sinyaller", font=("Arial",12,"bold"), bg=top["bg"]).pack(side="left", padx=10)
        list_frame=tk.Frame(self.tab_signals, bg="#f8f8f8"); list_frame.pack(fill="both", expand=True)
        self.signal_canvas=tk.Canvas(list_frame, bg="#ffffff")
        self.signal_canvas.pack(side="left", fill="both", expand=True)
        scr=tk.Scrollbar(list_frame, orient="vertical", command=self.signal_canvas.yview)
        scr.pack(side="right", fill="y")
        self.signal_canvas.configure(yscrollcommand=scr.set)
        self.signal_inner=tk.Frame(self.signal_canvas, bg="#ffffff")
        self.signal_canvas.create_window((0,0), window=self.signal_inner, anchor="nw")
        self.signal_inner.bind("<Configure>", lambda e: self.signal_canvas.configure(scrollregion=self.signal_canvas.bbox("all")))

    def build_detail(self):
        self.detail_title=tk.Label(self.tab_detail, text="Seçili Sinyal Yok", font=("Arial",16,"bold"), bg="#f8f8f8")
        self.detail_title.pack(pady=10)
        box=tk.Frame(self.tab_detail, bg="#ffffff", bd=1, relief="groove"); box.pack(padx=10, pady=5, fill="x")
        self.detail_labels={}
        fields=["Yön","Giriş","SL","TP1","TP2","TP3","Leverage","Reasons","Timeframe","ATR","R:R1","R:R2","R:R3","Test PnL"]
        for f in fields:
            row=tk.Frame(box, bg="#ffffff"); row.pack(anchor="w", fill="x", pady=1)
            tk.Label(row, text=f+":", font=("Arial",9,"bold"), width=10, bg="#ffffff").pack(side="left")
            val=tk.Label(row, text="-", font=("Arial",9), bg="#ffffff", anchor="w", wraplength=620, justify="left")
            val.pack(side="left", fill="x", expand=True); self.detail_labels[f]=val
        btns=tk.Frame(self.tab_detail, bg="#f8f8f8"); btns.pack(pady=8)
        tk.Button(btns, text="Sinyallere Geri", command=lambda: self.nb.select(self.tab_signals)).pack(side="left", padx=6)
        tk.Button(btns, text="Anasayfa", command=lambda: self.nb.select(self.tab_home)).pack(side="left", padx=6)
        tk.Button(btns, text="Pozisyon Aç (Test)", bg="#c8facc",
                  command=self.open_current_detail_position).pack(side="left", padx=6)
        tk.Button(btns, text="Backtest", bg="#d0e8ff", command=self.backtest_current_signal).pack(side="left", padx=6)

    def build_positions(self):
        top=tk.Frame(self.tab_positions, bg="#f8f8f8"); top.pack(fill="x", pady=4)
        tk.Label(top, text="Pozisyonlar", font=("Arial",12,"bold"), bg=top["bg"]).pack(side="left", padx=10)
        frame=tk.Frame(self.tab_positions, bg="#f8f8f8")
        frame.pack(fill="both", expand=True)
        self.pos_canvas=tk.Canvas(frame, bg="#ffffff")
        self.pos_canvas.pack(side="left", fill="both", expand=True)
        pos_scr=tk.Scrollbar(frame, orient="vertical", command=self.pos_canvas.yview)
        pos_scr.pack(side="right", fill="y")
        self.pos_canvas.configure(yscrollcommand=pos_scr.set)
        self.pos_inner=tk.Frame(self.pos_canvas, bg="#ffffff")
        self.pos_canvas.create_window((0,0), window=self.pos_inner, anchor="nw")
        self.pos_inner.bind("<Configure>", lambda e: self.pos_canvas.configure(scrollregion=self.pos_canvas.bbox("all")))

    def build_analysis(self):
        top=tk.Frame(self.tab_analysis, bg="#f8f8f8"); top.pack(fill="x", pady=6)
        tk.Label(top, text="Analiz Modu:", font=("Arial",10,"bold"), bg=top["bg"]).pack(side="left")
        self.analysis_combo=ttk.Combobox(top, state="readonly", width=10, values=["AI","Teknik","Temel"])
        self.analysis_combo.current(0); self.analysis_combo.pack(side="left", padx=6)
        self.analysis_combo.bind("<<ComboboxSelected>>", lambda e: self.update_analysis_list())
        tk.Button(top, text="LONG", command=lambda: self.set_analysis_side("LONG"), bg="#c8fbd8").pack(side="left", padx=3)
        tk.Button(top, text="SHORT", command=lambda: self.set_analysis_side("SHORT"), bg="#ffd8d8").pack(side="left", padx=3)
        tk.Label(top, text="Min Sebep:", bg=top["bg"]).pack(side="left", padx=(10,2))
        tk.Spinbox(top, from_=0, to=10, width=3, textvariable=self.filter_min_reasons,
                   command=self.update_analysis_list).pack(side="left")
        tk.Button(top, text="Yenile", command=self.update_analysis_list).pack(side="left", padx=6)
        self.analysis_canvas=tk.Canvas(self.tab_analysis, bg="#ffffff")
        self.analysis_canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self.analysis_inner=tk.Frame(self.analysis_canvas, bg="#ffffff")
        self.analysis_canvas.create_window((0,0), window=self.analysis_inner, anchor="nw")
        self.analysis_inner.bind("<Configure>", lambda e: self.analysis_canvas.configure(scrollregion=self.analysis_canvas.bbox("all")))

    def build_logs(self):
        top=tk.Frame(self.tab_logs, bg="#f8f8f8"); top.pack(fill="x", pady=4)
        tk.Label(top, text="Log Kayıtları", font=("Arial",12,"bold"), bg=top["bg"]).pack(side="left", padx=10)
        tk.Entry(top, textvariable=self.search_log_var, width=25).pack(side="left", padx=6)
        tk.Button(top, text="Ara", command=self.update_logbox).pack(side="left")
        self.log_text=tk.Text(self.tab_logs, height=40, width=98, font=("Arial",9), bg="#f0f0f0", state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    ############################################################################
    # EVENT / LOG
    ############################################################################
    def on_tab_changed(self, event):
        sel=self.nb.select()
        if sel==str(self.tab_signals): self.update_signal_list()
        elif sel==str(self.tab_positions): self.refresh_positions()
        elif sel==str(self.tab_analysis): self.update_analysis_list()
        elif sel==str(self.tab_logs): self.update_logbox()

    def on_timeframe_select(self):
        idx=self.tf_combo.current()
        tf_val=TIMEFRAMES[idx][1]
        if self.selected_timeframe.get()!=tf_val:
            self.selected_timeframe.set(tf_val)
            self.signal_refresh_flag.set()
            self.log(f"Zaman dilimi değişti: {tf_val}")

    def on_coin_filter(self):
        val=self.coin_filter_combo.get()
        self.coin_filter.set(val)
        self.update_signal_list()
        self.update_analysis_list()

    def goto_signals(self, side):
        self.analysis_side.set(side)
        self.nb.select(self.tab_signals)
        self.update_signal_list()

    def set_analysis_side(self, side):
        self.analysis_side.set(side)
        self.update_analysis_list()

    def manual_signal_refresh(self):
        self.signal_refresh_flag.set()
        self.log("Manuel sinyal yenile tetiklendi.")

    def clear_logs(self):
        with self.log_lock:
            self.log_lines=[]
        self.update_logbox()
        self.log("Log temizlendi.")

    def log(self, msg):
        with self.log_lock:
            line=f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
            self.log_lines.append(line)
            if len(self.log_lines)>LOG_MAX_LINES:
                self.log_lines=self.log_lines[-LOG_MAX_LINES:]
        if self.nb.select()==str(self.tab_logs):
            self.safe_ui(self.update_logbox)

    def update_logbox(self):
        if not hasattr(self,"log_text"): return
        q=self.search_log_var.get().strip().lower()
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        with self.log_lock:
            for line in self.log_lines[-LOG_MAX_LINES:]:
                if q and q not in line.lower(): continue
                self.log_text.insert(tk.END, line+"\n")
        self.log_text.config(state="disabled")

    ############################################################################
    # PORTFÖY
    ############################################################################
    def update_portfolio_labels(self, unrealized_total):
        total_equity = self.base_equity + self.realized_pnl + unrealized_total
        self.portfolio_label.config(text=f"Portföy (USDT): {total_equity:.2f}")
        self.realized_label.config(text=f"Gerçekleşen Kar/Zarar: {self.realized_pnl:.2f} USDT")
        self.unrealized_label.config(text=f"Gerçekleşmemiş Kar/Zarar: {unrealized_total:.2f} USDT")

    def set_portfolio_amount(self):
        val=simpledialog.askstring("Portföy Ayarla","Yeni portföy (USDT) değeri girin:")
        if not val: return
        try:
            f=float(val)
            if f<=0:
                messagebox.showinfo("Bilgi","Pozitif değer giriniz.")
                return
            self.base_equity=f
            self.log(f"Portföy tabanı güncellendi: {f}")
            self.recalc_and_update_equity()
        except:
            messagebox.showinfo("Hata","Geçersiz sayı.")

    def recalc_and_update_equity(self):
        unreal=self.compute_total_unrealized()
        self.update_portfolio_labels(unreal)

    def compute_total_unrealized(self):
        total=0.0
        for pos in self.open_positions:
            if pos["status"]!="OPEN": continue
            lp=self.live_price(pos['symbol'])
            if lp=="-": continue
            try:
                cur=float(lp); entry=pos['entry']; direction=pos['direction']; lev=pos['lev']; rem=pos['remaining_qty']
                if rem<=0: continue
                pnl_unit=(cur-entry) if direction=="LONG" else (entry-cur)
                pnl = pnl_unit * rem * lev
                total+=pnl
            except: pass
        return total

    ############################################################################
    # SAFE UI
    ############################################################################
    def safe_ui(self, func, *args, **kwargs):
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def clock_update(self):
        if hasattr(self,"time_label"):
            self.time_label.config(text=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        self.after(1000, self.clock_update)

    ############################################################################
    # THREADS
    ############################################################################
    def start_threads(self):
        threading.Thread(target=self.fetch_exchange_info_loop, daemon=True).start()
        threading.Thread(target=self.ticker_loop, daemon=True).start()
        threading.Thread(target=self.signal_loop, daemon=True).start()

    def fetch_exchange_info_loop(self):
        try:
            info=requests.get(BINANCE_INFO_URL, timeout=15).json()
            symbols=[]
            for s in info.get("symbols", []):
                if s.get("quoteAsset")=="USDT" and s.get("status")=="TRADING" and "_" not in s.get("symbol",""):
                    symbols.append(s["symbol"])
            self.active_usdt_pairs=symbols
            self.log(f"Aktif USDT parite sayısı: {len(symbols)}")
        except Exception as e:
            self.log(f"exchangeInfo alınamadı: {e}")

    def ticker_loop(self):
        while not self.stop_event.is_set():
            try:
                r=requests.get(BINANCE_TICKER_URL, timeout=10)
                data=r.json()
                if not isinstance(data, list): raise ValueError("Ticker response list değil")
                filtered=[d for d in data if d['symbol'] in self.active_usdt_pairs]
                usdttry=[d for d in data if d['symbol']=="USDTTRY"]
                filtered.extend(usdttry)
                self.ticker_map={d['symbol']:d for d in filtered}
                mkt=list(self.ticker_map.values())
                if mkt:
                    self.rises=sorted(mkt, key=lambda x: float(x['priceChangePercent']), reverse=True)[:5]
                    self.falls=sorted(mkt, key=lambda x: float(x['priceChangePercent']))[:5]
                    self.api_error=False
                self.safe_ui(self.update_home_section)
            except Exception as e:
                self.api_error=True
                self.log(f"Ticker hatası: {e}")
            time.sleep(TICKER_REFRESH_SECONDS)

    def signal_loop(self):
        while not self.stop_event.is_set():
            self.signal_refresh_flag.clear()
            try:
                market=list(self.ticker_map.values())
                if not market:
                    time.sleep(3); continue
                top=sorted(market, key=lambda x: float(x.get('quoteVolume',"0") or 0), reverse=True)[:MAX_SYMBOLS_FOR_SIGNALS]
                syms=[d['symbol'] for d in top]
                tf=self.selected_timeframe.get()
                new_signals=[]
                for sym in syms:
                    if self.stop_event.is_set() or self.signal_refresh_flag.is_set(): break
                    ccxt_sym=sym.replace("USDT","/USDT")
                    ohlc=fetch_ohlcv_ccxt(self.exchange, ccxt_sym, tf, OHLC_LIMIT)
                    if not ohlc: continue
                    sigs=generate_signals(ohlc, RISK_PARAMS, lev=5)
                    for s in sigs:
                        s['symbol']=sym; s['timeframe']=tf
                        new_signals.append(s)
                self.signals=new_signals
                self.analysis_signals=list(new_signals)
                self.safe_ui(self.on_signals_updated)
            except Exception as e:
                self.log(f"Sinyal döngü hatası: {e} | {traceback.format_exc(limit=1)}")
            for _ in range(SIGNAL_REFRESH_SECONDS):
                if self.stop_event.is_set() or self.signal_refresh_flag.is_set(): break
                time.sleep(1)

    ############################################################################
    # UI GÜNCELLEME
    ############################################################################
    def update_home_section(self):
        if self.api_error or not self.ticker_map:
            self.status_label.config(text="Durum: API Hatası / Veri Yok", fg="red")
            self.btc_label.config(text="BTCUSDT: -")
            self.usdttry_label.config(text="USDTTRY: -")
        else:
            self.status_label.config(text="Durum: OK", fg="green")
            btc=self.ticker_map.get("BTCUSDT")
            if btc:
                self.btc_label.config(text=f"BTCUSDT: {self.fmt_price(btc['lastPrice'])} (%{float(btc['priceChangePercent']):.2f})")
            ut=self.ticker_map.get("USDTTRY")
            if ut:
                self.usdttry_label.config(text=f"USDTTRY: {self.fmt_price(ut['lastPrice'])} (%{float(ut['priceChangePercent']):.2f})")

        for i,row in enumerate(self.rise_table):
            if i<len(self.rises):
                d=self.rises[i]
                row[0].config(text=d['symbol'])
                row[1].config(text=self.fmt_price(d['lastPrice']))
                row[2].config(text=f"%{float(d['priceChangePercent']):.2f}")
            else:
                for c in row: c.config(text="-")
        for i,row in enumerate(self.fall_table):
            if i<len(self.falls):
                d=self.falls[i]
                row[0].config(text=d['symbol'])
                row[1].config(text=self.fmt_price(d['lastPrice']))
                row[2].config(text=f"%{float(d['priceChangePercent']):.2f}")
            else:
                for c in row: c.config(text="-")

        long_count=sum(1 for s in self.signals if s['direction']=="LONG")
        short_count=sum(1 for s in self.signals if s['direction']=="SHORT")
        self.long_btn.config(text=f"Long: {long_count}")
        self.short_btn.config(text=f"Short: {short_count}")

        coins=["Hepsi"]+sorted({s['symbol'] for s in self.signals})
        cur=self.coin_filter.get()
        self.coin_filter_combo['values']=coins
        if cur in coins:
            self.coin_filter_combo.set(cur)
        else:
            self.coin_filter_combo.current(0); self.coin_filter.set("Hepsi")

        self.recalc_and_update_equity()

    def on_signals_updated(self):
        self.update_home_section()
        self.update_signal_list()
        self.update_analysis_list()

    def update_signal_list(self):
        for c in self.signal_inner.winfo_children(): c.destroy()
        side=self.analysis_side.get()
        coin_filt=self.coin_filter.get()
        data=[s for s in self.signals if s['direction']==side]
        if coin_filt!="Hepsi":
            data=[s for s in data if s['symbol']==coin_filt]
        data=data[:SIGNAL_MAX_ROWS]
        for s in data:
            self.create_signal_row(self.signal_inner, s, False)

    def update_analysis_list(self):
        for c in self.analysis_inner.winfo_children(): c.destroy()
        side=self.analysis_side.get()
        mode=self.analysis_combo.get()
        min_r=self.filter_min_reasons.get()
        coin_filt=self.coin_filter.get()
        sigs=[s for s in self.analysis_signals if s['direction']==side]
        if coin_filt!="Hepsi":
            sigs=[s for s in sigs if s['symbol']==coin_filt]
        if mode=="Teknik":
            sigs=sorted(sigs, key=lambda x: len(x['reasons']), reverse=True)
        elif mode=="Temel":
            def rr_pot(s):
                if not s.get("tps"): return 0
                entry=s['entry']; tp3=s['tps'][-1]
                dist=(tp3-entry) if s['direction']=="LONG" else (entry-tp3)
                atr=s.get("atr") or 0.000001
                return dist/atr
            sigs=sorted(sigs, key=lambda x: rr_pot(x), reverse=True)
        sigs=[s for s in sigs if len(s['reasons'])>=min_r][:ANALYSIS_MAX_ROWS]
        for s in sigs:
            self.create_signal_row(self.analysis_inner, s, True)

    def create_signal_row(self, parent, sig, is_analysis=False):
        bg="#f0fff0" if sig['direction']=="LONG" else "#fff0f0"
        f=tk.Frame(parent, bg=bg, bd=1, relief="groove"); f.pack(fill="x", padx=2, pady=1)
        font7=("Arial",9,"bold")
        tk.Label(f, text=sig['symbol'], font=font7, bg=bg, width=10, anchor="w").pack(side="left")
        tk.Label(f, text=self.live_price(sig['symbol']), font=font7, bg=bg, width=12).pack(side="left")
        pct=self.change_percent(sig['symbol'])
        clr="#006400" if pct!="-" and not pct.startswith("-") else "#8B0000"
        tk.Label(f, text=f"%{pct}", font=font7, bg=bg, fg=clr, width=8).pack(side="left")
        tk.Button(f, text="Detay", font=("Arial",8),
                  command=lambda s=sig: self.show_signal_detail(s)).pack(side="left", padx=2)
        tk.Button(f, text="Test", font=("Arial",8),
                  command=lambda s=sig: self.open_position_from_signal(s)).pack(side="left", padx=2)
        if is_analysis:
            tk.Label(f, text=f"Sebep:{len(sig['reasons'])}", font=("Arial",8), bg=bg).pack(side="left", padx=4)

    ############################################################################
    # FORMAT
    ############################################################################
    def fmt_price(self, p):
        try:
            f=float(p); return f"{f:.6f}" if f<1 else f"{f:.3f}"
        except: return "-"
    def live_price(self, symbol):
        t=self.ticker_map.get(symbol)
        return self.fmt_price(t['lastPrice']) if t else "-"
    def change_percent(self, symbol):
        t=self.ticker_map.get(symbol)
        if not t: return "-"
        try: return f"{float(t['priceChangePercent']):.2f}"
        except: return "-"

    ############################################################################
    # DETAY & POZİSYON
    ############################################################################
    def show_signal_detail(self, s):
        self.detail_title.config(text=f"{s['symbol']} Detay ({s['direction']})")
        vals={
            "Yön": s['direction'],
            "Giriş": self.fmt_price(s['entry']),
            "SL": self.fmt_price(s.get("sl")),
            "Leverage": f"x{s.get('lev',1)}",
            "Reasons": ", ".join(s['reasons']),
            "Timeframe": s.get("timeframe", self.selected_timeframe.get()),
            "ATR": f"{s.get('atr'):.6f}" if s.get('atr') else "-",
            "Test PnL": "-"
        }
        if s.get("tps"):
            for i,tp in enumerate(s['tps'][:3]):
                vals[f"TP{i+1}"]=f"{self.fmt_price(tp)} ({s['tps_yuzde'][i]:.2f} %)"
        rr=[]
        if s.get("atr") and s.get("tps"):
            atr=s['atr']; entry=s['entry']
            for tp in s['tps'][:3]:
                r=(tp-entry)/atr if s['direction']=="LONG" else (entry-tp)/atr
                rr.append(r)
        for i in range(3):
            vals[f"R:R{i+1}"]=f"{rr[i]:.2f}" if i<len(rr) else "-"
        for k,lab in self.detail_labels.items():
            lab.config(text=vals.get(k,"-"))
        self.nb.select(self.tab_detail)
        self.current_detail_signal=s

    def open_current_detail_position(self):
        if not self.current_detail_signal:
            messagebox.showinfo("Bilgi","Önce sinyal seçiniz.")
            return
        amt=simpledialog.askstring("Pozisyon Aç","Kaç USDT ile (margin) test girmek istersiniz?\n(Boş bırak = otomatik risk)")
        override=None
        if amt:
            try:
                val=float(amt)
                if val>0: override=val
                else: messagebox.showinfo("Bilgi","Pozitif değil, otomatik risk kullanılacak.")
            except:
                messagebox.showinfo("Bilgi","Geçersiz sayı, otomatik risk kullanılacak.")
        self.open_position_from_signal(self.current_detail_signal, override_amount_usdt=override)
        self.nb.select(self.tab_positions)

    def open_position_from_signal(self, s, override_amount_usdt=None):
        lp=self.live_price(s['symbol'])
        if lp=="-":
            messagebox.showinfo("Hata","Canlı fiyat yok.")
            return
        try: live=float(lp)
        except: live=s['entry']
        entry=float(s['entry'])
        sl=s.get("sl")
        lev=s.get("lev",5)
        if override_amount_usdt is not None:
            qty = (override_amount_usdt * lev)/entry
            qty_method="Kullanıcı"
        else:
            if sl is not None and abs(entry-sl)>0:
                risk_amount = self.base_equity * RISK_PER_TRADE
                qty = risk_amount / abs(entry-sl)
                qty_method="Risk"
            else:
                qty = (self.base_equity * RISK_PER_TRADE) / (entry*0.01)
                qty_method="Fallback"
        partials=PARTIAL_TP_RATIOS
        if s.get("tps") and len(s["tps"])>=1:
            tot=sum(partials)
            ratios=[p/tot for p in partials]
        else:
            ratios=[1.0,0,0]
        pos={
            "symbol":s['symbol'],
            "direction":s['direction'],
            "entry":entry,
            "lev":lev,
            "sl":sl,
            "tps":s.get("tps", []),
            "open_time":datetime.now().strftime("%H:%M:%S"),
            "status":"OPEN",
            "signal":s,
            "qty":qty,
            "remaining_qty":qty,
            "partials":ratios,
            "next_tp_index":0,
            "realized_pnl":0.0,
            "hit_target":None,
            "qty_method":qty_method
        }
        self.open_positions.append(pos)
        self.log(f"Pozisyon açıldı: {pos['symbol']} {pos['direction']} qty={qty:.4f} entry={entry} SL={sl} yöntem={qty_method}")
        self.safe_ui(self.refresh_positions)
        self.safe_ui(self.recalc_and_update_equity)

    ############################################################################
    # POZİSYON YÖNETİMİ
    ############################################################################
    def refresh_positions(self):
        for c in self.pos_inner.winfo_children(): c.destroy()
        for pos in self.open_positions[-400:]:
            f=tk.Frame(self.pos_inner, bg="#f9fff9", bd=1, relief="groove")
            f.pack(fill="x", padx=2, pady=1)
            font_small=("Arial",POS_ROW_FONT_SIZE,"bold")
            tk.Label(f, text=pos['symbol'], font=font_small, width=7, bg=f["bg"]).pack(side="left")
            tk.Label(f, text=pos['direction'], font=font_small, width=5, bg=f["bg"]).pack(side="left")
            tk.Label(f, text=f"E:{self.fmt_price(pos['entry'])}", font=font_small, width=12, bg=f["bg"]).pack(side="left")
            tk.Label(f, text=f"Qty:{pos['remaining_qty']:.4f}", font=font_small, width=14, bg=f["bg"]).pack(side="left")
            perc, usd, fg = self.calc_unrealized_pnl_detail(pos)
            tk.Label(f, text=f"{perc} {usd}", font=font_small, fg=fg, width=16, bg=f["bg"]).pack(side="left")
            tk.Label(f, text=f"Gerç:{pos['realized_pnl']:.2f}", font=font_small, width=12, bg=f["bg"]).pack(side="left")
            tk.Label(f, text=pos['status'], font=font_small, width=8, bg=f["bg"]).pack(side="left")
            tk.Button(f, text="X", font=font_small,
                      command=lambda p=pos: self.manual_close_position(p)).pack(side="left", padx=2)
        # Scroll alanı güncelle
        self.pos_canvas.configure(scrollregion=self.pos_canvas.bbox("all"))

    def position_auto_update_loop_once(self):
        for pos in self.open_positions:
            if pos["status"]!="OPEN": continue
            lp=self.live_price(pos['symbol'])
            if lp=="-": continue
            try: cur=float(lp)
            except: continue
            entry=pos['entry']; direction=pos['direction']
            sl=pos.get("sl")
            if sl is not None:
                if direction=="LONG" and cur<=sl:
                    self.close_position_full(pos,"SL"); continue
                elif direction=="SHORT" and cur>=sl:
                    self.close_position_full(pos,"SL"); continue
            tps=pos.get("tps",[])
            nidx=pos["next_tp_index"]
            if tps and nidx < len(tps):
                target=tps[nidx]
                hit=False
                if direction=="LONG" and cur>=target: hit=True
                if direction=="SHORT" and cur<=target: hit=True
                if hit:
                    self.partial_close(pos, nidx, cur)
                    if MOVE_SL_TO_BE_AFTER_TP1 and nidx==0 and pos["status"]=="OPEN":
                        old=pos["sl"]; pos["sl"]=entry
                        self.log(f"{pos['symbol']} TP1 sonrası SL BE {old}->{entry}")
                    if ADVANCED_SL_AFTER_TP2 and nidx==1 and pos["status"]=="OPEN":
                        if len(tps)>=1:
                            tp1=tps[0]
                            if direction=="LONG":
                                new_sl=max(pos["sl"] or entry, entry+(tp1-entry)*0.3)
                            else:
                                new_sl=min(pos["sl"] or entry, entry-(entry-tp1)*0.3)
                            pos["sl"]=new_sl
                            self.log(f"{pos['symbol']} TP2 sonrası SL ileri {new_sl}")
        self.refresh_positions()
        self.recalc_and_update_equity()

    def position_auto_update_loop(self):
        self.position_auto_update_loop_once()
        self.after(POSITION_AUTO_UPDATE_INTERVAL*1000, self.position_auto_update_loop)

    def calc_unrealized_pnl_detail(self, pos):
        if pos["status"]!="OPEN": return "-", "-", "black"
        lp=self.live_price(pos['symbol'])
        if lp=="-": return "-", "-", "black"
        try:
            cur=float(lp); entry=pos['entry']; direction=pos['direction']; lev=pos['lev']; rem=pos['remaining_qty']
            if rem<=0: return "0.00%","0.00","black"
            if direction=="LONG":
                pct=((cur-entry)/entry)*100*lev
                usd=(cur-entry)*rem*lev
            else:
                pct=((entry-cur)/entry)*100*lev
                usd=(entry-cur)*rem*lev
            arrow="▲" if pct>=0 else "▼"
            fg="#006400" if pct>=0 else "#8B0000"
            return f"{arrow}{pct:.2f}%", f"{usd:.2f}", fg
        except:
            return "-", "-", "black"

    def partial_close(self, pos, tp_index, price):
        ratio=pos["partials"][tp_index] if tp_index < len(pos["partials"]) else 0
        close_qty=pos["qty"]*ratio
        if close_qty>pos["remaining_qty"]: close_qty=pos["remaining_qty"]
        if close_qty<=0: return
        entry=pos['entry']; direction=pos['direction']; lev=pos['lev']
        pnl_unit = (price-entry) if direction=="LONG" else (entry-price)
        realized = pnl_unit * close_qty * lev
        pos["realized_pnl"] += realized
        self.realized_pnl += realized
        pos["remaining_qty"] -= close_qty
        pos["next_tp_index"] += 1
        self.log(f"{pos['symbol']} {direction} TP{tp_index+1} kısmi qty={close_qty:.4f} realized={realized:.2f}")
        if pos["next_tp_index"] >= len(pos["tps"]) or pos["remaining_qty"]<=0:
            self.close_position_full(pos, f"TP{tp_index+1}_FINAL", already_partial=True)

    def close_position_full(self, pos, reason="MANUAL", already_partial=False):
        if pos["status"]!="OPEN": return
        if (reason.startswith("SL") or reason.startswith("TP")) and not already_partial:
            lp=self.live_price(pos['symbol'])
            if lp!="-":
                try:
                    price=float(lp); entry=pos['entry']; direction=pos['direction']; lev=pos['lev']; rem=pos['remaining_qty']
                    if rem>0:
                        pnl_unit=(price-entry) if direction=="LONG" else (entry-price)
                        realized=pnl_unit*rem*lev
                        pos["realized_pnl"] += realized
                        self.realized_pnl += realized
                except: pass
        pos["status"]="CLOSED"
        pos["hit_target"]=reason
        pos["remaining_qty"]=0
        self.log(f"{pos['symbol']} kapandı: {reason} | Realized:{pos['realized_pnl']:.2f}")
        self.recalc_and_update_equity()

    def manual_close_position(self, pos):
        self.close_position_full(pos,"MANUAL")

    def close_all_positions(self):
        for pos in list(self.open_positions):
            if pos["status"]=="OPEN":
                self.close_position_full(pos,"MANUAL_ALL")
        self.refresh_positions()
        self.recalc_and_update_equity()

    ############################################################################
    # BACKTEST
    ############################################################################
    def backtest_current_signal(self):
        if not self.current_detail_signal:
            messagebox.showinfo("Backtest","Önce bir sinyal seçiniz.")
            return
        sym=self.current_detail_signal['symbol']; tf=self.current_detail_signal['timeframe']
        threading.Thread(target=self.run_backtest, args=(sym,tf), daemon=True).start()

    def run_backtest(self, symbol, timeframe):
        self.log(f"Backtest başladı: {symbol} {timeframe}")
        ccxt_sym=symbol.replace("USDT","/USDT")
        ohlc=fetch_ohlcv_ccxt(self.exchange, ccxt_sym, timeframe, BACKTEST_BARS)
        if not ohlc:
            self.log("Backtest veri alınamadı.")
            self.safe_ui(lambda: messagebox.showinfo("Backtest","Veri alınamadı."))
            return
        total_sigs=0; success=0
        closes=ohlc["close"]; highs=ohlc["high"]; lows=ohlc["low"]
        for i in range(MIN_BARS_FOR_SIGNAL, len(closes)-1):
            sub={k:v[:i+1] for k,v in ohlc.items()}
            sigs=generate_signals(sub, RISK_PARAMS, lev=5)
            if not sigs: continue
            future_end=min(i+1+BACKTEST_LOOKAHEAD, len(closes)-1)
            for s in sigs:
                total_sigs+=1
                entry=s['entry']; sl=s.get("sl"); tps=s.get("tps",[])
                tp1=tps[0] if tps else None
                hit_tp=False; hit_sl=False
                for j in range(i+1, future_end+1):
                    highj=highs[j]; lowj=lows[j]
                    if s['direction']=="LONG":
                        if tp1 and highj>=tp1: hit_tp=True; break
                        if sl is not None and lowj<=sl: hit_sl=True; break
                    else:
                        if tp1 and lowj<=tp1: hit_tp=True; break
                        if sl is not None and highj>=sl: hit_sl=True; break
                if hit_tp and not hit_sl: success+=1
        if total_sigs==0:
            res="Hiç sinyal yok."
        else:
            res=f"Toplam Sinyal: {total_sigs}\nTP1 Başarı: {success} ({(success/total_sigs)*100:.2f} %)"
        self.log(f"Backtest bitti: {symbol} | {res.replace(chr(10),' | ')}")
        self.safe_ui(lambda: self.show_backtest_popup(symbol, timeframe, res))

    def show_backtest_popup(self, symbol, timeframe, text):
        win=tk.Toplevel(self); win.title(f"Backtest - {symbol} {timeframe}")
        tk.Label(win, text=text, font=("Arial",10,"bold"), justify="left").pack(padx=10, pady=10)
        tk.Button(win, text="Kapat", command=win.destroy).pack(pady=6)

    ############################################################################
    # KAPANIŞ
    ############################################################################
    def on_close(self):
        self.stop_event.set()
        self.destroy()

###############################################################################
# MAIN
###############################################################################
if __name__ == "__main__":
    try:
        app=SignalApp()
        app.mainloop()
    except Exception as e:
        print("Uygulama başlatma hatası:", e)
        traceback.print_exc()