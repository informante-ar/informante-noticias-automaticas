import feedparser
import sqlite3
import requests
import time
import re
import random
from groq import Groq
import datetime
import os
import json

# --- GENERADOR DE LLAVES SEGURO ---
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
secrets_path = os.path.join(BASE_DIR, 'client_secrets.json')

if "GOOGLE_JSON" in os.environ:
    print(f"[INFO] Generando credenciales en: {secrets_path}")
    with open(secrets_path, "w") as f:
        f.write(os.environ["GOOGLE_JSON"])
else:
    print("[INFO] Usando archivo local si existe...")
# --- 1. CONFIGURACIÓN ---
# Así el bot busca las llaves en los Secretos de GitHub (o usa las locales por defecto)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
MODELO = "llama-3.1-8b-instant"

# Directorio base (para que funcione en PythonAnywhere sin perderse)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Datos Blogger
URL_BLOG = "https://informantear.blogspot.com/" # ⚠️ VERIFICÁ QUE ESTE SEA TU LINK EXACTO

# Datos Facebook (IMPORTANTE: Usa el token de PÁGINA que sacamos)
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
FB_PAGE_ID = "me" # "me" funciona si el token es de la página
BLOG_ID = os.environ.get("BLOG_ID")

client = Groq(api_key=GROQ_API_KEY)


# --- 2. BASE DE DATOS ---
def inicializar_db():
    # 1. Forzamos la ruta absoluta a la carpeta del bot
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(BASE_DIR, 'vIcmAr_noticias.db')
    
    print(f"[DEBUG] La base de datos se ubicará en: {db_path}")
    
    # 2. Conectamos (esto crea el archivo si no existe)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS posts (id_noticia TEXT PRIMARY KEY)''')
    conn.commit()
    return conn



# --- 3. REDACCIÓN CON IA ---
def transformar_con_ia(titulo, resumen):
    try:
        # Filtramos clima y pronostico para que no vaya al Blog (ya tenemos la funcion publicar_clima para FB)
        if any(palabra in titulo.lower() for palabra in ["quiniela", "sorteo", "lotería", "clima", "pronostico", "pronóstico", "tiempo", "alerta", "lluvia", "viento", "temperatura", "nevada"]):
            return None, None

        prompt = f"""
        Actúa como el Editor en Jefe de "vIcmAr Noticias". Tu estilo es dinámico, informativo y directo.
        
        Título original: {titulo}
        Resumen: {resumen}
        
        REGLAS DE ORO PARA EL POST:
        1. FORMATO TÉCNICO (OBLIGATORIO):
           - Primera línea: SOLO el TITULAR reescrito (Texto plano). NO escribas "Título:", "Noticia reeditada" ni uses comillas.
           - Resto: Cuerpo de la noticia en HTML (<p>, <ul>, <li>, <strong>). NO uses Markdown ni asteriscos.

        2. ESTRUCTURA DEL CONTENIDO:
           - TITULAR: En MAYÚSCULAS y con INTRIGA EXTREMA (estilo viral). PROHIBIDO poner "Noticia reeditada" o "Resumen". El usuario DEBE sentir curiosidad por saber más.
           - 🕒 <strong>El Dato Clave:</strong> Lista <ul> con 3 puntos muy breves <li> usando emojis. No cuentes el final de la noticia, deja misterio.
           - 📝 <strong>El desarrollo:</strong> Un texto explicativo y atrapante (más detallado para el blog) <p>.
           -  <strong>Relevancia:</strong> Si es de Comodoro Rivadavia o Chubut, usa un tono de "Vecino a Vecino", muy cercano y barrial.
           - 🗣️ <strong>Debate Polémico:</strong> Termina SIEMPRE con una pregunta abierta y controversial que obligue a la gente a comentar indignada o a favor <p>.

        3. PERSONALIDAD:
           - Usá un lenguaje muy coloquial, 100% argentino, con "voseo" directo (ej: "Mirá esto", "No lo vas a creer", "Contanos qué opinás").
           - Evitá palabras técnicas; hablá como si estuvieras en un café charlando.
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
from google.oauth2.credentials import Credentials

# Esta función se encarga de entrar a tu Blogger sin usar mails
def obtener_servicio_blogger():
    scopes = ['https://www.googleapis.com/auth/blogger']
    creds = None
    
    token_path = os.path.join(BASE_DIR, 'token.pickle')
    secrets_path = os.path.join(BASE_DIR, 'client_secrets.json')
    
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
    google_json = os.environ.get("GOOGLE_JSON", "").strip()

    # 1. Intentar usar Refresh Token si está configurado en GitHub Actions
    if refresh_token and google_json:
        print("[INFO] Usando GOOGLE_REFRESH_TOKEN desde GitHub Secrets...")
        client_info = json.loads(google_json)
        client_data = client_info.get("installed", client_info.get("web", {}))
        
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=client_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=client_data.get("client_id"),
            client_secret=client_data.get("client_secret"),
            scopes=scopes
        )

    # 2. Si no hay variables, intentamos cargar token.pickle local
    elif os.path.exists(token_path):
        print("[INFO] Cargando token de sesión de Blogger...")
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)
    else:
        print("[ALERTA] No se encontró 'token.pickle'. El bot intentará abrir un navegador (fallará en la nube).")
            
    # 3. Validar o actualizar credenciales
    if not creds or not creds.valid:
        if creds and creds.refresh_token:
            print("[INFO] Refrescando token de Google...")
            creds.refresh(Request())
        else:
            if not os.path.exists(secrets_path):
                print("[ERROR] No existe client_secrets.json ni token válido. No se puede autenticar en Blogger.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(secrets_path, scopes)
            creds = flow.run_local_server(port=0)
            
        # Solo guardamos el token.pickle si estamos en local (no en Actions con REFRESH_TOKEN)
        if "GOOGLE_REFRESH_TOKEN" not in os.environ:
            with open(token_path, 'wb') as token:
                pickle.dump(creds, token)
                
        # Mostrar token por consola para que el usuario pueda configurarlo
        if creds.refresh_token and "GOOGLE_REFRESH_TOKEN" not in os.environ:
            print(f"\n[IMPORTANTE] Copia este código y guárdalo en GitHub Secrets como 'GOOGLE_REFRESH_TOKEN':\n\n{creds.refresh_token}\n")
            
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
                # Guardamos la respuesta de la API para extraer el Link exacto de esta noticia
                respuesta_blog = service.posts().insert(blogId=BLOG_ID, body=body).execute()
                return respuesta_blog.get('url') # Retornamos la URL exacta del post
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

def publicar_en_facebook(titulo, cuerpo_ia, imagen_url, hashtags="", link_nota=""):
    # Mejoramos el formato: convertimos etiquetas HTML útiles a texto antes de limpiar
    texto_formateado = cuerpo_ia.replace('<li>', '• ').replace('</li>', '\n')
    texto_formateado = texto_formateado.replace('<p>', '').replace('</p>', '\n')
    texto_formateado = texto_formateado.replace('<br>', '\n').replace('<br/>', '\n')
    
    # Limpiamos el resto de etiquetas HTML
    texto_limpio = re.sub('<[^<]+?>', '', texto_formateado)
    texto_fb = "\n\n".join([line.strip() for line in texto_limpio.splitlines() if line.strip()])
    
    # TRUCO ALGORITMO: NUNCA ponemos el link en el cuerpo principal.
    # Anunciamos que el link está en el primer comentario.
    mensaje_final = f"🚨 {titulo}\n\n{texto_fb}\n\n🗣️ ¡Dejanos tu comentario abajo, te leemos!\n👇 (Link de la nota completa en el primer comentario) 👇\n\n{hashtags}"
    
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
            # Obtenemos el ID del post que acabamos de crear
            post_id = resultado.get('post_id') or resultado.get('id')
            
            # Si tenemos el link de Blogger, publicamos un comentario en nuestro propio post
            if post_id and link_nota:
                print("[INFO] Agregando el link en el primer comentario...")
                url_comment = f"https://graph.facebook.com/v19.0/{post_id}/comments"
                comentario_payload = {
                    'message': f"📰 ¡Leé la nota completa con todos los detalles haciendo clic acá! 👇\n{link_nota}",
                    'access_token': FB_PAGE_TOKEN
                }
                requests.post(url_comment, data=comentario_payload)
                
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
    elif "bbc" in url_fuente or "cnn" in url_fuente or "dw.com" in url_fuente:
        return "#Mundo #Internacional #Global #Actualidad"
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
            
        # --- FILTRO DE IMAGEN OBLIGATORIA ---
        if not imagen:
            print(f"[SKIP] La noticia '{entry.title}' no tiene imagen. Buscando otra...")
            continue
            
        # Generar contenido con IA
        nuevo_titulo, cuerpo = transformar_con_ia(entry.title, getattr(entry, 'summary', ''))
        
        # Obtener hashtags según la fuente
        tags = obtener_hashtags(url_rss)
        
        if nuevo_titulo and cuerpo:
            # Intentamos publicar en Blogger
            link_nota = publicar_en_blogger_api(nuevo_titulo, cuerpo, imagen) # Ahora retorna la URL real
            
            if link_nota: # Si devolvió el link, se publicó exitosamente
                print("[OK] Publicado en Blogger")
                publicar_en_facebook(nuevo_titulo, cuerpo, imagen, tags, link_nota=link_nota)
            else:
                print("[ALERTA] Falló Blogger (posible cuota), publicando solo en Facebook...")
                publicar_en_facebook(nuevo_titulo, cuerpo, imagen, tags, link_nota="")

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

        # --- MUNDO GLOBAL E INTERESANTE ---
        "http://feeds.bbci.co.uk/mundo/rss.xml", # BBC Mundo
        "https://cnnespanol.cnn.com/feed/",      # CNN en Español
        "https://rss.dw.com/xml/rss-sp-all",     # DW Español
        
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
    LIMITE_CICLO = 1 # RECOMENDACIÓN: Ejecutar el bot cada 3 o 4 horas (Max 4-6 noticias al día) para no ser SPAM y evitar canibalización.
    
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
        
        
