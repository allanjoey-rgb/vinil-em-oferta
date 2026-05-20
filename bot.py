import requests
import sqlite3
import time
import re
import schedule
from datetime import datetime
from bs4 import BeautifulSoup
import base64

# ============================================================
TELEGRAM_TOKEN = "8510903032:AAFWAM2Wgx9Nle2ZwUyngfICorai_U7WVf0"
TELEGRAM_CHANNEL = "@vinilemoferta"
DESCONTO_MINIMO = 20
MAX_DISCOS = 50
SPOTIFY_CLIENT_ID = "a71df3a013bc4e13bc802d9085937a28"
SPOTIFY_CLIENT_SECRET = "cc903c8455884f45b9aa2a3b0f1ad8e3"
# ============================================================

DB_FILE = "ofertas.db"
BASE_URL = "https://www.garimpavinil.com.br"
spotify_token = None
spotify_token_expires = 0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS enviados (
            id TEXT PRIMARY KEY,
            titulo TEXT,
            preco REAL,
            desconto INTEGER,
            enviado_em TEXT
        )
    """)
    conn.commit()
    conn.close()

def ja_enviado(disco_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT id FROM enviados WHERE id = ?", (disco_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def marcar_enviado(disco_id, titulo, preco, desconto):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO enviados VALUES (?, ?, ?, ?, ?)",
        (disco_id, titulo, preco, desconto, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def to_float(s):
    try:
        return float(s.replace(".", "").replace(",", ".").strip())
    except:
        return None

# ── Spotify ──────────────────────────────────────────────────

def get_spotify_token():
    global spotify_token, spotify_token_expires
    if spotify_token and time.time() < spotify_token_expires:
        return spotify_token
    creds = base64.b64encode(f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={"Authorization": f"Basic {creds}"},
        data={"grant_type": "client_credentials"},
        timeout=10
    )
    if resp.status_code == 200:
        data = resp.json()
        spotify_token = data["access_token"]
        spotify_token_expires = time.time() + data["expires_in"] - 60
        return spotify_token
    return None

def buscar_spotify(titulo, artista):
    try:
        token = get_spotify_token()
        if not token:
            return None

        # Busca o álbum específico
        for query in [
            f"album:{titulo} artist:{artista}",
            f"{titulo} {artista}",
            titulo
        ]:
            resp = requests.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": query, "type": "album", "limit": 1, "market": "BR"},
                timeout=10
            )
            if resp.status_code != 200:
                continue
            items = resp.json().get("albums", {}).get("items", [])
            if items:
                album = items[0]
                return {
                    "url": album["external_urls"]["spotify"],
                    "ano": album.get("release_date", "")[:4],
                    "nome_album": album.get("name", titulo),
                    "nome_artista": album["artists"][0]["name"] if album.get("artists") else artista,
                }

        return None
    except Exception as e:
        print(f"  Spotify erro: {e}")
        return None

# ── Descrição via Claude ──────────────────────────────────────

def gerar_descricao(titulo, artista, ano):
    try:
        prompt = (
            f"Escreva 2 frases curtas e envolventes sobre o álbum '{titulo}' de {artista}"
            + (f", lançado em {ano}" if ano else "")
            + ". Destaque algo marcante: contexto histórico, curiosidade, impacto cultural ou por que vale a pena ouvir. "
            + "Seja direto, sem introdução. Escreva em português brasileiro."
        )

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json"},
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 150,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=15
        )

        if resp.status_code == 200:
            return resp.json()["content"][0]["text"].strip()
        return None
    except Exception as e:
        print(f"  Claude erro: {e}")
        return None

# ── Garimpa Vinil ────────────────────────────────────────────

def buscar_ids_pagina(pagina):
    url = f"{BASE_URL}/disco?page={pagina}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.find_all("a", href=re.compile(r'^/disco/[^/]+$'))
        ids = []
        seen = set()
        for l in links:
            disco_id = l["href"].replace("/disco/", "").strip("/")
            if disco_id and disco_id not in seen:
                seen.add(disco_id)
                ids.append(disco_id)
        return ids
    except:
        return []

def buscar_dados_disco(disco_id):
    url = f"{BASE_URL}/disco/{disco_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        texto = soup.get_text(" ")

        match_d = re.search(r'↓\s*([\d.]+)%', texto)
        if not match_d:
            return None
        desconto = round(float(match_d.group(1)))
        if desconto < DESCONTO_MINIMO:
            return None

        h1 = soup.find("h1")
        titulo = h1.get_text(strip=True) if h1 else disco_id

        artista_link = soup.find("a", href=re.compile(r'/artista/'))
        artista = artista_link.get_text(strip=True) if artista_link else ""

        precos = re.findall(r'R\$\s*([\d.,]+)', texto)
        preco_atual = to_float(precos[0]) if precos else None

        match_media = re.search(r'Média:\s*R\$\s*([\d.,]+)', texto)
        preco_original = to_float(match_media.group(1)) if match_media else None

        if not preco_atual:
            return None

        img = soup.find("img", src=re.compile(r'media-amazon'))
        img_url = img.get("src") if img else None

        amazon = soup.find("a", href=re.compile(r'amazon\.com\.br/dp/'))
        amazon_link = amazon.get("href") if amazon else url

        return {
            "id": disco_id,
            "titulo": titulo,
            "artista": artista,
            "preco_original": preco_original,
            "preco_atual": preco_atual,
            "desconto": desconto,
            "link": url,
            "amazon_link": amazon_link,
            "imagem": img_url,
        }
    except:
        return None

def buscar_ofertas():
    todos_ids = []
    for pagina in range(1, 6):
        ids = buscar_ids_pagina(pagina)
        print(f"  Página {pagina}: {len(ids)} discos")
        todos_ids.extend(ids)
        time.sleep(1)

    ids_novos = []
    seen = set()
    for disco_id in todos_ids:
        if disco_id not in seen and not ja_enviado(disco_id):
            seen.add(disco_id)
            ids_novos.append(disco_id)

    print(f"  {len(ids_novos)} discos novos — verificando {min(len(ids_novos), MAX_DISCOS)}")

    ofertas = []
    for disco_id in ids_novos[:MAX_DISCOS]:
        dados = buscar_dados_disco(disco_id)
        if dados:
            ofertas.append(dados)
            print(f"  ✓ {dados['titulo']} ({dados['desconto']}% OFF)")
        time.sleep(1.5)

    ofertas.sort(key=lambda x: x["desconto"], reverse=True)
    return ofertas

# ── Mensagem ─────────────────────────────────────────────────

def formatar_mensagem(oferta, spotify=None, descricao=None):
    artista = f"👤 {oferta['artista']}" if oferta['artista'] else ""
    preco_atual_fmt = f"R$ {oferta['preco_atual']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    preco_original_fmt = ""
    if oferta.get('preco_original'):
        p = f"R$ {oferta['preco_original']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        preco_original_fmt = f"~{p}~ → "

    amazon_link = oferta.get("amazon_link") or oferta.get("link")

    desc_bloco = f"\n\n_{descricao}_" if descricao else ""

    spotify_bloco = ""
    if spotify:
        spotify_bloco = f"\n\n[▶️ Ouvir no Spotify]({spotify['url']})"

    msg = (
        f"🎵 *{oferta['titulo']}*\n"
        f"{artista}"
        f"{desc_bloco}\n\n"
        f"🔥 *{oferta['desconto']}% OFF*\n"
        f"💰 {preco_original_fmt}*{preco_atual_fmt}*"
        f"{spotify_bloco}\n"
        f"[🛒 Comprar na Amazon]({amazon_link})"
    )
    return msg

def enviar_telegram(oferta, spotify=None, descricao=None):
    msg = formatar_mensagem(oferta, spotify, descricao)
    imagem = oferta.get("imagem")

    if imagem:
        url_api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {"chat_id": TELEGRAM_CHANNEL, "photo": imagem, "caption": msg, "parse_mode": "Markdown"}
    else:
        url_api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHANNEL, "text": msg, "parse_mode": "Markdown"}

    resp = requests.post(url_api, json=payload, timeout=10)
    if resp.status_code != 200:
        print(f"  Telegram erro: {resp.text}")
    return resp.status_code == 200

def executar():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Buscando ofertas...")
    ofertas = buscar_ofertas()
    print(f"  {len(ofertas)} oferta(s) com desconto >= {DESCONTO_MINIMO}%")

    enviados = 0
    for oferta in ofertas:
        spotify = buscar_spotify(oferta['titulo'], oferta['artista'])
        ano = spotify['ano'] if spotify else ""
        descricao = gerar_descricao(oferta['titulo'], oferta['artista'], ano)
        sucesso = enviar_telegram(oferta, spotify, descricao)
        if sucesso:
            marcar_enviado(oferta["id"], oferta["titulo"], oferta["preco_atual"], oferta["desconto"])
            enviados += 1
            time.sleep(3)

    print(f"  Total enviado: {enviados}")

if __name__ == "__main__":
    init_db()
    print("🎵 Vinil em Oferta — Bot iniciado")
    print(f"   Desconto mínimo: {DESCONTO_MINIMO}%")
    print(f"   Canal: {TELEGRAM_CHANNEL}")
    print(f"   Agendado: a cada 3 horas\n")

    executar()

    schedule.every(3).hours.do(executar)
    while True:
        schedule.run_pending()
        time.sleep(60)
