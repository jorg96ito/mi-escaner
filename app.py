import streamlit as st
import requests
from scipy.stats import poisson, nbinom
from datetime import datetime, timedelta
import pandas as pd
import re
import time
import math
import os

# ---------------------------------------------------------
# 1. CONFIGURACIÓN E INFRAESTRUCTURA
# ---------------------------------------------------------
st.set_page_config(page_title="Quant Pro V18.2 | Data Extractor + Stake", layout="wide")

API_KEY_FOOTBALL = "08edd9f31ef5d32739e7d7acb5740f57"  # ⚠️ Tu clave de fútbol
HEADERS = {'x-apisports-key': API_KEY_FOOTBALL}
BANKROLL_INICIAL = 1000.0
APUESTA_MINIMA_EUROS = 0.20
ITEMS_POR_PAGINA = 10

# EXPANSIÓN MUNDIAL: 60+ Ligas Domésticas + Regionalligas Alemanas
PAISES_LIGAS = {
    "Inglaterra": {"Premier League": 39, "Championship": 40, "League One": 41, "League Two": 42, "National League": 43},
    "España": {"LaLiga": 140, "LaLiga 2": 141, "Primera RFEF": 435, "Liga Femenina": 142},
    "Italia": {"Serie A": 135, "Serie B": 136, "Serie C": 137},
    "Alemania": {"1. Bundesliga": 78, "2. Bundesliga": 79, "3. Liga": 80, "Reg. Nord": 81, "Reg. Nordost": 82, "Reg. West": 83, "Reg. Südwest": 84, "Reg. Bayern": 85},
    "Francia": {"Ligue 1": 61, "Ligue 2": 62, "National": 63},
    "Paises Bajos": {"Eredivisie": 88, "Eerste Divisie": 89},
    "Portugal": {"Primeira Liga": 94, "Liga Portugal 2": 95},
    "Bélgica": {"Jupiler Pro League": 144, "Challenger Pro": 145},
    "Escocia": {"Premiership": 179, "Championship": 180},
    "Turquía": {"Süper Lig": 203, "1. Lig": 204},
    "Grecia": {"Super League 1": 197},
    "Suiza": {"Super League": 207, "Challenge League": 208},
    "Austria": {"Bundesliga": 218, "2. Liga": 219},
    "Dinamarca": {"Superliga": 119, "1st Division": 120},
    "Suecia": {"Allsvenskan": 113, "Superettan": 114},
    "Noruega": {"Eliteserien": 103, "Obos-Ligaen": 104},
    "Polonia": {"Ekstraklasa": 106, "I Liga": 107},
    "Rumanía": {"Liga I": 283},
    "Croacia": {"HNL": 210},
    "Serbia": {"Super Liga": 288},
    "República Checa": {"First League": 345},
    "Brasil": {"Serie A": 71, "Serie B": 72},
    "Argentina": {"Liga Profesional": 128, "Primera Nacional": 131},
    "EEUU": {"MLS": 253, "USL Championship": 255},
    "México": {"Liga MX": 262, "Liga de Expansión": 263},
    "Colombia": {"Primera A": 239},
    "Chile": {"Primera División": 265},
    "Uruguay": {"Primera División": 268},
    "Perú": {"Liga 1": 281},
    "Ecuador": {"Liga Pro": 242},
    "Japón": {"J1 League": 98, "J2 League": 99},
    "Corea del Sur": {"K League 1": 292},
    "Arabia Saudita": {"Pro League": 307},
    "Australia": {"A-League": 188}
}

LIGAS_IDS_ACTIVAS = [id for pais in PAISES_LIGAS.values() for id in pais.values()]

# ---------------------------------------------------------
# 2. SISTEMA DE TRACKING Y MEMORIA
# ---------------------------------------------------------
TRACKER_FILE = "tracking_apuestas.csv"

def init_tracker():
    if not os.path.exists(TRACKER_FILE):
        df = pd.DataFrame(columns=["Fecha", "Fixture_ID", "Partido", "Mercado", "Cuota", "Stake_Eur", "Prob_Modelo", "Estado", "PnL"])
        df.to_csv(TRACKER_FILE, index=False)

def guardar_pick(fixture_id, partido, mercado, cuota, stake, prob):
    df = pd.read_csv(TRACKER_FILE)
    nuevo = pd.DataFrame([{
        "Fecha": datetime.now().strftime("%Y-%m-%d"),
        "Fixture_ID": str(fixture_id), "Partido": partido, "Mercado": mercado, 
        "Cuota": cuota, "Stake_Eur": stake, "Prob_Modelo": prob, "Estado": "Pendiente", "PnL": 0.0
    }])
    df = pd.concat([df, nuevo], ignore_index=True)
    df.to_csv(TRACKER_FILE, index=False)
    st.toast(f"✅ Pick guardado: {partido} - {mercado}")

def obtener_picks_historicos():
    init_tracker()
    try:
        df = pd.read_csv(TRACKER_FILE)
        if df.empty: return set()
        historico = set()
        for _, row in df.iterrows():
            try: fid = str(int(float(row["Fixture_ID"])))
            except: fid = str(row["Fixture_ID"]).strip()
            merc = str(row["Mercado"]).strip()
            historico.add(f"{fid}_{merc}")
        return historico
    except: return set()

def calcular_bankroll_actual():
    init_tracker()
    df = pd.read_csv(TRACKER_FILE)
    return BANKROLL_INICIAL + df["PnL"].sum()

def auto_resolver_apuestas():
    df = pd.read_csv(TRACKER_FILE)
    pendientes = df[df["Estado"] == "Pendiente"]
    if pendientes.empty: return 0
        
    resueltas_hoy = 0
    for idx, row in pendientes.iterrows():
        try: fid_limpio = int(float(row['Fixture_ID']))
        except: fid_limpio = row['Fixture_ID']
            
        url = f"https://v3.football.api-sports.io/fixtures?id={fid_limpio}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=5).json()
            if not res.get("response"): continue
            
            fixture_data = res["response"][0]
            status = fixture_data["fixture"]["status"]["short"]
            
            if status in ["FT", "AET", "PEN"]:
                goles_l = fixture_data["goals"]["home"]
                goles_v = fixture_data["goals"]["away"]
                mercado = row["Mercado"]
                cuota = row["Cuota"]
                stake = row["Stake_Eur"]
                
                if mercado in ["Local (1)", "Empate (X)", "Visitante (2)", "Over 2.5 Goles", "Ambos Marcan (Sí)"]:
                    ganada = False
                    if mercado == "Local (1)": ganada = (goles_l > goles_v)
                    elif mercado == "Empate (X)": ganada = (goles_l == goles_v)
                    elif mercado == "Visitante (2)": ganada = (goles_l < goles_v)
                    elif mercado == "Over 2.5 Goles": ganada = ((goles_l + goles_v) > 2.5)
                    elif mercado == "Ambos Marcan (Sí)": ganada = (goles_l > 0 and goles_v > 0)
                    
                    df.at[idx, "Estado"] = "Ganada" if ganada else "Perdida"
                    df.at[idx, "PnL"] = round((stake * cuota) - stake, 2) if ganada else -stake
                    resueltas_hoy += 1
                time.sleep(0.3) 
        except: pass
    df.to_csv(TRACKER_FILE, index=False)
    return resueltas_hoy

# ---------------------------------------------------------
# 3. MOTORES MATEMÁTICOS AFINADOS
# ---------------------------------------------------------
def limpiar_nombre(texto): 
    return re.sub(r'\b(fc|cf|ud|sd|cd|real|1\.)\b', '', (texto or "").lower()).strip()

def calcular_momentum_ema(form_str, alpha=0.65):
    if not form_str: return 1.0
    pesos = {'W': 1.25, 'D': 1.00, 'L': 0.75}
    score, peso_total = 0.0, 0.0
    historial = list(form_str[-5:]) if len(form_str) >= 5 else list(form_str)
    for i, res in enumerate(reversed(historial)):
        decay = alpha ** i
        score += pesos.get(res, 1.0) * decay
        peso_total += decay
    return score / peso_total if peso_total > 0 else 1.0

def desviggar_cuotas_power_method(cuotas_dict, keys):
    if not all(k in cuotas_dict for k in keys): return {}
    inv_odds = [1.0 / cuotas_dict[k] for k in keys]
    margin = sum(inv_odds) - 1.0
    if margin <= 0: return {f"TrueProb_{k}": p for k, p in zip(keys, inv_odds)}
        
    low, high = 0.5, 1.5 
    for _ in range(25): 
        mid = (low + high) / 2.0
        if sum(math.pow(p, mid) for p in inv_odds) > 1.0: low = mid
        else: high = mid
            
    n = (low + high) / 2.0
    cuotas_reales = {}
    for k in keys:
        true_p = math.pow(1.0 / cuotas_dict[k], n)
        cuotas_reales[f"TrueProb_{k}"] = true_p
        cuotas_reales[f"TrueOdd_{k}"] = 1.0 / true_p if true_p > 0 else 0
    return cuotas_reales

@st.cache_data(ttl=3600)
def obtener_fuerzas_liga(league_id):
    temp = datetime.now().year if datetime.now().month >= 7 else datetime.now().year - 1
    url = f"https://v3.football.api-sports.io/standings?league={league_id}&season={temp}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=8).json()
        if not res.get("response"): return {}, {}
        standings = res["response"][0]["league"]["standings"][0]
        pj_loc = sum(t["home"]["played"] for t in standings)
        if pj_loc == 0: return {}, {}
        
        avg_g_loc = max(0.1, sum(t["home"]["goals"]["for"] for t in standings) / pj_loc)
        avg_g_vis = max(0.1, sum(t["away"]["goals"]["for"] for t in standings) / sum(t["away"]["played"] for t in standings))
        
        stats_eq = {}
        K = 5.0 

        for t in standings:
            nom = limpiar_nombre(t["team"]["name"])
            mom = calcular_momentum_ema(t.get("form", ""))
            
            hl_pj, hl_gf, hl_gc = t["home"]["played"], t["home"]["goals"]["for"], t["home"]["goals"]["against"]
            aw_pj, aw_gf, aw_gc = t["away"]["played"], t["away"]["goals"]["for"], t["away"]["goals"]["against"]
            
            fa_l = (((hl_gf + K * avg_g_loc) / (hl_pj + K)) / avg_g_loc) * mom
            fd_l = (((hl_gc + K * avg_g_vis) / (hl_pj + K)) / avg_g_vis) / mom
            fa_v = (((aw_gf + K * avg_g_vis) / (aw_pj + K)) / avg_g_vis) * mom
            fd_v = (((aw_gc + K * avg_g_loc) / (aw_pj + K)) / avg_g_loc) / mom
            
            stats_eq[nom] = {"FA_H": fa_l, "FD_H": fd_l, "FA_A": fa_v, "FD_A": fd_v}
        return stats_eq, {"avg_home": avg_g_loc, "avg_away": avg_g_vis}
    except: return {}, {}

def ajuste_dixon_coles(x, y, l_l, l_v):
    rho = -0.13
    if x == 0 and y == 0: return max(0.0, 1.0 - l_l * l_v * rho)
    if x == 0 and y == 1: return max(0.0, 1.0 + l_l * rho)
    if x == 1 and y == 0: return max(0.0, 1.0 + l_v * rho)
    if x == 1 and y == 1: return max(0.0, 1.0 - rho)
    return 1.0

def calcular_mercados(xg_l, xg_v):
    p_1, p_x, p_2, p_ov25, p_btts = 0.0, 0.0, 0.0, 0.0, 0.0
    for g_l in range(10):
        for g_v in range(10):
            p_base = poisson.pmf(g_l, xg_l) * poisson.pmf(g_v, xg_v)
            p_ex = p_base * ajuste_dixon_coles(g_l, g_v, xg_l, xg_v)
            
            if g_l > g_v: p_1 += p_ex
            elif g_l == g_v: p_x += p_ex
            else: p_2 += p_ex
            if (g_l + g_v) > 2.5: p_ov25 += p_ex
            if g_l > 0 and g_v > 0: p_btts += p_ex
            
    t = p_1 + p_x + p_2
    if t == 0: return {'1': 0.33, 'X': 0.34, '2': 0.33}, 0.5, 0.5
    return {'1': p_1/t, 'X': p_x/t, '2': p_2/t}, p_ov25/t, p_btts/t

def calcular_corners_y_tarjetas(xg_l, xg_v, prob_1x2, ritmo_partido):
    xg_total = (xg_l + xg_v) 
    exp_corners = 7.5 + (xg_total * 0.85) 
    if prob_1x2['1'] > 0.65 or prob_1x2['2'] > 0.65: exp_corners *= 1.05 
        
    v = exp_corners + (0.05 * exp_corners**2)
    n = (exp_corners**2) / (v - exp_corners)
    p_nbinom = exp_corners / v
    p_ov95c = 1.0 - nbinom.cdf(9, n, p_nbinom) if exp_corners < v else 0.5

    tension = 1.0 - abs(prob_1x2['1'] - prob_1x2['2'])
    exp_tarjetas = (3.0 + (tension * 2.5)) * ritmo_partido
    p_ov45t = 1.0 - poisson.cdf(4, exp_tarjetas)
    return p_ov95c, p_ov45t

def obtener_cuotas_partido(fixture_id):
    url = f"https://v3.football.api-sports.io/odds?fixture={fixture_id}&bookmaker=8"
    try:
        res = requests.get(url, headers=HEADERS, timeout=4).json()
        cuotas = {}
        if res.get("response"):
            for market in res["response"][0]["bookmakers"][0]["bets"]:
                if market["name"] == "Match Winner":
                    for val in market["values"]:
                        if val["value"] == "Home": cuotas["1"] = float(val["odd"])
                        elif val["value"] == "Draw": cuotas["X"] = float(val["odd"])
                        elif val["value"] == "Away": cuotas["2"] = float(val["odd"])
                elif market["name"] == "Goals Over/Under":
                    for val in market["values"]:
                        if val["value"] == "Over 2.5": cuotas["O25"] = float(val["odd"])
                elif market["name"] == "Both Teams Score":
                    for val in market["values"]:
                        if val["value"] == "Yes": cuotas["BTTS"] = float(val["odd"])
                elif "Corners Over Under" in market["name"] or "Corners" in market["name"]:
                    for val in market["values"]:
                        if "Over 9.5" in str(val["value"]): cuotas["O95C"] = float(val["odd"])
                elif "Cards Over/Under" in market["name"] or "Cards" in market["name"]:
                    for val in market["values"]:
                        if "Over 4.5" in str(val["value"]): cuotas["O45T"] = float(val["odd"])
        return cuotas
    except: return {}

@st.cache_data(ttl=1800)
def cargar_datos_jornada(fecha):
    url = f"https://v3.football.api-sports.io/fixtures?date={fecha}&timezone=Europe/Madrid"
    try:
        res = requests.get(url, headers=HEADERS).json()
        return [p for p in res.get("response", []) if p["league"]["id"] in LIGAS_IDS_ACTIVAS]
    except: return []

@st.cache_data(ttl=1800)
def cargar_proxima_jornada_liga(league_id):
    url = f"https://v3.football.api-sports.io/fixtures?league={league_id}&next=10&timezone=Europe/Madrid"
    try:
        return requests.get(url, headers=HEADERS).json().get("response", [])
    except: return []

# ---------------------------------------------------------
# 4. INTERFAZ GRÁFICA Y GENERADOR DE DATOS CRUDOS
# ---------------------------------------------------------
bankroll_actual = calcular_bankroll_actual()

st.sidebar.markdown(f"### 🏦 Bankroll: **€{bankroll_actual:.2f}**")
st.sidebar.caption("Se actualiza automáticamente al resolver partidos.")
modo_vista = st.sidebar.radio("Navegación", ["1️⃣ Escáner General (Jornada)", "2️⃣ Explorador de Ligas", "3️⃣ Mi Cartera (Resultados)"])

st.sidebar.markdown("---")
st.sidebar.header("🌍 Explorador de Ligas")
pais_sel = st.sidebar.selectbox("País", list(PAISES_LIGAS.keys()))
liga_sel = st.sidebar.selectbox("Liga", list(PAISES_LIGAS[pais_sel].keys()))
id_liga_explorador = PAISES_LIGAS[pais_sel][liga_sel]

if modo_vista == "1️⃣ Escáner General (Jornada)":
    st.title("🤖 Escáner Cuantitativo & Extractor Data")
    
    dias = {"Hoy": 0, "Mañana": 1, "Pasado": 2}
    c_dia, c_riesgo, c_orden, c_btn = st.columns([1, 1.2, 1.3, 1])
    dia_sel = c_dia.selectbox("Día", list(dias.keys()))
    max_exposure = c_riesgo.slider("Riesgo Máx Carter(%)", 2, 20, 10)
    
    def reset_pagina(): st.session_state.pagina_actual = 1
    criterio_orden = c_orden.selectbox("Escanear por:", ["💰 Importe (EV+)", "📊 Probabilidad (%)"], on_change=reset_pagina)
    
    fecha_calc = (datetime.now() + timedelta(days=dias[dia_sel])).strftime("%Y-%m-%d")
    
    if 'raw_picks' not in st.session_state: st.session_state.raw_picks = None
    if 'pagina_actual' not in st.session_state: st.session_state.pagina_actual = 1

    if c_btn.button("🔄 Ejecutar Escáner"):
        st.session_state.pagina_actual = 1 
        partidos = cargar_datos_jornada(fecha_calc)
        if not partidos:
            st.info("No hay partidos programados en las más de 60 ligas configuradas para este día.")
            st.session_state.raw_picks = [] 
        else:
            ligas_activas = list(set([p["league"]["id"] for p in partidos]))
            stats_liga, medias_liga = {}, {}
            
            with st.spinner(f"Evaluando {len(partidos)} partidos alrededor del mundo..."):
                for lid in ligas_activas:
                    s, m = obtener_fuerzas_liga(lid)
                    stats_liga[lid], medias_liga[lid] = s, m

            raw_picks_temp = []
            bar = st.progress(0)
            
            for i, p in enumerate(partidos):
                f_id = p["fixture"]["id"]
                lid = p["league"]["id"]
                loc, vis = p["teams"]["home"]["name"], p["teams"]["away"]["name"]
                
                # Datos para la exportación comercial
                liga_nombre = p["league"]["name"]
                pais_nombre = p["league"]["country"]
                
                try:
                    dt = datetime.fromisoformat(p["fixture"]["date"].replace("Z", "+00:00"))
                    fecha_hora_str = dt.strftime("%d/%m/%Y %H:%M")
                except:
                    fecha_hora_str = p["fixture"]["date"]
                
                sl = stats_liga.get(lid, {}).get(limpiar_nombre(loc), {"FA_H": 1.0, "FD_H": 1.0})
                sv = stats_liga.get(lid, {}).get(limpiar_nombre(vis), {"FA_A": 1.0, "FD_A": 1.0})
                ritmo_partido = 1.0 + ((sl["FA_H"] + sv["FA_A"] - 2.0) * 0.15)
                
                xG_loc = sl["FA_H"] * sv["FD_A"] * medias_liga.get(lid, {}).get("avg_home", 1.5) * ritmo_partido
                xG_vis = sv["FA_A"] * sl["FD_H"] * medias_liga.get(lid, {}).get("avg_away", 1.2) * ritmo_partido
                
                prob_1x2, p_ov25, p_btts = calcular_mercados(xG_loc, xG_vis)
                p_ov95c, p_ov45t = calcular_corners_y_tarjetas(xG_loc, xG_vis, prob_1x2, ritmo_partido)
                cuotas = obtener_cuotas_partido(f_id)
                
                cuotas_desviggadas = desviggar_cuotas_power_method(cuotas, ["1", "X", "2"])
                
                mercados = [
                    ("Local (1)", prob_1x2['1'], cuotas.get("1", 0), cuotas_desviggadas.get("TrueProb_1", 0)),
                    ("Empate (X)", prob_1x2['X'], cuotas.get("X", 0), cuotas_desviggadas.get("TrueProb_X", 0)),
                    ("Visitante (2)", prob_1x2['2'], cuotas.get("2", 0), cuotas_desviggadas.get("TrueProb_2", 0)),
                    ("Over 2.5 Goles", p_ov25, cuotas.get("O25", 0), 0),
                    ("Ambos Marcan (Sí)", p_btts, cuotas.get("BTTS", 0), 0),
                    ("Over 9.5 Córners", p_ov95c, cuotas.get("O95C", 0), 0),
                    ("Over 4.5 Tarjetas", p_ov45t, cuotas.get("O45T", 0), 0)
                ]

                for n_merc, p_real, cuota, p_real_casa in mercados:
                    if cuota > 1.20:
                        ev = (p_real * cuota) - 1
                        ev_valido = True
                        if p_real_casa > 0 and (p_real - p_real_casa) < 0.005:
                            ev_valido = False
                            
                        tiene_valor = (ev > 0.025 and ev_valido)
                        
                        if tiene_valor or p_real >= 0.65:
                            raw_picks_temp.append({
                                "f_id": f_id, "Partido": f"{loc} vs {vis}", "Mercado": n_merc,
                                "Prob": p_real, "Cuota": cuota, "EV": ev, "Tiene_Valor": tiene_valor,
                                "Liga": liga_nombre, "Pais": pais_nombre, "Fecha_Hora": fecha_hora_str,
                                "xG_loc": xG_loc, "xG_vis": xG_vis,
                                "FA_H": sl["FA_H"], "FD_H": sl["FD_H"], 
                                "FA_A": sv["FA_A"], "FD_A": sv["FD_A"]
                            })
                bar.progress((i+1)/len(partidos))
            bar.empty()
            st.session_state.raw_picks = raw_picks_temp

    if st.session_state.raw_picks is not None:
        raw_picks = st.session_state.raw_picks
        picks_finales = []
        
        if raw_picks:
            for p in raw_picks:
                if p["Tiene_Valor"]:
                    b = p["Cuota"] - 1.0
                    p["Raw_Kelly"] = max(0.0, ((b * p["Prob"] - (1.0 - p["Prob"])) / b)) * 0.15
                else:
                    p["Raw_Kelly"] = 0.0

            suma_k = sum(p["Raw_Kelly"] for p in raw_picks if p["Tiene_Valor"]) * 100
            ajuste = (max_exposure / suma_k) if suma_k > max_exposure else 1.0
            
            for p in raw_picks:
                if p["Tiene_Valor"]:
                    stake_pct = (p["Raw_Kelly"] * 100) * ajuste
                    stake_eur = (stake_pct / 100) * bankroll_actual
                    
                    # NUEVO: Cálculo cauto de Stake 1-10 basado en el Fractional Kelly
                    stake_1_10 = int(max(1, min(10, round(stake_pct * 2))))
                    p["Stake_1_10"] = stake_1_10
                else:
                    stake_eur = 0.0
                    p["Stake_1_10"] = 1
                
                if criterio_orden == "💰 Importe (EV+)":
                    if p["Tiene_Valor"] and stake_eur >= APUESTA_MINIMA_EUROS:
                        p["Stake_Eur"] = stake_eur
                        picks_finales.append(p)
                else:
                    if p["Prob"] >= 0.65:
                        p["Stake_Eur"] = stake_eur
                        picks_finales.append(p)
            
            if criterio_orden == "💰 Importe (EV+)":
                picks_ordenados = sorted(picks_finales, key=lambda x: x["Stake_Eur"], reverse=True)
                mensaje_exito = f"Se han filtrado {len(picks_ordenados)} picks de Valor Real."
            else:
                picks_ordenados = sorted(picks_finales, key=lambda x: x["Prob"], reverse=True)
                mensaje_exito = f"Mostrando {len(picks_ordenados)} selecciones de alta probabilidad."

            if picks_ordenados:
                st.success(mensaje_exito)
                
                total_paginas = math.ceil(len(picks_ordenados) / ITEMS_POR_PAGINA)
                
                if total_paginas > 1:
                    cp1, cp2, cp3 = st.columns([1, 2, 1])
                    if cp1.button("⬅️ Anterior") and st.session_state.pagina_actual > 1:
                        st.session_state.pagina_actual -= 1
                        st.rerun()
                        
                    cp2.markdown(f"<div style='text-align: center;'><b>Página {st.session_state.pagina_actual} de {total_paginas}</b></div>", unsafe_allow_html=True)
                    
                    if cp3.button("Siguiente ➡️") and st.session_state.pagina_actual < total_paginas:
                        st.session_state.pagina_actual += 1
                        st.rerun()
                        
                st.divider()
                
                inicio_idx = (st.session_state.pagina_actual - 1) * ITEMS_POR_PAGINA
                fin_idx = inicio_idx + ITEMS_POR_PAGINA
                picks_pagina = picks_ordenados[inicio_idx:fin_idx]
                
                picks_historicos = obtener_picks_historicos()
                if 'picks_registrados' not in st.session_state: st.session_state.picks_registrados = set()
                
                def registrar_accion(f_id, partido, mercado, cuota, stake, prob, key_interna):
                    guardar_pick(f_id, partido, mercado, cuota, stake, prob)
                    st.session_state.picks_registrados.add(key_interna)

                for idx, pick in enumerate(picks_pagina, start=inicio_idx+1):
                    with st.container():
                        cc1, cc2, cc3, cc4, cc5 = st.columns([3, 2, 1.5, 2, 1.5])
                        cc1.write(f"⚽ **{pick['Partido']}**")
                        cc2.write(f"🎯 **{pick['Mercado']}** (Cuota: {pick['Cuota']})")
                        cc3.write(f"📊 Prob: **{pick['Prob']*100:.1f}%**")
                        
                        pick_key_ui = f"{pick['f_id']}_{pick['Mercado']}_{idx}"
                        pick_id_real = f"{str(pick['f_id']).strip()}_{str(pick['Mercado']).strip()}"
                        
                        ya_registrado = (pick_id_real in picks_historicos) or (pick_key_ui in st.session_state.picks_registrados)

                        if pick['Tiene_Valor'] and pick['Stake_Eur'] >= APUESTA_MINIMA_EUROS:
                            cc4.write(f"💰 Apostar: **€{pick['Stake_Eur']:.2f}**")
                            
                            if ya_registrado:
                                cc5.button("✅ Guardado", key=f"btn_{pick_key_ui}", disabled=True)
                            else:
                                cc5.button("Registrar Pick", key=f"btn_{pick_key_ui}", 
                                           on_click=registrar_accion, 
                                           args=(pick['f_id'], pick['Partido'], pick['Mercado'], pick['Cuota'], pick['Stake_Eur'], pick['Prob'], pick_key_ui))
                        else:
                            cc4.write("⚠️ *Sin Valor Matemático*")
                            cc5.button("No Operable", key=f"btn_nop_{pick_key_ui}", disabled=True)
                        
                        # --- MODULO ACTUALIZADO CON STAKE ---
                        with st.expander("📊 Ver Datos Matemáticos en Crudo (Copiar para IA)"):
                            datos_crudos = f"""**DATOS DEL PARTIDO**
- **Partido:** {pick['Partido']}
- **Competición:** {pick['Liga']} ({pick['Pais']})
- **Horario:** {pick['Fecha_Hora']}
- **Mercado Recomendado:** {pick['Mercado']}
- **Cuota Casa de Apuestas:** {pick['Cuota']}
- **Stake Recomendado (1-10):** {pick['Stake_1_10']}/10
- **Probabilidad Real (Modelo):** {pick['Prob']*100:.1f}%
- **Valor Esperado (EV+):** {pick['EV']*100:.1f}%

**MÉTRICAS INTERNAS (Fuerza Relativa y Goles Esperados)**
- **xG (Goles Esperados):** Local {pick['xG_loc']:.2f} | Visitante {pick['xG_vis']:.2f}
- **Rendimiento Local:** Fuerza Ofensiva {pick['FA_H']:.2f} | Fuerza Defensiva {pick['FD_H']:.2f}
- **Rendimiento Visitante:** Fuerza Ofensiva {pick['FA_A']:.2f} | Fuerza Defensiva {pick['FD_A']:.2f}
*(Nota: Valores de Fuerza > 1.0 indican rendimiento superior a la media de la liga)*
"""
                            st.code(datos_crudos, language="markdown")
                            st.caption("Copia este bloque de texto usando el icono de arriba a la derecha y pégalo en tu IA junto con el Prompt Maestro.")
                        
                        st.divider()
            else:
                st.warning("No hay resultados que superen los filtros de rentabilidad.")
        else:
            st.warning("El modelo no encontró ningún pick relevante para hoy.")

elif modo_vista == "2️⃣ Explorador de Ligas":
    st.title(f"🌍 Próxima Jornada: {liga_sel} ({pais_sel})")
    prox_partidos = cargar_proxima_jornada_liga(id_liga_explorador)
    if not prox_partidos: st.info("No hay datos de próximos partidos para esta liga.")
    else:
        stats, medias = obtener_fuerzas_liga(id_liga_explorador)
        tabla_liga = []
        for p in prox_partidos:
            loc, vis = p["teams"]["home"]["name"], p["teams"]["away"]["name"]
            sl = stats.get(limpiar_nombre(loc), {"FA_H": 1.0, "FD_H": 1.0})
            sv = stats.get(limpiar_nombre(vis), {"FA_A": 1.0, "FD_A": 1.0})
            xG_l = sl["FA_H"] * sv["FD_A"] * medias.get("avg_home", 1.5)
            xG_v = sv["FA_A"] * sl["FD_H"] * medias.get("avg_away", 1.2)
            probs, _, _ = calcular_mercados(xG_l, xG_v)
            tabla_liga.append({
                "Fecha": p["fixture"]["date"][:10], "Local": loc, "Visitante": vis,
                "% Gana Local": f"{probs['1']*100:.1f}%", "% Empate": f"{probs['X']*100:.1f}%", "% Gana Vis": f"{probs['2']*100:.1f}%"
            })
        st.dataframe(pd.DataFrame(tabla_liga), use_container_width=True)

elif modo_vista == "3️⃣ Mi Cartera (Resultados)":
    st.title("💼 Rendimiento del Fondo")
    if st.button("🔄 Auto-Resolver Partidos Finalizados"):
        with st.spinner("Conectando con la API..."):
            resueltas = auto_resolver_apuestas()
            st.success(f"Se han actualizado {resueltas} apuestas finalizadas.")
            time.sleep(1)
            st.rerun()

    df = pd.read_csv(TRACKER_FILE)
    if df.empty: st.info("Aún no has registrado ninguna apuesta.")
    else:
        df_finalizadas = df[df["Estado"] != "Pendiente"]
        total_apostado = df_finalizadas["Stake_Eur"].sum()
        total_pnl = df_finalizadas["PnL"].sum()
        yield_pct = (total_pnl / total_apostado * 100) if total_apostado > 0 else 0
        aciertos = len(df_finalizadas[df_finalizadas["Estado"] == "Ganada"])
        total_resueltas = len(df_finalizadas)
        hit_rate = (aciertos / total_resueltas * 100) if total_resueltas > 0 else 0

        c1, c2, c3 = st.columns(3)
        c1.metric("Beneficio Neto (PnL)", f"€{total_pnl:.2f}")
        c2.metric("Yield (ROI)", f"{yield_pct:.2f}%")
        c3.metric("Hit Rate (Aciertos)", f"{hit_rate:.1f}% ({aciertos}/{total_resueltas})")

        if not df_finalizadas.empty:
            df_finalizadas["Bank_Progresivo"] = BANKROLL_INICIAL + df_finalizadas["PnL"].cumsum()
            chart_data = df_finalizadas[["Bank_Progresivo"]].copy()
            chart_data.loc[-1] = [BANKROLL_INICIAL]
            chart_data.index = chart_data.index + 1
            st.line_chart(chart_data.sort_index())

        st.dataframe(df.sort_values(by="Fecha", ascending=False), use_container_width=True)