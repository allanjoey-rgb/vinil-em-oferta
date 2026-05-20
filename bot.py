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
PAGINAS = 5
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

def parse_preco(texto):
    try:
        limpo = texto.replace("R$", "").replace("\xa0", "").strip()
        limpo = limpo.replace(".", "").replace(",", ".")
        return float(limpo)
    except:
        return None

def buscar_ofertas():
    ofertas = []

    for pagina in range(1, PAGINAS + 1):
        url = f"{BASE_URL}/disco?page={pagina}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                print(f"  Página {pagina}: erro {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            texto_pagina = resp.text

            # Debug: mostra trecho do HTML pra entender estrutura
            if pagina == 1:
                # Procura qualquer menção a desconto
                matches = re.findall(r'.{50}-\d+%.{50}', texto_pagina)
                print(f"  Exemplos de desconto no HTML: {matches[:2]}")
                
                # Procura preços
                precos = re.findall(r'R\$\s*[\d.,]+', texto_pagina)
                print(f"  Exemplos de preço: {precos[:4]}")

            # Tenta extrair blocos por âncora de disco
            # Cada disco tem um link /disco/SLUG e dados próximos
            blocos = re.findall(
                r'href="(/disco/([^"]+))"[^}]*?(-\d+%)[^}]*?(R\$[\s\d.,]+)[^}]*?(R\$[\s\d.,]+)',
                texto_pagina
            )
            print(f"  Página {pagina}: {len(blocos)} blocos encontrados via regex")

            for bloco in blocos:
                href, disco_id, desconto_str, preco1_str, preco2_str = bloco
                try:
                    desconto = int(desconto_str.replace("-", "").replace("%", ""))
                    if desconto < DESCONTO_MINIMO:
                        continue
                    if ja_enviado(disco_id):
                        continue

                    preco_original = parse_preco(preco1_str)
                    preco_atual = parse_preco(preco2_str)

                    if not preco_atual:
                        continue

                    # Busca título e artista próximos ao href no HTML
                    idx = texto_pagina.find(f'href="{href}"')
                    trecho = texto_pagina[idx:idx+800] if idx >= 0 else ""
                    
                    titulo_match = re.search(r'<h2[^>]*>([^<]+)</h2>', trecho)
                    titulo = titulo_match.group(1).strip() if titulo_match else disco_id

                    artista_match = re.search(r'<p[^>]*>([^<]{2,60})</p>', trecho)
                    artista = artista_match.group(1).strip() if artista_match else ""

                    img_match = re.search(r'src="(https://m\.media-amazon[^"]+)"', trecho)
                    img_url = img_match.group(1) if img_match else None

                    amazon_match = re.search(r'href="(https://www\.amazon\.com\.br[^"]+)"', trecho)
                    amazon_link = amazon_match.group(1) if amazon_match else f"{BASE_URL}{href}"

                    ofertas.append({
                        "id": disco_id,
                        "titulo": titulo,
                        "artista": artista,
                        "preco_original": preco_original,
                        "preco_atual": preco_atual,
                        "desconto": desconto,
                        "link": f"{BASE_URL}{href}",
                        "amazon_link": amazon_link,
                        "imagem": img_url,
                    })
                except Exception as e:
                    continue

            time.sleep(1)

        except Exception as e:
            print(f"  Erro na página {pagina}: {e}")

    # Deduplica e ordena
    seen = set()
    unicas = []
    for o in ofertas:
        if o["id"] not in seen:
            seen.add(o["id"])
            unicas.append(o)

    unicas.sort(key=lambda x: x["desconto"], reverse=True)
    print(f"  Total de ofertas novas: {len(unicas)}")
    return unicas

def formatar_mensagem(oferta):
    artista = f"👤 {oferta['artista']}\n" if oferta['artista'] else ""
    preco_atual_fmt = f"R$ {oferta['preco_atual']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    preco_original_fmt = ""
    if oferta.get('preco_original') and oferta['preco_original'] != oferta['preco_atual']:
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
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {"chat_id": TELEGRAM_CHANNEL, "photo": imagem, "caption": msg, "parse_mode": "Markdown"}
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHANNEL, "text": msg, "parse_mode": "Markdown"}

    resp = requests.post(url, json=payload, timeout=10)
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
