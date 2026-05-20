import requests
import sqlite3
import time
import re
import schedule
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
TELEGRAM_TOKEN = "8510903032:AAFWAM2Wgx9Nle2ZwUyngfICorai_U7WVf0"
TELEGRAM_CHANNEL = "@vinilemoferta"
DESCONTO_MINIMO = 20
MAX_DISCOS = 30
# ============================================================

DB_FILE = "ofertas.db"
BASE_URL = "https://www.garimpavinil.com.br"

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
    except Exception as e:
        print(f"  Erro página {pagina}: {e}")
        return []

def buscar_dados_disco(disco_id):
    url = f"{BASE_URL}/disco/{disco_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        texto = soup.get_text(" ")

        # Desconto — aparece como "↓ 35.5%" na página individual
        match_d = re.search(r'↓\s*([\d.]+)%', texto)
        if not match_d:
            return None
        desconto = round(float(match_d.group(1)))
        if desconto < DESCONTO_MINIMO:
            return None

        # Título — h1
        h1 = soup.find("h1")
        titulo = h1.get_text(strip=True) if h1 else disco_id

        # Artista — primeiro link de artista
        artista_link = soup.find("a", href=re.compile(r'/artista/'))
        artista = artista_link.get_text(strip=True) if artista_link else ""

        # Preço atual — primeiro "R$ X" após o título
        precos = re.findall(r'R\$\s*([\d.,]+)', texto)
        preco_atual = to_float(precos[0]) if precos else None
        preco_original = None

        # Preço original — busca "Média: R$ X"
        match_media = re.search(r'Média:\s*R\$\s*([\d.,]+)', texto)
        if match_media:
            preco_original = to_float(match_media.group(1))

        if not preco_atual:
            return None

        # Imagem
        img = soup.find("img", src=re.compile(r'media-amazon'))
        img_url = img.get("src") if img else None

        # Link Amazon
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

    except Exception as e:
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

def formatar_mensagem(oferta):
    artista = f"👤 {oferta['artista']}\n" if oferta['artista'] else ""
    preco_atual_fmt = f"R$ {oferta['preco_atual']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    preco_original_fmt = ""
    if oferta.get('preco_original'):
        p = f"R$ {oferta['preco_original']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        preco_original_fmt = f"~{p}~\n"

    link = oferta.get("amazon_link") or oferta.get("link")
    msg = (
        f"🎵 *{oferta['titulo']}*\n"
        f"{artista}\n"
        f"🔥 *{oferta['desconto']}% OFF*\n"
        f"{preco_original_fmt}"
        f"💰 *{preco_atual_fmt}*\n\n"
        f"[🛒 Ver oferta]({link})"
    )
    return msg

def enviar_telegram(oferta):
    msg = formatar_mensagem(oferta)
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
        sucesso = enviar_telegram(oferta)
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
    print(f"   Agendado: a cada 20 minutos\n")

    executar()

    schedule.every(20).minutes.do(executar)
    while True:
        schedule.run_pending()
        time.sleep(60)
