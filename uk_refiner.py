"""
uk_refiner.py - 🎩 The Analyst UK-CALIBRATED
Port de la lógica Analyst AI calibrada específicamente para el mercado de Reino Unido.
Build: V3.7 UK-Calibrated
"""

import pandas as pd
import numpy as np
import json

# Buckets sectoriales
DEFENSIVE_SECTORS = {"Consumer Defensive", "Utilities", "Healthcare"}
CYCLICAL_SECTORS = {"Consumer Cyclical", "Industrials", "Basic Materials", "Energy", "Real Estate"}
GROWTH_SECTORS = {"Technology", "Communication Services"}

def sector_bucket(sector: str) -> str:
    """Clasifica sector en bucket"""
    if sector in DEFENSIVE_SECTORS: return "DEFENSIVE"
    if sector in CYCLICAL_SECTORS:  return "CYCLICAL"
    if sector in GROWTH_SECTORS:    return "GROWTH"
    return "OTHER"

def issuer_key(ticker: str) -> str:
    """Normaliza ticker para dedup por emisor (versión UK)"""
    t = ticker.upper()
    if t.endswith(".L"):
        t = t[:-2]
    for suf in ["-A", "-B", "-C", ".A", ".B", ".C"]:
        if t.endswith(suf):
            t = t[: -len(suf)]
    if t in {"FOXA", "FOX"}: return "FOX"
    if t in {"GOOGL", "GOOG"}: return "GOOG"
    return t

def normalize_oracle_df_for_analyst(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Soporta dos formatos:
    - Legacy US: Price, Intrinsic, FCF, Debt, Cash, MarketCap ...
    - Nuevo UK: Price_Local, Intrinsic_Local, FCF_Local, Debt_Local, Cash_Local, MarketCap_Local ...
    Devuelve df con columnas estándar que Analyst AI espera.
    """
    df = df_in.copy()

    # Preservar opcionales
    OPTIONAL_COLS_DEFAULTS = {"AsOf": None, "PxDateUsed": None}
    for c, default in OPTIONAL_COLS_DEFAULTS.items():
        if c not in df.columns:
            df[c] = default

    # Detecta formato UK
    is_uk = ("Price_Local" in df.columns) or ("Intrinsic_Local" in df.columns) or ("FCF_Local" in df.columns)
    if is_uk:
        mapping = {
            "Price": "Price_Local",
            "Intrinsic": "Intrinsic_Local",
            "FCF": "FCF_Local",
            "OCF": "OCF_Local",
            "Capex": "Capex_Local",
            "Debt": "Debt_Local",
            "Cash": "Cash_Local",
            "Equity": "Equity_Local",
            "InvestedCap": "InvestedCap_Local",
            "MarketCap": "MarketCap_Local",
        }
        for legacy_col, uk_col in mapping.items():
            if legacy_col not in df.columns and uk_col in df.columns:
                df[legacy_col] = df[uk_col]

        if "Currency" not in df.columns:
            df["Currency"] = "N/A"
        if "MarketCap_USD" not in df.columns:
            df["MarketCap_USD"] = np.nan
    else:
        if "Currency" not in df.columns:
            df["Currency"] = "N/A"
        if "MarketCap_USD" not in df.columns:
            df["MarketCap_USD"] = np.nan

    return df

def mos_penalty(dtm, tvw):
    """Penalización DTM/TVW más suave (UK)"""
    pen = 0.0
    if not pd.isna(dtm):
        if dtm >= 1.2: pen += 0.04
        elif dtm >= 1.0: pen += 0.02
    if not pd.isna(tvw):
        if tvw >= 0.85: pen += 0.07
        elif tvw >= 0.80: pen += 0.04
    return pen

def analyst_ai_v37_uk_calibrated(df_input: pd.DataFrame, return_all: bool = False) -> pd.DataFrame:
    """
    Versión calibrada para UK
    """
    df = df_input.copy()

    # Normalización numérica
    num_cols = [
        "Price","ROIC","Piotroski","Growth_Est","Terminal_g","Intrinsic","MOS",
        "FCF","Debt","Cash","MarketCap","Debt_to_MCap","FCF_Yield","DCF_TV_Weight",
        "MarketCap_USD"
    ]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").replace([np.inf, -np.inf], np.nan)

    df["Sector"] = df["Sector"].fillna("N/A").astype(str)
    df["Ticker"] = df["Ticker"].astype(str)
    df["Currency"] = df.get("Currency", "N/A")
    df["Currency"] = df["Currency"].fillna("N/A").astype(str)

    # ✅ CFG calibrado UK
    CFG = {
        "MIN_PIO_BUY": 6,
        "MIN_PIO_STRONG": 7,
        "MIN_ROIC_BUY": 0.08,
        "MIN_ROIC_STRONG": 0.10,
        "MAX_TVW_BUY": 0.80,
        "MAX_TVW_STRONG": 0.77,
        "MAX_DTM_BUY": 1.0,
        "MAX_DTM_STRONG": 0.9,
        "MOS_BUY":    {"DEFENSIVE":0.30, "CYCLICAL":0.34, "GROWTH":0.30, "OTHER":0.32},
        "MOS_STRONG": {"DEFENSIVE":0.38, "CYCLICAL":0.42, "GROWTH":0.38, "OTHER":0.40},
        "FCFY_BUY":    {"DEFENSIVE":0.065, "CYCLICAL":0.055, "GROWTH":0.045, "OTHER":0.055},
        "FCFY_STRONG": {"DEFENSIVE":0.080, "CYCLICAL":0.065, "GROWTH":0.055, "OTHER":0.065},
        "UP_BUY": 0.40,
        "UP_STRONG": 0.65,
        "DEF_MAX_GROWTH_EST": 0.10,
        "REQUIRE_POSITIVE_FCF": True,
    }

    out = []
    for _, r in df.iterrows():
        ticker = r["Ticker"]
        sector = r["Sector"]
        bucket = sector_bucket(sector)

        price = r["Price"]
        fair  = r["Intrinsic"]
        roic = r["ROIC"]
        pio  = r["Piotroski"]
        fcf  = r["FCF"]
        fcfy = r["FCF_Yield"]
        dtm  = r["Debt_to_MCap"]
        tvw  = r["DCF_TV_Weight"]
        g_est = r["Growth_Est"]
        t_g   = r["Terminal_g"]
        ccy  = r.get("Currency", "N/A")
        asof = r.get("AsOf", None)
        pxdt = r.get("PxDateUsed", None)

        if sector == "Financial Services":
            if return_all:
                out.append({
                    "Ticker": ticker, "Issuer": issuer_key(ticker), "Sector": sector, "Bucket": bucket,
                    "Currency": ccy, "AsOf": asof, "PxDateUsed": pxdt,
                    "Price": price, "Target_Fair": np.nan, "Upside": np.nan, "Real_MOS": np.nan,
                    "Action": "VALUAR P/B", "Cat": "🏦 Banco/Seguro",
                    "Flags": "DCF_NA",
                    "Why": "Evaluar con P/Book (Sector financiero).",
                    "DCF_TV_Weight": tvw, "Debt_to_MCap": dtm, "FCF_Yield": fcfy, "Piotroski": pio, "ROIC": roic
                })
            continue

        if pd.isna(price) or pd.isna(fair) or price <= 0 or fair <= 0:
            continue

        upside = (fair - price) / price
        real_mos = (fair - price) / fair
        flags = []

        fcf_ok = (not pd.isna(fcf)) and (fcf > 0)
        if CFG["REQUIRE_POSITIVE_FCF"] and (not fcf_ok):
            flags.append("FCF_NEG")

        mos_req_buy    = CFG["MOS_BUY"][bucket]    + mos_penalty(dtm, tvw)
        mos_req_strong = CFG["MOS_STRONG"][bucket] + mos_penalty(dtm, tvw)
        fcfy_req_buy    = CFG["FCFY_BUY"][bucket]
        fcfy_req_strong = CFG["FCFY_STRONG"][bucket]

        defensive_trap = False
        if bucket == "DEFENSIVE":
            if (not pd.isna(g_est)) and (g_est > CFG["DEF_MAX_GROWTH_EST"]):
                defensive_trap = True
                flags.append("DEF_GROWTH_IMPLAUSIBLE")
            if (not pd.isna(pio)) and (pio <= 5):
                defensive_trap = True
                flags.append("DEF_LOW_PIO")
            if (pd.isna(fcfy)) or (fcfy < fcfy_req_buy):
                flags.append("DEF_FCFY_LOW")

        if (not pd.isna(tvw)) and (tvw > 0.85):
            flags.append("TV_HEAVY")

        base_ok_buy = (
            (not pd.isna(pio)) and (pio >= CFG["MIN_PIO_BUY"]) and
            (not pd.isna(roic)) and (roic >= CFG["MIN_ROIC_BUY"]) and
            (not pd.isna(fcfy)) and (fcfy >= fcfy_req_buy) and
            (not pd.isna(dtm)) and (dtm <= CFG["MAX_DTM_BUY"]) and
            (not pd.isna(tvw)) and (tvw <= CFG["MAX_TVW_BUY"]) and
            fcf_ok and (real_mos >= mos_req_buy) and (upside >= CFG["UP_BUY"]) and (not defensive_trap)
        )

        base_ok_strong = (
            (not pd.isna(pio)) and (pio >= CFG["MIN_PIO_STRONG"]) and
            (not pd.isna(roic)) and (roic >= CFG["MIN_ROIC_STRONG"]) and
            (not pd.isna(fcfy)) and (fcfy >= fcfy_req_strong) and
            (not pd.isna(dtm)) and (dtm <= CFG["MAX_DTM_STRONG"]) and
            (not pd.isna(tvw)) and (tvw <= CFG["MAX_TVW_STRONG"]) and
            fcf_ok and (real_mos >= mos_req_strong) and (upside >= CFG["UP_STRONG"]) and (not defensive_trap)
        )

        # Narrative "Why"
        narrative = []
        if upside >= 0.80: narrative.append("descuento muy significativo")
        elif upside >= 0.50: narrative.append("claramente subvaluada")
        elif upside >= 0.30: narrative.append("precio atractivo")
        else: narrative.append("cotización razonable")

        if (not pd.isna(roic)) and roic >= 0.18: narrative.append("alta eficiencia de capital")
        elif (not pd.isna(pio)) and pio >= 8: narrative.append("salud financiera robusta")
        elif (not pd.isna(roic)) and roic >= 0.12: narrative.append("rentabilidad estable")

        if (not pd.isna(dtm)) and dtm <= 0.2: narrative.append("muy bajo nivel de deuda")
        elif (not pd.isna(fcfy)) and fcfy >= 0.08: narrative.append("fuerte generación de caja")

        action, cat = "AVOID", "❌ No pasa filtros"
        why_text = " + ".join(narrative).capitalize() + "."

        if base_ok_strong:
            action, cat = "STRONG BUY", "💎 JOYA REAL"
            final_why = f"Convencimiento alto: {why_text}"
        elif base_ok_buy:
            action, cat = "BUY", "✅ Oportunidad"
            final_why = f"Tesis sólida: {why_text}"
        else:
            if (real_mos >= 0.18) and (upside >= 0.30):
                action, cat = "WATCH", "⚖️ Casi, pero no"
                missing_stuff = []
                if dtm > CFG["MAX_DTM_BUY"]: missing_stuff.append("deuda elevada")
                if roic < CFG["MIN_ROIC_BUY"]: missing_stuff.append("rentabilidad insuficiente")
                if defensive_trap: missing_stuff.append("crecimiento implausible")
                if missing_stuff: final_why = "Atractiva por precio, pero riesgo por " + " y ".join(missing_stuff) + "."
                else: final_why = "Buen precio, pero faltan métricas de calidad."
            else:
                final_why = "No cumple criterios mínimos de seguridad o precio."

        if (not return_all) and (action not in {"STRONG BUY","BUY"}):
            continue

        out.append({
            "Ticker": ticker, "Issuer": issuer_key(ticker), "Sector": sector, "Bucket": bucket, "Currency": ccy,
            "AsOf": asof, "PxDateUsed": pxdt,
            "Price": price, "Target_Fair": fair, "Upside": upside, "Real_MOS": real_mos,
            "Piotroski": pio, "ROIC": roic, "FCF_Yield": fcfy, "Debt_to_MCap": dtm,
            "DCF_TV_Weight": tvw, "Growth_Est": g_est, "Terminal_g": t_g,
            "MarketCap": r.get("MarketCap", np.nan), "MarketCap_USD": r.get("MarketCap_USD", np.nan),
            "Action": action, "Cat": cat, "Flags": ",".join(sorted(set(flags))), "Why": final_why
        })

    res = pd.DataFrame(out)
    if res.empty: return res

    action_rank = {"STRONG BUY": 0, "BUY": 1, "WATCH": 2, "AVOID": 3, "VALUAR P/B": 4}
    res["_ar"] = res["Action"].map(action_rank).fillna(99)
    res = res.sort_values(by=["_ar","Upside"], ascending=[True, False])
    res = res.drop_duplicates(subset=["Issuer"], keep="first").drop(columns=["_ar"])
    return res

def add_exit_plan(df_rec: pd.DataFrame) -> pd.DataFrame:
    if df_rec is None or df_rec.empty: return df_rec
    dfp = df_rec.copy()
    price = pd.to_numeric(dfp["Price"], errors="coerce")
    fair  = pd.to_numeric(dfp["Target_Fair"], errors="coerce")
    tvw   = pd.to_numeric(dfp["DCF_TV_Weight"], errors="coerce")

    tv_penalty = np.where(tvw >= 0.78, 0.90, np.where(tvw >= 0.74, 0.95, 1.00))
    dfp["TV_Penalty"] = tv_penalty
    gap = (fair - price).clip(lower=0)

    conv6 = np.where(dfp["Action"].eq("STRONG BUY"), 0.60, np.where(dfp["Action"].eq("BUY"), 0.45, 0.40))
    conv12 = np.where(dfp["Action"].eq("STRONG BUY"), 0.80, np.where(dfp["Action"].eq("BUY"), 0.65, 0.55))
    dfp["Conv_6M"] = conv6
    dfp["Conv_12M"] = conv12

    tgt6  = price + gap * dfp["Conv_6M"]  * dfp["TV_Penalty"]
    tgt12 = price + gap * dfp["Conv_12M"] * dfp["TV_Penalty"]
    cap6  = np.where(dfp["Action"].eq("STRONG BUY"), 1.20, 0.90)
    cap12 = np.where(dfp["Action"].eq("STRONG BUY"), 1.80, 1.40)

    dfp["Target_6M"]  = np.minimum(tgt6,  price * (1 + cap6))
    dfp["Target_12M"] = np.minimum(tgt12, price * (1 + cap12))
    dfp["Upside_6M"]  = (dfp["Target_6M"]  - price) / price
    dfp["Upside_12M"] = (dfp["Target_12M"] - price) / price
    dfp["Trim_6M"] = price + (dfp["Target_6M"] - price) * 0.70
    stop_pct = np.where(dfp["Action"].eq("STRONG BUY"), 0.12, 0.10)
    dfp["Stop_Price"] = price * (1 - stop_pct)

    cols_front = [
        "Ticker","Issuer","Action","Cat","Bucket","Currency", "AsOf","PxDateUsed",
        "Price","Target_Fair","Target_6M","Target_12M", "Upside","Upside_6M","Upside_12M","Real_MOS",
        "Trim_6M","Stop_Price", "Piotroski","ROIC","FCF_Yield","Debt_to_MCap","DCF_TV_Weight",
        "MarketCap_USD","MarketCap", "Conv_6M","Conv_12M","TV_Penalty", "Flags","Why"
    ]
    cols_front = [c for c in cols_front if c in dfp.columns]
    cols_rest = [c for c in dfp.columns if c not in cols_front]
    return dfp[cols_front + cols_rest]

class UKPortfolioRefiner:
    def __init__(self, data, return_all=False):
        self.raw_data = data
        self.return_all = return_all
        self.df = None
        self.refined_df = None

    def load_data(self):
        if isinstance(self.raw_data, pd.DataFrame):
            self.df = self.raw_data.copy()
        elif isinstance(self.raw_data, dict) and 'results' in self.raw_data:
            self.df = pd.DataFrame(self.raw_data['results'])
        elif isinstance(self.raw_data, list):
            self.df = pd.DataFrame(self.raw_data)
        else:
            return False
        return not self.df.empty

    def refine_all(self):
        if not self.load_data(): return None
        
        # 1. Normalizar
        df_norm = normalize_oracle_df_for_analyst(self.df)
        
        # 1.1 Safety Check
        required = [
            "Ticker","Price","Sector","ROIC","Piotroski","Growth_Est","Terminal_g",
            "Intrinsic","MOS","FCF","Debt","Cash","MarketCap","Debt_to_MCap","FCF_Yield","DCF_TV_Weight"
        ]
        missing = [c for c in required if c not in df_norm.columns]
        if missing:
            print(f"❌ Faltan columnas requeridas: {missing}")
            return None
        
        # 2. Analyst AI UK
        self.refined_df = analyst_ai_v37_uk_calibrated(df_norm, return_all=self.return_all)
        
        # 3. Exit Plan
        if not self.refined_df.empty:
            self.refined_df = add_exit_plan(self.refined_df)
            
        return self.export_to_dict()

    def export_to_dict(self):
        if self.refined_df is None or self.refined_df.empty:
            return {'refined_results': [], 'summary': {'total': 0}}
        
        df_clean = self.refined_df.replace({np.nan: None})
        results = df_clean.to_dict('records')
        
        return {
            'refined_results': results,
            'summary': {
                'total_reviewed': len(self.df),
                'candidates_count': len(results),
                'strong_buys': len(df_clean[df_clean['Action'] == 'STRONG BUY']),
                'buys': len(df_clean[df_clean['Action'] == 'BUY'])
            }
        }
