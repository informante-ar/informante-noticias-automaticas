import feedparser
import sqlite3
import requests
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import re
import random
from groq import Groq
import datetime
import os

# --- GENERADOR DE LLAVES PARA LA NUBE ---
if "GOOGLE_JSON" in os.environ:
    with open("client_secrets.json", "w") as f:
        f.write(os.environ["GOOGLE_JSON"])

# Si estamos en GitHub Actions, creamos el archivo JSON desde el secreto
if "GOOGLE_JSON" in os.environ:
    print("[INFO] Generando archivo de credenciales de Google...")
    with open("client_secrets.json", "w") as f:
        f.write(os.environ["GOOGLE_JSON"])
else:
    if not os.path.exists("client_secrets.json"):
        print("[ALERTA] No se detectó el secreto GOOGLE_JSON ni el archivo local. Blogger podría fallar.")

# --- 1. CONFIGURACIÓN ---
# Así el bot busca las llaves en los Secretos de GitHub (o usa las locales por defecto)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
MODELO = "llama-3.1-8b-instant"

# Directorio base (para que funcione en PythonAnywhere sin perderse)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Datos Blogger
EMAIL_DESTINO_BLOGGER = "victormarsilli18.victorruben1@blogger.com"
MI_GMAIL = "victormarsilli18@gmail.com"
MI_GMAIL_APP_PASSWORD = "hite ajcz ufre hmnj" 
URL_BLOG = "https://informantear.blogspot.com/" # ⚠️ VERIFICÁ QUE ESTE SEA TU LINK EXACTO

# Datos Facebook (IMPORTANTE: Usa el token de PÁGINA que sacamos)
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN", "EAAUycAE8pgkBQ2LC4eqKe4rPj4BLJzIZAIOGyDEZCM1PXx821UqCd2rQlwBuvc04u0DKxfdKn1DZAHbK90u59URrCqZAWvVPzo4cfREMYiNkuxOg897dHeGqOwAZAVqhTWZCtvX0DGUDDHKF2ZCG4fEvotAZCvR33u6OILWZBnIZB7ZAfW4SQZCuyzJHQyJDpHZCJMQpiXLrjJ7TD")
FB_PAGE_ID = "me" # "me" funciona si el token es de la página
BLOG_ID = os.environ.get("BLOG_ID", "166823084082098901")

client = Groq(api_key=GROQ_API_KEY)


# --- 2. BASE DE DATOS ---
def inicializar_db():
    conn = sqlite3.connect('vIcmAr_noticias.db')
    db_path = os.path.join(BASE_DIR, 'vIcmAr_noticias.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS posts (id_noticia TEXT PRIMARY KEY)''')
    conn.commit()
    return conn

# --- 3. REDACCIÓN CON IA ---
def transformar_con_ia(titulo, resumen):
    try:
        # Filtramos clima y pronostico para que no vaya al Blog (ya tenemos la funcion publicar_clima para FB)
        if any(palabra in titulo.lower() for palabra in ["quiniela", "sorteo", "lotería", "clima", "pronostico", "pronóstico"]):
            return None, None

        prompt = f"""
        Actúa como un experto en SEO y periodista digital. Reescribe esta noticia para el blog 'informARte' optimizando para motores de búsqueda.
        Título original: {titulo}
        Resumen: {resumen}
        
        REGLAS DE FORMATO Y SEO:
        1. Primera línea: SOLO el título reescrito (texto plano, SIN HTML). NO escribas "Título:", "Título atractivo:" ni uses comillas o asteriscos (**).
        2. Estructura HTML (SOLO para el cuerpo): Usa <h2> para subtítulos (importante para SEO), <p> para párrafos, <ul>/<li> para listas.
        3. Intro SEO: El primer párrafo debe ser un resumen impactante (Lead) en <strong> que contenga las palabras clave principales.
        4. NO uses Markdown (**negrita**). Usa siempre HTML (<strong>negrita</strong>).
        5. Legibilidad: Usa párrafos cortos y lenguaje natural, dale un estilo moderno.
        6. Localización: Si menciona Comodoro Rivadavia, Chubut o Argentina, resáltalo.
        """
        
        completion = client.chat.completions.create(
            model=MODELO,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        
        respuesta = completion.choices[0].message.content
        lineas = respuesta.split('\n')
        
        # Limpieza agresiva del título para sacar "Título atractivo:" y asteriscos
        raw_title = lineas[0]
        raw_title = re.sub(r'<[^>]+>', '', raw_title) # Eliminar etiquetas HTML del título si la IA las puso
        clean_title = re.sub(r'^(Título|Titulo|Título atractivo|Titulo atractivo|Asunto)[:\s-]*', '', raw_title, flags=re.IGNORECASE)
        nuevo_titulo = clean_title.replace('**', '').replace('*', '').replace('"', '').strip()
        
        cuerpo = "\n".join(lineas[1:])
        cuerpo = cuerpo.replace('**', '') # Eliminar asteriscos si la IA no obedeció
        return nuevo_titulo, cuerpo
    except: return None, None

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
import pickle

# Esta función se encarga de entrar a tu Blogger sin usar mails
def obtener_servicio_blogger():
    scopes = ['https://www.googleapis.com/auth/blogger']
    creds = None
    
    token_path = os.path.join(BASE_DIR, 'token.pickle')
    secrets_path = os.path.join(BASE_DIR, 'client_secrets.json')
    
    # Guardamos el "permiso" en un archivo para no tener que loguearnos cada vez
    if os.path.exists(token_path):
        print("[INFO] Cargando token de sesión de Blogger...")
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    else:
        print("[ALERTA] No se encontró 'token.pickle'. El bot intentará abrir un navegador (fallará en la nube).")
            
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("[INFO] Refrescando token de Google...")
            creds.refresh(Request())
        else:
            # Aquí es donde usamos el archivo que bajaste de Google Cloud
            # IMPORTANTE: En GitHub Actions esto fallará si no subes el token.pickle
            if not os.path.exists(secrets_path):
                print("[ERROR] No existe client_secrets.json ni token válido. No se puede autenticar en Blogger.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes)
            creds = flow.run_local_server(port=0)
            
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)
            
    return build('blogger', 'v3', credentials=creds)

def publicar_en_blogger_api(titulo, contenido_html, imagen_url):
    # --- ESTILOS VISUALES (CSS INLINE) ---
    estilo_contenedor = "font-family: 'Georgia', 'Times New Roman', serif; font-size: 18px; line-height: 1.8; color: #2c3e50; max-width: 800px; margin: 0 auto;"
    estilo_h2 = "color: #d35400; font-family: 'Helvetica', 'Arial', sans-serif; font-weight: bold; margin-top: 30px; border-bottom: 2px solid #f39c12; padding-bottom: 5px;"
    estilo_img = "width: 100%; height: auto; border-radius: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); margin-bottom: 20px;"
    estilo_footer = "background-color: #ecf0f1; padding: 20px; border-radius: 10px; margin-top: 40px; font-family: 'Arial', sans-serif; font-size: 15px; text-align: center; color: #7f8c8d;"

    # Inyectamos los estilos
    contenido_estilizado = contenido_html.replace('<h2>', f'<h2 style="{estilo_h2}">')
    contenido_estilizado = contenido_estilizado.replace('<h3>', f'<h2 style="{estilo_h2}">')
    
    # Construimos el HTML final para la API
    cuerpo_final = f'<div style="{estilo_contenedor}">'
    if imagen_url:
        cuerpo_final += f'<img src="{imagen_url}" alt="{titulo}" style="{estilo_img}" />'
    
    cuerpo_final += f'<div>{contenido_estilizado}</div>'
    cuerpo_final += f'<div style="{estilo_footer}">📢 <strong>¡Gracias por leer!</strong><br>Si te sirvió esta información, compartila con tus amigos.<br><em>Seguinos en <a href="https://www.facebook.com/Informante.ar" style="color: #3b5998; text-decoration: none; font-weight: bold;">Facebook</a> y visitá nuestro <a href="{URL_BLOG}" style="color: #e67e22; text-decoration: none; font-weight: bold;">Blog</a> para más noticias de Comodoro y el país.</em></div>'
    cuerpo_final += '</div>'
    
    try:
        service = obtener_servicio_blogger()
        if not service:
            print("[ERROR] Saltando publicación en Blogger por falta de credenciales.")
            return False
        
        body = {
            "kind": "blogger#post",
            "title": titulo,
            "content": cuerpo_final
        }
        
        # Reintentos ante error de cuota (429)
        for i in range(3):
            try:
                service.posts().insert(blogId=BLOG_ID, body=body).execute()
                return True
            except HttpError as e:
                if e.resp.status == 429:
                    print(f"[ALERTA] Cuota Blogger excedida. Esperando {60*(i+1)}s...")
                    time.sleep(60 * (i + 1))
                else:
                    raise e
        return False
    except Exception as e:
        print(f"[ERROR] API Blogger: {e}")
        return False

def publicar_en_facebook(titulo, cuerpo_ia, imagen_url, hashtags="", incluir_link=True):
    # Mejoramos el formato: convertimos etiquetas HTML útiles a texto antes de limpiar
    texto_formateado = cuerpo_ia.replace('<li>', '• ').replace('</li>', '\n')
    texto_formateado = texto_formateado.replace('<p>', '').replace('</p>', '\n')
    texto_formateado = texto_formateado.replace('<br>', '\n').replace('<br/>', '\n')
    
    # Limpiamos el resto de etiquetas HTML
    texto_limpio = re.sub('<[^<]+?>', '', texto_formateado)
    texto_fb = "\n\n".join([line.strip() for line in texto_limpio.splitlines() if line.strip()])
    
    # CTA (Llamada a la acción) más fuerte para generar CLICS (Dinero)
    if incluir_link:
        mensaje_final = f"📌 {titulo}\n\n{texto_fb}\n\n👇 LEÉ LA NOTA COMPLETA ACÁ 👇\n{URL_BLOG}\n\n{hashtags}"
    else:
        mensaje_final = f"📌 {titulo}\n\n{texto_fb}\n\n{hashtags}"
    
    # Lógica para imagen: Usamos /photos si hay imagen (se ve más grande y bonita), sino /feed
    if imagen_url:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/photos"
        payload = {
            'message': mensaje_final,
            'url': imagen_url,
            'access_token': FB_PAGE_TOKEN
        }
    else:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
        payload = {
            'message': mensaje_final,
            'access_token': FB_PAGE_TOKEN
        }
    
    try:
        r = requests.post(url, data=payload)
        resultado = r.json()
        if r.status_code == 200:
            print("[OK] Publicado en Facebook con exito!")
        else:
            # Si vuelve a fallar, el error nos dirá exactamente qué permiso falta
            print(f"[ALERTA] Detalle del error: {resultado.get('error').get('message')}")
    except Exception as e:
        print(f"[ERROR] Conexion FB: {e}")

# --- FUNCION AUXILIAR: HASHTAGS ---
def obtener_hashtags(url_fuente):
    # Asigna hashtags según de dónde viene la noticia para ganar viralidad
    if "adnsur" in url_fuente or "elpatagonico" in url_fuente or "elcomodorense" in url_fuente:
        return "#Comodoro #Chubut #NoticiasLocales #Patagonia"
    elif "ole.com" in url_fuente or "tycsports" in url_fuente:
        return "#Deportes #FutbolArgentino #Argentina"
    elif "diarioshow" in url_fuente or "ciudad.com" in url_fuente or "pronto" in url_fuente:
        return "#Espectaculos #GranHermano #Farandula #Chimentos"
    elif "clarin" in url_fuente and "musica" in url_fuente:
        return "#Musica #Artistas #Show"
    elif "ambito" in url_fuente or "lanacion" in url_fuente:
        return "#Economia #Dolar #Finanzas"
    else:
        return "#Actualidad #Argentina #Noticias"

# --- 5. FUNCION CLIMA ---
def publicar_clima():
    conn = inicializar_db()
    cursor = conn.cursor()
    
    hoy = datetime.date.today()
    id_clima = f"clima_{hoy}"
    
    # Verificar si ya publicamos el clima hoy para no repetir
    cursor.execute("SELECT id_noticia FROM posts WHERE id_noticia = ?", (id_clima,))
    if cursor.fetchone():
        conn.close()
        return

    print("[INFO] Obteniendo datos del clima para Comodoro...")
    try:
        # API Open-Meteo (Gratis) - Coordenadas de Comodoro Rivadavia
        # Agregamos wind_speed_10m_max para el viento
        url = "https://api.open-meteo.com/v1/forecast?latitude=-45.8641&longitude=-67.4966&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max&timezone=auto&wind_speed_unit=kmh&forecast_days=1"
        r = requests.get(url)
        data = r.json()
        
        daily = data.get('daily', {})
        max_temp = daily['temperature_2m_max'][0]
        min_temp = daily['temperature_2m_min'][0]
        lluvia = daily['precipitation_probability_max'][0]
        viento = daily['wind_speed_10m_max'][0]
        
        titulo = f"🌦️ El Clima en Comodoro - {hoy.strftime('%d/%m/%Y')}"
        cuerpo = f"<p><strong>¡Buenos días Comodoro!</strong> Así estará el tiempo hoy en la capital del viento:</p><ul><li><strong>Mínima:</strong> {min_temp}°C ❄️</li><li><strong>Máxima:</strong> {max_temp}°C ☀️</li><li><strong>Viento:</strong> {viento} km/h 🌬️</li><li><strong>Probabilidad de lluvia:</strong> {lluvia}% ☔</li></ul><p>¡Que tengas una excelente jornada!</p>"
        imagen_clima = "https://cdn-icons-png.flaticon.com/512/1163/1163661.png" # Icono genérico de clima
        hashtags_clima = "#Clima #ComodoroRivadavia #Tiempo #Pronostico #CapitalDelViento"
        
        # Publicamos SOLO en Facebook
        publicar_en_facebook(titulo, cuerpo, imagen_clima, hashtags_clima)
        print("[OK] Clima publicado en Facebook")
        
        cursor.execute("INSERT INTO posts VALUES (?)", (id_clima,))
        conn.commit()
    except Exception as e:
        print(f"[ERROR] Obteniendo clima: {e}")
    conn.close()

# --- 5. FUNCIÓN PRINCIPAL DEL BOT ---
def ejecutar_bot(url_rss):
    conn = inicializar_db()
    cursor = conn.cursor()
    
    print(f"[INFO] Analizando fuente: {url_rss}")
    try:
        feed = feedparser.parse(url_rss)
    except Exception as e:
        print(f"[ERROR] Leyendo RSS: {e}")
        return False

    # Procesamos las primeras noticias hasta encontrar una nueva
    for entry in feed.entries[:3]:
        guid = entry.link
        
        # Verificar si ya existe en la base de datos
        cursor.execute("SELECT id_noticia FROM posts WHERE id_noticia = ?", (guid,))
        if cursor.fetchone():
            continue
            
        print(f"[INFO] Procesando: {entry.title}")
        
        # Intentar obtener imagen para Facebook
        imagen = ""
        if hasattr(entry, 'media_content') and entry.media_content:
            imagen = entry.media_content[0]['url']
        elif hasattr(entry, 'enclosures') and entry.enclosures:
            imagen = entry.enclosures[0]['href']
            
        # Generar contenido con IA
        nuevo_titulo, cuerpo = transformar_con_ia(entry.title, getattr(entry, 'summary', ''))
        
        # Obtener hashtags según la fuente
        tags = obtener_hashtags(url_rss)
        
        if nuevo_titulo and cuerpo:
            # Intentamos publicar en Blogger
            exito_blogger = publicar_en_blogger_api(nuevo_titulo, cuerpo, imagen)
            
            if exito_blogger:
                print("[OK] Publicado en Blogger")
                publicar_en_facebook(nuevo_titulo, cuerpo, imagen, tags, incluir_link=True)
            else:
                print("[ALERTA] Falló Blogger (posible cuota), publicando solo en Facebook...")
                publicar_en_facebook(nuevo_titulo, cuerpo, imagen, tags, incluir_link=False)

            # Guardamos en DB para no repetir (ya sea que salió en Blogger o solo en FB)
            cursor.execute("INSERT INTO posts VALUES (?)", (guid,))
            conn.commit()
            conn.close()
            return True # Retornamos True para contar la publicación
    conn.close()
    return False

# --- 6. EJECUCIÓN MULTI-FUENTE ---
def iniciar_escaneo():
    lista_fuentes = [
        # --- LOCALES (COMODORO / CHUBUT) ---
        "https://www.adnsur.com.ar/rss/feed.xml",
        "https://www.elpatagonico.com/rss/pages/chubut.xml",
        "https://elcomodorense.net/feed/",
        "https://radio3cadenapatagonia.com.ar/feed/",
        
        # --- TECNOLOGÍA ---
        "https://www.clarin.com/rss/tecnologia/",
        "https://www.perfil.com/rss/tecnologia.xml",
        
        # --- SOCIEDAD (Tendencias y Viral) ---
        "https://www.infobae.com/feeds/rss/sociedad.xml",
        "https://tn.com.ar/rss/sociedad/",

        # --- ESPECTÁCULOS, CHIMENTOS Y GRAN HERMANO ---
        "https://www.diarioshow.com/rss/pages/espectaculos.xml", # Fuente principal de chimentos
        "https://www.ciudad.com.ar/rss", # Ciudad Magazine (Cubre mucho GH)
        "https://www.pronto.com.ar/rss/feed.xml", # Revista Pronto

        # --- MÚSICA ---
        "https://www.clarin.com/rss/espectaculos/musica/",
        
        # --- DEPORTES ---
        "https://www.ole.com.ar/rss/ultimas-noticias/", # Diario Olé
        "https://www.tycsports.com/rss"
    ]
    
    # Mezclamos las fuentes para que no siempre empiece por las mismas
    random.shuffle(lista_fuentes)
    
    publicaciones_ciclo = 0
    LIMITE_CICLO = 3 # Máximo de noticias a publicar por ciclo (cada 30 min)
    
    print("[INFO] --- Iniciando ciclo de noticias vIcmAr ---")
    
    # Publicar clima (se ejecuta una vez al día)
    publicar_clima()
    
    for url in lista_fuentes:
        if publicaciones_ciclo >= LIMITE_CICLO:
            print("[INFO] Limite de publicaciones por ciclo alcanzado.")
            break
            
        if ejecutar_bot(url):
            publicaciones_ciclo += 1
            print(f"[INFO] Publicaciones en este ciclo: {publicaciones_ciclo}/{LIMITE_CICLO}")
            time.sleep(30) # Pausa de seguridad entre publicaciones
    
    print(f"\n[INFO] Ciclo completado. Se publicaron {publicaciones_ciclo} noticias.")
    print(f"Hora de finalización: {time.ctime()}")
    


# --- 6. BUCLE DE REPETICIÓN CADA 30 MINUTOS ---
# if __name__ == "__main__":
#     print("[INFO] Bot vIcmAr: Informante AR esta ONLINE")
#     print("[INFO] La ventana de CMD debe quedar abierta para que el bot funcione.")
    
#     while True:
#         try:
#             iniciar_escaneo() 
            
#             print(f"\n[OK] Ciclo completado con exito a las {datetime.datetime.now().strftime('%H:%M:%S')}")
#             print("[INFO] Esperando 60 minutos para el proximo escaneo...")
#             time.sleep(3600) # 3600 segundos = 60 minutos
            
#         except Exception as e:
#             print(f"[ERROR] Ocurrio un error inesperado: {e}")
#             time.sleep(60)

if __name__ == "__main__":
    print(f"--- [vIcmAr CLOUD] ---")
    try:
        iniciar_escaneo() # Corre una vez y termina
        print("[OK] Proceso finalizado con éxito.")
    except Exception as e:
        print(f"[ERROR]: {e}")
        
        
