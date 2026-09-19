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
st.set_page_config(page_title="Quant Pro V15 | Data Sanitization", layout="wide")

API_KEY = "08edd9f31ef5d32739e7d7acb5740f57"  # ⚠️ CLAVE PREMIUM AQUÍ
HEADERS = {'x-apisports-key': API_KEY}
BANKROLL_INICIAL = 100.0
APUESTA_MINIMA_EUROS = 0.20
ITEMS_POR_PAGINA = 50

PAISES_LIGAS = {
    "Alemania": {"1. Bundesliga": 78, "2. Bundesliga": 79, "3. Liga": 80, "Reg. Nord": 81, "Reg. Nordost": 82, "Reg. West": 83, "Reg. Südwest": 84, "Reg. Bayern": 85},
    "Austria": {"Bundesliga": 218, "2. Liga": 219},
    "Bélgica": {"Jupiler Pro League": 144, "Challenger Pro": 145},
    "Dinamarca": {"Superliga": 119, "1st Division": 120},
    "España": {"LaLiga": 140, "LaLiga 2": 141, "Liga Femenina": 142},
    "Finlandia": {"Veikkausliiga": 128, "Ykkösliiga": 129},
    "Francia": {"Ligue 1": 61, "Ligue 2": 62, "National": 63},
    "Inglaterra": {"Premier League": 39, "Championship": 40, "League One": 41, "League Two": 42},
    "Italia": {"Serie A": 135, "Serie B": 136},
    "Japón": {"J1 League": 98, "J2 League": 99},
    "Noruega": {"Eliteserien": 103, "Obos-Ligaen": 104},
    "Paises Bajos": {"Eredivisie": 88, "Eerste Divisie": 89},
    "Portugal": {"Primeira Liga": 94, "Liga Portugal 2": 95},
    "Suecia": {"Allsvenskan": 113, "Superettan": 114},
    "Suiza": {"Super League": 207, "Challenge League": 208}
}

LIGAS_IDS_ACTIVAS = [id for pais in PAISES_LIGAS.values() for id in pais.values()]

# ---------------------------------------------------------
# 2. SISTEMA DE TRACKING Y MEMORIA PERMANENTE BLINDADA
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
    """Lee el CSV forzando que los IDs sean enteros limpios sin decimales fantasmas"""
    init_tracker()
    try:
        df = pd.read_csv(TRACKER_FILE)
        if df.empty: return set()
        
        historico = set()
        for _, row in df.iterrows():
            try:
                # Transforma "1234.0" en "1234"
                fid = str(int(float(row["Fixture_ID"])))
            except:
                fid = str(row["Fixture_ID"]).strip()
            merc = str(row["Mercado"]).strip()
            historico.add(f"{fid}_{merc}")
        return historico
    except:
        return set()

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
        # Limpiar el ID antes de enviarlo a la API
        try:
            fid_limpio = int(float(row['Fixture_ID']))
        except:
            fid_limpio = row['Fixture_ID']
            
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
# 3. MOTORES MATEMÁTICOS DE ÉLITE
# ---------------------------------------------------------
def limpiar_nombre(texto): return re.sub(r'\b(fc|cf|ud|sd|cd|real|1\.)\b', '', (texto or "").lower()).strip()

def calcular_momentum_weibull(form_str):
    if not form_str: return 1.0
    pesos = {'W': 1.15, 'D': 1.00, 'L': 0.85}
    form_list = list(form_str[-5:]) if len(form_str) >= 5 else list(form_str)
    weibull_weights = [0.10, 0.25, 0.60, 1.30, 2.75] 
    score, divisor = 0, 0
    for i, res in enumerate(form_list):
        w = weibull_weights[i]
        score += pesos.get(res, 1.0) * w
        divisor += w
    return score / divisor if divisor > 0 else 1.0

def desviggar_cuotas(cuotas_dict, keys):
    prob_implicitas = {}
    overround = 0.0
    if all(k in cuotas_dict for k in keys):
        for k in keys:
            prob = 1.0 / cuotas_dict[k]
            prob_implicitas[k] = prob
            overround += prob
        cuotas_reales = {}
        for k in keys:
            cuotas_reales[f"TrueProb_{k}"] = prob_implicitas[k] / overround
            cuotas_reales[f"TrueOdd_{k}"] = 1.0 / cuotas_reales[f"TrueProb_{k}"]
        return cuotas_reales
    return {}

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
        
        avg_g_loc = sum(t["home"]["goals"]["for"] for t in standings) / pj_loc
        avg_g_vis = sum(t["away"]["goals"]["for"] for t in standings) / sum(t["away"]["played"] for t in standings)
        
        stats_eq = {}
        C = 5.0 
        for t in standings:
            nom = limpiar_nombre(t["team"]["name"])
            mom = calcular_momentum_weibull(t.get("form", ""))
            
            hl_pj, hl_gf, hl_gc = t["home"]["played"], t["home"]["goals"]["for"], t["home"]["goals"]["against"]
            aw_pj, aw_gf, aw_gc = t["away"]["played"], t["away"]["goals"]["for"], t["away"]["goals"]["against"]
            
            gf_tot, gc_tot = t["all"]["goals"]["for"], t["all"]["goals"]["against"]
            factor_suerte = 1.0
            if gf_tot + gc_tot > 0:
                pyth_pct = (gf_tot**1.7) / (gf_tot**1.7 + gc_tot**1.7)
                real_pct = t["all"]["win"] / t["all"]["played"] if t["all"]["played"]>0 else 0
                factor_suerte = real_pct / pyth_pct if pyth_pct > 0 else 1.0

            fa_l = ((((hl_gf + C * avg_g_loc) / (hl_pj + C)) / avg_g_loc) * mom) / max(0.8, min(factor_suerte, 1.2))
            fd_l = ((((hl_gc + C * avg_g_vis) / (hl_pj + C)) / avg_g_vis) / mom) * max(0.8, min(factor_suerte, 1.2))
            fa_v = ((((aw_gf + C * avg_g_vis) / (aw_pj + C)) / avg_g_vis) * mom) / max(0.8, min(factor_suerte, 1.2))
            fd_v = ((((aw_gc + C * avg_g_loc) / (aw_pj + C)) / avg_g_loc) / mom) * max(0.8, min(factor_suerte, 1.2))
            
            stats_eq[nom] = {"FA_H": fa_l, "FD_H": fd_l, "FA_A": fa_v, "FD_A": fd_v}
        return stats_eq, {"avg_home": avg_g_loc, "avg_away": avg_g_vis}
    except: return {}, {}

def ajuste_dixon_coles(x, y, l_l, l_v):
    rho = max(-0.25, -0.10 * (2.5 / max(0.1, l_l + l_v)))
    if x == 0 and y == 0: return max(0.0, 1.0 - l_l * l_v * rho)
    if x == 0 and y == 1: return max(0.0, 1.0 + l_l * rho)
    if x == 1 and y == 0: return max(0.0, 1.0 + l_v * rho)
    if x == 1 and y == 1: return max(0.0, 1.0 - rho)
    return 1.0

def calcular_mercados(xg_l, xg_v):
    p_1, p_x, p_2, p_ov25, p_btts = 0.0, 0.0, 0.0, 0.0, 0.0
    inflacion_cero = 0.06 
    
    for g_l in range(8):
        for g_v in range(8):
            p_ex = poisson.pmf(g_l, xg_l) * poisson.pmf(g_v, xg_v) * ajuste_dixon_coles(g_l, g_v, xg_l, xg_v)
            if g_l == 0 and g_v == 0: p_ex = (p_ex * (1 - inflacion_cero)) + inflacion_cero
            else: p_ex = p_ex * (1 - inflacion_cero)
            
            if g_l > g_v: p_1 += p_ex
            elif g_l == g_v: p_x += p_ex
            else: p_2 += p_ex
            if (g_l + g_v) > 2.5: p_ov25 += p_ex
            if g_l > 0 and g_v > 0: p_btts += p_ex
            
    t = p_1 + p_x + p_2
    if t == 0: return {'1': 0.33, 'X': 0.33, '2': 0.33}, 0.5, 0.5
    return {'1': p_1/t, 'X': p_x/t, '2': p_2/t}, p_ov25/t, p_btts/t

def calcular_corners_y_tarjetas(xg_l, xg_v, prob_1x2, ritmo_partido):
    xg_total = (xg_l + xg_v) 
    exp_corners = 7.0 + (xg_total * 0.9) 
    if prob_1x2['1'] > 0.65 or prob_1x2['2'] > 0.65:
        exp_corners *= 0.90
    v = exp_corners * 1.25
    p_ov95c = 1 - nbinom.cdf(9, (exp_corners**2) / (v - exp_corners), exp_corners / v) if exp_corners < v else 0.5

    tension = 1.0 - abs(prob_1x2['1'] - prob_1x2['2'])
    exp_tarjetas = (3.5 + (tension * 2.0)) * ritmo_partido
    p_ov45t = 1 - poisson.cdf(4, exp_tarjetas)
    
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
# 4. INTERFAZ GRÁFICA Y PAGINACIÓN
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
    st.title("🤖 Escáner Cuantitativo Auditado")
    
    dias = {"Hoy": 0, "Mañana": 1, "Pasado": 2}
    c_dia, c_riesgo, c_orden, c_btn = st.columns([1, 1.2, 1.3, 1])
    dia_sel = c_dia.selectbox("Día", list(dias.keys()))
    max_exposure = c_riesgo.slider("Riesgo Máx (%)", 5, 30, 15)
    
    def reset_pagina(): st.session_state.pagina_actual = 1
    criterio_orden = c_orden.selectbox("Escanear por:", ["💰 Importe (EV+)", "📊 Probabilidad (%)"], on_change=reset_pagina)
    
    fecha_calc = (datetime.now() + timedelta(days=dias[dia_sel])).strftime("%Y-%m-%d")
    
    if 'raw_picks' not in st.session_state: st.session_state.raw_picks = None
    if 'pagina_actual' not in st.session_state: st.session_state.pagina_actual = 1

    if c_btn.button("🔄 Ejecutar Escáner"):
        st.session_state.pagina_actual = 1 
        partidos = cargar_datos_jornada(fecha_calc)
        if not partidos:
            st.info("No hay partidos programados en las 38 ligas para este día.")
            st.session_state.raw_picks = [] 
        else:
            ligas_activas = list(set([p["league"]["id"] for p in partidos]))
            stats_liga, medias_liga = {}, {}
            
            with st.spinner(f"Evaluando {len(partidos)} partidos en toda Europa..."):
                for lid in ligas_activas:
                    s, m = obtener_fuerzas_liga(lid)
                    stats_liga[lid], medias_liga[lid] = s, m

            raw_picks_temp = []
            bar = st.progress(0)
            
            for i, p in enumerate(partidos):
                f_id, lid = p["fixture"]["id"], p["league"]["id"]
                loc, vis = p["teams"]["home"]["name"], p["teams"]["away"]["name"]
                
                sl = stats_liga.get(lid, {}).get(limpiar_nombre(loc), {"FA_H": 1.0, "FD_H": 1.0})
                sv = stats_liga.get(lid, {}).get(limpiar_nombre(vis), {"FA_A": 1.0, "FD_A": 1.0})
                ritmo_partido = 1.0 + ((sl["FA_H"] + sv["FA_A"] - 2.0) * 0.15)
                
                xG_loc = sl["FA_H"] * sv["FD_A"] * medias_liga.get(lid, {}).get("avg_home", 1.5) * ritmo_partido
                xG_vis = sv["FA_A"] * sl["FD_H"] * medias_liga.get(lid, {}).get("avg_away", 1.2) * ritmo_partido
                
                prob_1x2, p_ov25, p_btts = calcular_mercados(xG_loc, xG_vis)
                p_ov95c, p_ov45t = calcular_corners_y_tarjetas(xG_loc, xG_vis, prob_1x2, ritmo_partido)
                cuotas = obtener_cuotas_partido(f_id)
                cuotas_desviggadas = desviggar_cuotas(cuotas, ["1", "X", "2"])
                
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
                    if cuota > 1.10:
                        ev = (p_real * cuota) - 1
                        ev_valido = True
                        if p_real_casa > 0 and (p_real - p_real_casa) < 0.01:
                            ev_valido = False
                            
                        tiene_valor = (ev > 0.03 and ev_valido)
                        
                        if tiene_valor or p_real >= 0.65:
                            raw_picks_temp.append({
                                "f_id": f_id, "Partido": f"{loc} vs {vis}", "Mercado": n_merc,
                                "Prob": p_real, "Cuota": cuota, "EV": ev, "Tiene_Valor": tiene_valor
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
                    p["Raw_Kelly"] = max(0.0, ((b * p["Prob"] - (1.0 - p["Prob"])) / b))
                else:
                    p["Raw_Kelly"] = 0.0

            suma_k = sum(p["Raw_Kelly"] for p in raw_picks if p["Tiene_Valor"]) * 100
            ajuste = (max_exposure / suma_k) if suma_k > max_exposure else 0.25
            
            for p in raw_picks:
                if p["Tiene_Valor"]:
                    stake_pct = (p["Raw_Kelly"] * 100) * ajuste
                    stake_eur = (stake_pct / 100) * bankroll_actual
                else:
                    stake_eur = 0.0
                
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
                mensaje_exito = f"Se han encontrado {len(picks_ordenados)} oportunidades de Valor (EV+) seguro."
            else:
                picks_ordenados = sorted(picks_finales, key=lambda x: x["Prob"], reverse=True)
                mensaje_exito = f"Mostrando {len(picks_ordenados)} selecciones con alta probabilidad (>65%)."

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
                if 'picks_registrados' not in st.session_state:
                    st.session_state.picks_registrados = set()
                
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
                        # Saneamiento extremo para asegurar cruce perfecto
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
                        
                        st.divider()
            else:
                st.warning("No hay resultados que cumplan los criterios actuales de rentabilidad o probabilidad (>65%).")
        else:
            st.warning("El modelo no encontró ningún pick relevante para hoy.")

elif modo_vista == "2️⃣ Explorador de Ligas":
    st.title(f"🌍 Próxima Jornada: {liga_sel} ({pais_sel})")
    
    prox_partidos = cargar_proxima_jornada_liga(id_liga_explorador)
    if not prox_partidos:
        st.info("No hay datos de próximos partidos para esta liga en la API.")
    else:
        stats, medias = obtener_fuerzas_liga(id_liga_explorador)
        tabla_liga = []
        
        for p in prox_partidos:
            loc = p["teams"]["home"]["name"]
            vis = p["teams"]["away"]["name"]
            fecha = p["fixture"]["date"][:10]
            
            sl = stats.get(limpiar_nombre(loc), {"FA_H": 1.0, "FD_H": 1.0})
            sv = stats.get(limpiar_nombre(vis), {"FA_A": 1.0, "FD_A": 1.0})
            
            xG_l = sl["FA_H"] * sv["FD_A"] * medias.get("avg_home", 1.5)
            xG_v = sv["FA_A"] * sl["FD_H"] * medias.get("avg_away", 1.2)
            
            probs, _, _ = calcular_mercados(xG_l, xG_v)
            
            tabla_liga.append({
                "Fecha": fecha, "Local": loc, "Visitante": vis,
                "% Gana Local": f"{probs['1']*100:.1f}%",
                "% Empate": f"{probs['X']*100:.1f}%",
                "% Gana Vis": f"{probs['2']*100:.1f}%"
            })
            
        st.dataframe(pd.DataFrame(tabla_liga), use_container_width=True)

elif modo_vista == "3️⃣ Mi Cartera (Resultados)":
    st.title("💼 Rendimiento del Fondo")
    
    if st.button("🔄 Auto-Resolver Partidos Finalizados"):
        with st.spinner("Conectando con resultados reales de la API..."):
            resueltas = auto_resolver_apuestas()
            st.success(f"Se han actualizado {resueltas} apuestas finalizadas.")
            time.sleep(1)
            st.rerun()

    df = pd.read_csv(TRACKER_FILE)
    
    if df.empty:
        st.info("Aún no has registrado ninguna apuesta.")
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
            st.markdown("### 📈 Evolución del Bankroll")
            df_finalizadas["Bank_Progresivo"] = BANKROLL_INICIAL + df_finalizadas["PnL"].cumsum()
            chart_data = df_finalizadas[["Bank_Progresivo"]].copy()
            chart_data.loc[-1] = [BANKROLL_INICIAL]
            chart_data.index = chart_data.index + 1
            chart_data.sort_index(inplace=True)
            st.line_chart(chart_data)

        st.markdown("### 📝 Historial de Operaciones")
        st.dataframe(df.sort_values(by="Fecha", ascending=False), use_container_width=True)