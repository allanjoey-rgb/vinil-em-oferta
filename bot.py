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

def buscar_ids_sitemap():
    """Busca IDs de discos pelo sitemap XML — sem JavaScript"""
    url = f"{BASE_URL}/sitemap"
    ids = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  Sitemap: status {resp.status_code}, tamanho {len(resp.text)} chars")
        
        # Tenta XML
        soup = BeautifulSoup(resp.text, "xml")
        locs = soup.find_all("loc")
        print(f"  Sitemap XML: {len(locs)} URLs encontradas")
        
        for loc in locs:
            href = loc.get_text(strip=True)
            if "/disco/" in href:
                disco_id = href.split("/disco/")[-1].strip("/")
                if disco_id:
                    ids.append(disco_id)
    except Exception as e:
        print(f"  Erro sitemap: {e}")
    
    print(f"  Total IDs do sitemap: {len(ids)}")
    return ids

def buscar_dados_disco(disco_id):
    """Busca dados de um disco específico pela página JSON do Next.js"""
    # Tenta endpoint JSON do Next.js
    urls_tentar = [
        f"{BASE_URL}/disco/{disco_id}",
    ]
    
    for url in urls_tentar:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            
            html = resp.text
            
            # Procura dados no __NEXT_DATA__ (JSON embutido no HTML pelo Next.js)
            match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
            if match:
                import json
                try:
                    data = json.loads(match.group(1))
                    props = data.get("props", {}).get("pageProps", {})
                    
                    disco = props.get("disco") or props.get("product") or props.get("album") or {}
                    
                    print(f"  Next data keys: {list(props.keys())}")
                    
                    # Tenta extrair campos
                    titulo = disco.get("title") or disco.get("titulo") or disco.get("name") or ""
                    artista = disco.get("artist") or disco.get("artista") or disco.get("author") or ""
                    preco_atual = disco.get("price") or disco.get("preco") or disco.get("currentPrice") or 0
                    preco_original = disco.get("originalPrice") or disco.get("precoOriginal") or 0
                    desconto = disco.get("discount") or disco.get("desconto") or 0
                    img_url = disco.get("image") or disco.get("imagem") or disco.get("thumbnail") or ""
                    amazon_link = disco.get("amazonUrl") or disco.get("link") or disco.get("url") or ""
                    
                    if not titulo:
                        # Fallback: extrai do HTML
                        soup = BeautifulSoup(html, "html.parser")
                        h1 = soup.find("h1")
                        titulo = h1.get_text(strip=True) if h1 else disco_id
                    
                    if desconto >= DESCONTO_MINIMO and preco_atual:
                        return {
                            "id": disco_id,
                            "titulo": titulo,
                            "artista": artista,
                            "preco_original": float(preco_original) if preco_original else None,
                            "preco_atual": float(preco_atual),
                            "desconto": int(desconto),
                            "link": url,
                            "amazon_link": amazon_link,
                            "imagem": img_url,
                        }
                    elif titulo:
                        # Tem dados mas sem desconto suficiente
                        return None
                        
                except json.JSONDecodeError:
                    pass
            
            # Fallback: parse HTML direto
            soup = BeautifulSoup(html, "html.parser")
            texto = soup.get_text(" ")
            
            # Desconto
            match_d = re.search(r'-(\d+)%', texto)
            if not match_d:
                return None
            desconto = int(match_d.group(1))
            if desconto < DESCONTO_MINIMO:
                return None
            
            # Preços
            precos = re.findall(r'R\$\s*([\d]+[.,][\d]+)', texto)
            if len(precos) < 2:
                return None
            
            def to_float(s):
                return float(s.replace(".", "").replace(",", "."))
            
            preco_original = to_float(precos[0])
            preco_atual = to_float(precos[1])
            
            # Título
            h1 = soup.find("h1")
            titulo = h1.get_text(strip=True) if h1 else disco_id
            
            # Artista
            artista = ""
            for p in soup.find_all("p"):
                t = p.get_text(strip=True)
                if t and 2 < len(t) < 60 and "R$" not in t and "%" not in t:
                    artista = t
                    break
            
            # Imagem
            img = soup.find("img", src=re.compile(r'amazon|media'))
            img_url = img.get("src") if img else None
            
            # Amazon link
            amazon = soup.find("a", href=re.compile(r'amazon\.com\.br'))
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
            print(f"  Erro em {url}: {e}")
    
    return None

def buscar_ofertas():
    # Busca IDs pelo sitemap
    ids = buscar_ids_sitemap()
    
    if not ids:
        print("  Sitemap vazio, usando fallback por paginação")
        ids = []
        for pagina in range(1, 6):
            url = f"{BASE_URL}/disco?page={pagina}"
            try:
                resp = requests.get(url, headers=HEADERS, timeout=15)
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r'^/disco/[^/]+$'))
                for l in links:
                    disco_id = l["href"].replace("/disco/", "").strip("/")
                    if disco_id:
                        ids.append(disco_id)
                time.sleep(1)
            except:
                pass
    
    # Filtra já enviados
    ids_novos = []
    seen = set()
    for disco_id in ids:
        if disco_id not in seen and not ja_enviado(disco_id):
            seen.add(disco_id)
            ids_novos.append(disco_id)
    
    print(f"  {len(ids_novos)} discos novos para verificar (max {MAX_DISCOS})")
    
    ofertas = []
    for disco_id in ids_novos[:MAX_DISCOS]:
        dados = buscar_dados_disco(disco_id)
        if dados:
            ofertas.append(dados)
            print(f"  ✓ {dados['titulo']} ({dados['desconto']}% OFF - R${dados['preco_atual']})")
        time.sleep(1.5)
    
    ofertas.sort(key=lambda x: x["desconto"], reverse=True)
    return ofertas

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
