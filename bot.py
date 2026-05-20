import requests
import sqlite3
import time
import schedule
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURAÇÕES
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
        return float(texto.replace("R$", "").replace(".", "").replace(",", ".").strip())
    except:
        return None

def buscar_ofertas():
    ofertas = []

    for pagina in range(1, PAGINAS + 1):
        url = f"{BASE_URL}/disco?page={pagina}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            print(f"  Página {pagina}: status {resp.status_code}")
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            # Busca todos os links de disco
            links = soup.find_all("a", href=True)
            disco_links = [l for l in links if "/disco/" in l.get("href", "") and l.get("href", "").count("/") >= 2]

            print(f"  Página {pagina}: {len(disco_links)} links de disco encontrados")

            for card in disco_links:
                try:
                    href = card.get("href", "")
                    disco_id = href.split("/disco/")[-1].strip("/")
                    if not disco_id or ja_enviado(disco_id):
                        continue

                    texto_completo = card.get_text(" ", strip=True)

                    # Desconto
                    desconto = None
                    import re
                    match = re.search(r'-(\d+)%', texto_completo)
                    if match:
                        desconto = int(match.group(1))
                    if not desconto or desconto < DESCONTO_MINIMO:
                        continue

                    # Título
                    titulo_el = card.find(["h2", "h3", "h4"])
                    titulo = titulo_el.get_text(strip=True) if titulo_el else "Sem título"

                    # Artista
                    paragrafos = card.find_all("p")
                    artista = paragrafos[0].get_text(strip=True) if paragrafos else ""

                    # Preços
                    precos_texto = re.findall(r'R\$\s*[\d.,]+', texto_completo)
                    preco_original = parse_preco(precos_texto[0]) if len(precos_texto) > 0 else None
                    preco_atual = parse_preco(precos_texto[1]) if len(precos_texto) > 1 else None

                    # Imagem
                    img = card.find("img")
                    img_url = img.get("src") if img else None

                    # Link Amazon
                    amazon_links = card.find_all("a", href=lambda h: h and "amazon.com.br" in h)
                    amazon_link = amazon_links[0]["href"] if amazon_links else None

                    if titulo and preco_atual:
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

            time.sleep(2)

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
    if oferta.get('preco_original'):
        preco_original_fmt = f"~R$ {oferta['preco_original']:,.2f}~\n".replace(",", "X").replace(".", ",").replace("X", ".")

    link = oferta.get("amazon_link") or oferta.get("link")

    msg = (
        f"🎵 *{oferta['titulo']}*\n"
        f"{artista}"
        f"\n"
        f"🔥 *{oferta['desconto']}% OFF*\n"
        f"{preco_original_fmt}"
        f"💰 *{preco_atual_fmt}*\n"
        f"\n"
        f"[🛒 Ver oferta]({link})"
    )
    return msg

def enviar_telegram(oferta):
    msg = formatar_mensagem(oferta)
    imagem = oferta.get("imagem")

    if imagem:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
        payload = {
            "chat_id": TELEGRAM_CHANNEL,
            "photo": imagem,
            "caption": msg,
            "parse_mode": "Markdown"
        }
    else:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHANNEL,
            "text": msg,
            "parse_mode": "Markdown"
        }

    resp = requests.post(url, json=payload, timeout=10)
    if resp.status_code != 200:
        print(f"  Telegram erro: {resp.text}")
    return resp.status_code == 200

def executar():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Buscando ofertas...")
    ofertas = buscar_ofertas()

    enviados = 0
    for oferta in ofertas:
        sucesso = enviar_telegram(oferta)
        if sucesso:
            marcar_enviado(oferta["id"], oferta["titulo"], oferta["preco_atual"], oferta["desconto"])
            enviados += 1
            print(f"  ✓ {oferta['titulo']} ({oferta['desconto']}% OFF)")
            time.sleep(3)
        else:
            print(f"  ✗ Falha: {oferta['titulo']}")

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
