import requests
import sqlite3
import time
import re
import schedule
from datetime import datetime
from bs4 import BeautifulSoup
import base64
import random

# ============================================================
import os
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8510903032:AAFWAM2Wgx9Nle2ZwUyngfICorai_U7WVf0")
TELEGRAM_CHANNEL = "@vinilemoferta"
DESCONTO_MINIMO = 20
MAX_DISCOS = 20
SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "a71df3a013bc4e13bc802d9085937a28")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "cc903c8455884f45b9aa2a3b0f1ad8e3")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ESTILOS = ["rock", "jazz", "pop", "classical", "hip-hop", "blues", "electronic", "soul", "folk", "samba", "mpb"]
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            chave TEXT PRIMARY KEY,
            valor TEXT
        )
    """)
    c.execute("INSERT OR IGNORE INTO config VALUES ('rodada', '0')")
    conn.commit()
    conn.close()

def get_rodada():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT valor FROM config WHERE chave = 'rodada'")
    result = c.fetchone()
    conn.close()
    return int(result[0]) if result else 0

def avancar_rodada():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    rodada_atual = get_rodada()
    nova_rodada = (rodada_atual + 1) % 3
    c.execute("UPDATE config SET valor = ? WHERE chave = 'rodada'", (str(nova_rodada),))
    conn.commit()
    conn.close()
    return nova_rodada

def ja_enviado(disco_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Bloqueia por 7 dias — depois pode aparecer de novo se ainda estiver em oferta
    c.execute("""
        SELECT id FROM enviados 
        WHERE id = ? AND enviado_em > datetime('now', '-2 days')
    """, (disco_id,))
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

def limpar_titulo(titulo):
    """Remove sufixos de edição que atrapalham a busca"""
    import re
    titulo = re.sub(r'\[.*?\]', '', titulo)  # Remove [LP], [2LP], [Disco de Vinil] etc
    titulo = re.sub(r'\(.*?\)', '', titulo)  # Remove (Remaster), (Edition) etc
    titulo = titulo.strip()
    return titulo

def buscar_spotify(titulo, artista):
    try:
        token = get_spotify_token()
        if not token:
            return None

        titulo_limpo = limpar_titulo(titulo)
        artista_limpo = artista.strip()

        queries = []
        if artista_limpo:
            queries.append(f"album:{titulo_limpo} artist:{artista_limpo}")
            queries.append(f"{titulo_limpo} {artista_limpo}")
        queries.append(titulo_limpo)

        for query in queries:
            resp = requests.get(
                "https://api.spotify.com/v1/search",
                headers={"Authorization": f"Bearer {token}"},
                params={"q": query, "type": "album", "limit": 5, "market": "BR"},
                timeout=10
            )
            if resp.status_code != 200:
                continue
            items = resp.json().get("albums", {}).get("items", [])
            if not items:
                continue

            # Tenta encontrar o melhor match pelo nome do artista
            for album in items:
                album_artista = album["artists"][0]["name"].lower() if album.get("artists") else ""
                album_nome = album.get("name", "").lower()
                titulo_lower = titulo_limpo.lower()
                artista_lower = artista_limpo.lower()

                # Match exato de artista ou título similar
                if (artista_lower and artista_lower in album_artista) or                    (artista_lower and album_artista in artista_lower) or                    titulo_lower in album_nome:
                    return {
                        "url": album["external_urls"]["spotify"],
                        "ano": album.get("release_date", "")[:4],
                        "nome_album": album.get("name", titulo),
                        "nome_artista": album["artists"][0]["name"] if album.get("artists") else artista,
                    }

            # Fallback: primeiro resultado
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
            headers={
                "Content-Type": "application/json",
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-haiku-4-5-20251001",
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

def buscar_ids_url(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return []
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

def buscar_ids_pagina(pagina):
    return buscar_ids_url(f"{BASE_URL}/disco?page={pagina}")

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
        if amazon_link and "amazon.com.br" in amazon_link:
            sep = "&" if "?" in amazon_link else "?"
            amazon_link = f"{amazon_link}{sep}tag=groovesemfim-20"

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

def buscar_umusic():
    """Busca ofertas na Universal Music Store"""
    ofertas = []
    url = "https://www.umusicstore.com/lp---vinil/vinil-ate-50--off---frete-fixo?map=category-2,productclusternames&order=OrderByBestDiscountDESC"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  UMusic: erro {resp.status_code}")
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        texto = resp.text
        
        # Extrai produtos via regex do HTML
        import re as _re
        # Padrão: título, artista, preço original, preço atual, desconto, link
        produtos = _re.findall(
            r'href="(https://www\.umusicstore\.com/[^"]+/p)"[^>]*>.*?'
            r'R\$\s*([\d.,]+).*?R\$\s*([\d.,]+).*?(\d+)%\s*OFF',
            texto, _re.DOTALL
        )
        
        print(f"  UMusic: {len(produtos)} produtos encontrados")
        
        seen = set()
        for produto in produtos:
            try:
                link, preco_orig_str, preco_atual_str, desconto_str = produto
                desconto = int(desconto_str)
                if desconto < DESCONTO_MINIMO:
                    continue
                
                # ID único baseado no link
                disco_id = "umusic_" + link.split("/")[-2]
                if disco_id in seen or ja_enviado(disco_id):
                    continue
                seen.add(disco_id)
                
                preco_original = float(preco_orig_str.replace(".", "").replace(",", "."))
                preco_atual = float(preco_atual_str.replace(".", "").replace(",", "."))
                
                # Busca título e artista pelo contexto no HTML
                idx = texto.find(link)
                trecho = texto[max(0, idx-500):idx+200]
                
                # Título — geralmente "Vinil Artista - Album"
                titulo_match = _re.search(r'Vinil\s+([^<"]+?)\s*(?:R\$|$)', trecho)
                titulo_raw = titulo_match.group(1).strip() if titulo_match else disco_id
                
                # Separa artista e título
                partes = titulo_raw.split(" - ", 1)
                artista = partes[0].replace("Vinil ", "").strip() if len(partes) > 1 else ""
                titulo = partes[1].strip() if len(partes) > 1 else titulo_raw
                
                # Remove sufixos como (LP), (2LP), - Importado, - Nacional
                titulo = _re.sub(r'\s*[\(\[][^\)\]]+[\)\]]', '', titulo).strip()
                titulo = _re.sub(r'\s*-\s*(Importado|Nacional|LP|2LP).*$', '', titulo).strip()
                
                # Imagem
                img_match = _re.search(r'src="(https://universalmusic\.vtexassets\.com[^"]+)"', trecho)
                img_url = img_match.group(1) if img_match else None
                
                # Link com afiliado (sem afiliado Amazon pois é loja própria)
                amazon_link = link
                
                ofertas.append({
                    "id": disco_id,
                    "titulo": titulo,
                    "artista": artista,
                    "preco_original": preco_original,
                    "preco_atual": preco_atual,
                    "desconto": desconto,
                    "link": link,
                    "amazon_link": link,
                    "imagem": img_url,
                    "fonte": "UMusic"
                })
            except Exception as e:
                continue
    except Exception as e:
        print(f"  UMusic erro: {e}")
    
    return ofertas

def buscar_ofertas():
    todos_ids = []
    
    # Fonte 1: artistas mais ouvidos (Garimpa Vinil)
    ids_mais_ouvidos = buscar_ids_url(f"{BASE_URL}/artistas-mais-ouvidos")
    print(f"  Mais ouvidos: {len(ids_mais_ouvidos)} discos")
    todos_ids.extend(ids_mais_ouvidos)
    time.sleep(1)
    
    # Complementa com estilos rotacionados
    rodada = get_rodada()
    estilos_rodada = ESTILOS[rodada % len(ESTILOS):] + ESTILOS[:rodada % len(ESTILOS)]
    for estilo in estilos_rodada[:2]:
        ids = buscar_ids_url(f"{BASE_URL}/estilo/{estilo}?page=1")
        print(f"  Estilo {estilo}: {len(ids)} discos")
        todos_ids.extend(ids)
        time.sleep(1)
    
    # Fonte 2: Universal Music Store
    ofertas_umusic = buscar_umusic()
    print(f"  UMusic: {len(ofertas_umusic)} ofertas com desconto")

    ids_novos = []
    seen = set()
    for disco_id in todos_ids:
        if disco_id not in seen and not ja_enviado(disco_id):
            seen.add(disco_id)
            ids_novos.append(disco_id)

    print(f"  {len(ids_novos)} discos novos — verificando {min(len(ids_novos), MAX_DISCOS)}")

    ofertas = []
    # Garimpa Vinil
    for disco_id in ids_novos[:MAX_DISCOS]:
        dados = buscar_dados_disco(disco_id)
        if dados:
            ofertas.append(dados)
            print(f"  ✓ {dados['titulo']} ({dados['desconto']}% OFF)")
        time.sleep(1.5)
    
    # Universal Music Store — adiciona as que cabem no limite
    slots_restantes = MAX_DISCOS - len(ofertas)
    if slots_restantes > 0:
        ofertas.extend(ofertas_umusic[:slots_restantes])

    rodada = get_rodada()
    
    if rodada == 0:
        # Maior desconto
        print(f"  Estratégia: maior desconto")
        ofertas.sort(key=lambda x: x["desconto"], reverse=True)
    elif rodada == 1:
        # Menor preço
        print(f"  Estratégia: menor preço")
        ofertas.sort(key=lambda x: x["preco_atual"])
    else:
        # Aleatório
        print(f"  Estratégia: aleatório")
        random.shuffle(ofertas)
    
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

    # Chamada pra ação baseada no desconto — varia a cada post
    import random as _rnd
    if oferta['desconto'] >= 40:
        cta = _rnd.choice([
            "⚡ Desconto raro — corre antes que suba!",
            "🚨 Esse preço não dura. Aproveita agora!",
            "🔥 Um dos maiores descontos que vimos nesse disco.",
            "⏳ Histórico mostra que sobe rápido. Não deixa passar.",
            "💥 Oferta fora do comum. Sério.",
        ])
    elif oferta['desconto'] >= 30:
        cta = _rnd.choice([
            "👉 Preço bem abaixo da média. Vale muito.",
            "🎯 Boa hora pra adicionar esse à coleção.",
            "📉 Caiu bastante. Momento certo pra comprar.",
            "🛒 Desconto consistente — tá valendo sim.",
            "✅ Preço histórico bom. Não precisa esperar mais.",
        ])
    else:
        cta = _rnd.choice([
            "🎯 Preço abaixo da média histórica.",
            "💡 Tá com desconto. Vale conferir.",
            "📊 Desconto real, não é fumaça.",
            "👀 Melhor preço dos últimos tempos.",
            "🎵 Bom momento pra garantir esse.",
        ])

    msg = (
        f"🎵 *{oferta['titulo']}*\n"
        f"{artista}"
        f"{desc_bloco}\n\n"
        f"🔥 *{oferta['desconto']}% OFF*\n"
        f"💰 {preco_original_fmt}*{preco_atual_fmt}*"
        f"{spotify_bloco}\n"
        f"[🛒 {'Comprar na Universal Music' if oferta.get('fonte') == 'UMusic' else 'Comprar na Amazon'}]({amazon_link})\n\n"
        f"{cta}\n"
        f"📲 [instagram.com/groovesemfim](https://instagram.com/groovesemfim)"
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

    avancar_rodada()
    print(f"  Total enviado: {enviados}")

from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'Vinil em Oferta - Bot rodando!')
    def log_message(self, format, *args):
        pass

def iniciar_servidor():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), Handler)
    server.serve_forever()

if __name__ == "__main__":
    init_db()
    print("🎵 Vinil em Oferta — Bot iniciado")
    print(f"   Desconto mínimo: {DESCONTO_MINIMO}%")
    print(f"   Canal: {TELEGRAM_CHANNEL}")
    print(f"   Agendado: a cada 3 horas\n")

    t = threading.Thread(target=iniciar_servidor, daemon=True)
    t.start()

    executar()

    schedule.every(3).hours.do(executar)
    while True:
        schedule.run_pending()
        time.sleep(60)
