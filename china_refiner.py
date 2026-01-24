"""
china_refiner.py - 🐉 The Analyst AI V7 (CHINA FULL)
Versión completa adaptada para el mercado de China.
Filtros por riesgo geopolítico, normalización de moneda y plan de salida.
"""

import pandas as pd
import numpy as np
import json

def normalize_china_to_analyst(df_in: pd.DataFrame) -> pd.DataFrame:
    """Adapta las columnas de China al formato estándar Analyst AI."""
    df = df_in.copy()

    mapping = {
        "Price_Local": "Price",
        "Intrinsic_Local": "Intrinsic",
    }
    for china_col, std_col in mapping.items():
        if china_col in df.columns:
            df[std_col] = df[china_col]

    # Rellenar faltantes técnicos con NaN para evitar errores
    for col in ["Growth_Est", "Terminal_g", "FCF", "Debt", "Cash", "Debt_to_MCap", "DCF_TV_Weight", "FCF_Yield"]:
        if col not in df.columns:
            df[col] = np.nan

    if "MarketCap_USD" in df.columns:
        df["MarketCap"] = df["MarketCap_USD"]

    return df

def analyst_ai_v37_china_full(df_input: pd.DataFrame, return_all: bool = False) -> pd.DataFrame:
    required_cols = ["Ticker", "Price", "Intrinsic", "MOS", "ROIC"]
    missing = [c for c in required_cols if c not in df_input.columns]
    if missing:
        return pd.DataFrame()

    df = df_input.copy()

    # Normalización
    num_cols = ["Price", "ROIC", "Piotroski", "Intrinsic", "MOS", "MarketCap", "FCF_Yield", "Debt_to_MCap", "DCF_TV_Weight"]
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df["Sector"] = df["Sector"].fillna("N/A").astype(str)
    df["Ticker"] = df["Ticker"].astype(str)
    df["Currency"] = df.get("Currency", "USD")
    df["Currency"] = df["Currency"].fillna("USD").astype(str)

    # Buckets sectoriales
    DEFENSIVE = {"Consumer Defensive","Utilities","Healthcare"}
    CYCLICAL  = {"Consumer Cyclical","Industrials","Basic Materials","Energy","Real Estate", "Financial Services"}
    GROWTH    = {"Technology","Communication Services"}

    def sector_bucket(sector: str) -> str:
        if sector in DEFENSIVE: return "DEFENSIVE"
        if sector in CYCLICAL:  return "CYCLICAL"
        if sector in GROWTH:    return "GROWTH"
        return "OTHER"

    def issuer_key(ticker: str) -> str:
        return ticker.split('.')[0]

    # Configuración China (Calibrated)
    CFG = {
        "MIN_PIO_BUY": 5,
        "MIN_ROIC_BUY": 0.08,
        "MOS_BUY": 0.20,      # 20% descuento mínimo
        "MOS_STRONG": 0.35,   # 35% descuento joya
    }

    out = []
    for _, r in df.iterrows():
        ticker = r["Ticker"]
        sector = r["Sector"]
        bucket = sector_bucket(sector)
        ccy    = r["Currency"]
        price  = r["Price"]
        fair   = r["Intrinsic"]

        # Datos opcionales
        roic = r.get("ROIC", 0)
        pio  = r.get("Piotroski", 0)
        fcfy = r.get("FCF_Yield", 0)
        dtm  = r.get("Debt_to_MCap", 0)
        tvw  = r.get("DCF_TV_Weight", 0.7)

        if pd.isna(price) or pd.isna(fair) or price <= 0 or fair <= 0:
            continue

        upside = (fair - price) / price
        real_mos = r.get("MOS", 0)

        flags = []
        if dtm > 0.8: flags.append("HIGH_DEBT")
        if tvw > 0.85: flags.append("TV_HEAVY")

        # Selección
        quality_ok = (roic >= CFG["MIN_ROIC_BUY"]) and (pio >= CFG["MIN_PIO_BUY"])
        mos_ok = (real_mos >= CFG["MOS_BUY"])

        action = "AVOID"
        cat = "❌ Riesgo/Caro"

        # Lógica China (Más enfocada en MOS profundo por riesgo geopolítico)
        is_strong = (roic >= 0.12) and (real_mos >= CFG["MOS_STRONG"])
        is_buy    = quality_ok and mos_ok

        if is_strong:
            action, cat = "STRONG BUY", "💎 JOYA DRAGÓN"
        elif is_buy:
            action, cat = "BUY", "✅ Oportunidad"
        elif quality_ok and real_mos > 0.10:
            action, cat = "WATCH", "⚖️ En radar"

        if (not return_all) and (action not in {"STRONG BUY", "BUY"}):
            continue

        # Why generator
        narrative = []
        if upside >= 0.80: narrative.append("descuento masivo")
        elif upside >= 0.40: narrative.append("subvaluación profunda")
        else: narrative.append("precio atractivo")

        if roic >= 0.15: narrative.append("alta rentabilidad (ROIC)")
        if pio >= 7: narrative.append("fundamentales sólidos")

        if "HK" in ticker: narrative.append("mercado Hong Kong")
        elif "SS" in ticker or "SZ" in ticker: narrative.append("A-Share Mainland")

        why_text = " + ".join(narrative).capitalize()
        final_why = f"Tesis China: {why_text}."

        out.append({
            "Ticker": ticker,
            "Issuer": issuer_key(ticker),
            "Sector": sector,
            "Bucket": bucket,
            "Currency": ccy,
            "Price": price,
            "Target_Fair": fair,
            "Upside": upside,
            "Real_MOS": real_mos,
            "Piotroski": pio,
            "ROIC": roic,
            "FCF_Yield": fcfy,
            "Debt_to_MCap": dtm,
            "DCF_TV_Weight": tvw,
            "Action": action,
            "Cat": cat,
            "Flags": ",".join(flags),
            "Why": final_why
        })

    res = pd.DataFrame(out)
    if res.empty: return res

    action_rank = {"STRONG BUY": 0, "BUY": 1, "WATCH": 2}
    res["_ar"] = res["Action"].map(action_rank).fillna(99)
    res = res.sort_values(by=["_ar","Real_MOS"], ascending=[True, False]).drop(columns=["_ar"])
    return res

def add_exit_plan_china_full(df_rec: pd.DataFrame) -> pd.DataFrame:
    if df_rec is None or df_rec.empty: return df_rec
    dfp = df_rec.copy()

    price = dfp["Price"]
    fair  = dfp["Target_Fair"]
    tvw   = dfp["DCF_TV_Weight"].fillna(0.75)

    tv_penalty = np.where(tvw >= 0.80, 0.90, 1.00)
    dfp["TV_Penalty"] = tv_penalty
    gap = (fair - price).clip(lower=0)

    conv6  = np.where(dfp["Action"] == "STRONG BUY", 0.35, 0.25)
    conv12 = np.where(dfp["Action"] == "STRONG BUY", 0.60, 0.45)

    dfp["Conv_6M"] = conv6
    dfp["Conv_12M"] = conv12

    tgt6  = price + gap * dfp["Conv_6M"] * dfp["TV_Penalty"]
    tgt12 = price + gap * dfp["Conv_12M"] * dfp["TV_Penalty"]

    dfp["Target_6M"]  = tgt6
    dfp["Target_12M"] = tgt12
    dfp["Upside_6M"]  = (tgt6 - price) / price
    dfp["Upside_12M"] = (tgt12 - price) / price
    dfp["Trim_6M"] = price + (tgt6 - price) * 0.70
    stop_pct = np.where(dfp["Action"] == "STRONG BUY", 0.18, 0.15)
    dfp["Stop_Price"] = price * (1 - stop_pct)

    return dfp

class ChinaPortfolioRefiner:
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
        df_norm = normalize_china_to_analyst(self.df)
        
        # 2. Analyst AI China
        self.refined_df = analyst_ai_v37_china_full(df_norm, return_all=self.return_all)
        
        # 3. Exit Plan
        if not self.refined_df.empty:
            self.refined_df = add_exit_plan_china_full(self.refined_df)
            
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
