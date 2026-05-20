import requests
import sqlite3
import json
import time
import schedule
from datetime import datetime

# ============================================================
# CONFIGURAÇÕES — edite aqui
# ============================================================
TELEGRAM_TOKEN = "8510903032:AAFWAM2Wgx9Nle2ZwUyngfICorai_U7WVf0"
TELEGRAM_CHANNEL = "@vinilemoferta"
DESCONTO_MINIMO = 20  # % mínimo de desconto
PAGINAS = 5           # quantas páginas do Garimpa Vinil buscar
# ============================================================

DB_FILE = "ofertas.db"
BASE_URL = "https://www.garimpavinil.com.br"

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

def buscar_ofertas():
    ofertas = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for pagina in range(1, PAGINAS + 1):
        url = f"{BASE_URL}/disco?page={pagina}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                print(f"Erro na página {pagina}: status {resp.status_code}")
                continue

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")

            # Busca cards de disco
            cards = soup.find_all("a", href=lambda h: h and "/disco/" in h)

            for card in cards:
                try:
                    # Desconto
                    badge = card.find(string=lambda t: t and "%" in t)
                    if not badge:
                        continue
                    desconto_str = badge.strip().replace("-", "").replace("%", "")
                    desconto = int(desconto_str)
                    if desconto < DESCONTO_MINIMO:
                        continue

                    # Título
                    titulo_el = card.find("h2") or card.find("h3")
                    titulo = titulo_el.get_text(strip=True) if titulo_el else "Sem título"

                    # Artista
                    artista_els = card.find_all("p")
                    artista = artista_els[0].get_text(strip=True) if artista_els else ""

                    # Preços
                    precos = card.find_all(string=lambda t: t and "R$" in t)
                    preco_original = None
                    preco_atual = None
                    for p in precos:
                        val = p.strip().replace("R$", "").replace(".", "").replace(",", ".").strip()
                        try:
                            val_float = float(val)
                            if preco_original is None:
                                preco_original = val_float
                            else:
                                preco_atual = val_float
                                break
                        except:
                            continue

                    # Link Amazon
                    amazon_link = None
                    amazon_tag = card.find("a", href=lambda h: h and "amazon.com.br" in h)
                    if amazon_tag:
                        amazon_link = amazon_tag["href"]

                    # ID único baseado no href
                    disco_id = card["href"].split("/disco/")[-1].strip("/")

                    # Imagem
                    img = card.find("img")
                    img_url = img["src"] if img and img.get("src") else None

                    if preco_atual and not ja_enviado(disco_id):
                        ofertas.append({
                            "id": disco_id,
                            "titulo": titulo,
                            "artista": artista,
                            "preco_original": preco_original,
                            "preco_atual": preco_atual,
                            "desconto": desconto,
                            "link": f"{BASE_URL}{card['href']}",
                            "amazon_link": amazon_link,
                            "imagem": img_url,
                        })
                except Exception as e:
                    continue

            time.sleep(1)  # respeita o servidor

        except Exception as e:
            print(f"Erro ao buscar página {pagina}: {e}")

    # Remove duplicatas por ID
    seen = set()
    unicas = []
    for o in ofertas:
        if o["id"] not in seen:
            seen.add(o["id"])
            unicas.append(o)

    # Ordena por maior desconto
    unicas.sort(key=lambda x: x["desconto"], reverse=True)
    return unicas

def formatar_mensagem(oferta):
    artista = f"👤 {oferta['artista']}\n" if oferta['artista'] else ""
    preco_original = f"~~R$ {oferta['preco_original']:,.2f}~~".replace(",", "X").replace(".", ",").replace("X", ".") if oferta['preco_original'] else ""
    preco_atual = f"R$ {oferta['preco_atual']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    link = oferta.get("amazon_link") or oferta.get("link")

    msg = (
        f"🎵 *{oferta['titulo']}*\n"
        f"{artista}"
        f"\n"
        f"🔥 *{oferta['desconto']}% OFF*\n"
        f"{preco_original}\n"
        f"💰 *{preco_atual}*\n"
        f"\n"
        f"[🛒 Ver na Amazon]({link})"
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
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }

    resp = requests.post(url, json=payload, timeout=10)
    return resp.status_code == 200

def executar():
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Buscando ofertas...")
    ofertas = buscar_ofertas()
    print(f"  {len(ofertas)} oferta(s) nova(s) encontrada(s)")

    enviados = 0
    for oferta in ofertas:
        sucesso = enviar_telegram(oferta)
        if sucesso:
            marcar_enviado(oferta["id"], oferta["titulo"], oferta["preco_atual"], oferta["desconto"])
            enviados += 1
            print(f"  ✓ Enviado: {oferta['titulo']} ({oferta['desconto']}% OFF)")
            time.sleep(3)  # pausa entre mensagens
        else:
            print(f"  ✗ Falha ao enviar: {oferta['titulo']}")

    print(f"  Total enviado: {enviados}")

if __name__ == "__main__":
    init_db()
    print("🎵 Vinil em Oferta — Bot iniciado")
    print(f"   Desconto mínimo: {DESCONTO_MINIMO}%")
    print(f"   Canal: {TELEGRAM_CHANNEL}")
    print(f"   Agendado: a cada 4 horas\n")

    # Roda imediatamente na primeira vez
    executar()

    # Agenda a cada 4 horas
    schedule.every(4).hours.do(executar)
    while True:
        schedule.run_pending()
        time.sleep(60)
