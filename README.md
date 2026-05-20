# 🎵 Vinil em Oferta — Bot Telegram

Bot que monitora o Garimpa Vinil e envia automaticamente as melhores ofertas de discos pro seu canal no Telegram.

## Instalação local

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Rodar o bot
python bot.py
```

## Deploy no Render (gratuito)

1. Cria conta em https://render.com
2. Conecta com GitHub
3. Cria um novo repositório e sobe os arquivos (bot.py, requirements.txt)
4. No Render: New → Background Worker
5. Build Command: `pip install -r requirements.txt`
6. Start Command: `python bot.py`
7. Deploy!

## Configurações (dentro do bot.py)

| Variável | Padrão | Descrição |
|---|---|---|
| `TELEGRAM_TOKEN` | seu token | Token do @BotFather |
| `TELEGRAM_CHANNEL` | @vinilemoferta | Username do canal |
| `DESCONTO_MINIMO` | 20 | % mínimo de desconto |
| `PAGINAS` | 5 | Páginas do Garimpa Vinil a buscar |

## Como funciona

1. A cada 4 horas, busca as primeiras 5 páginas do Garimpa Vinil
2. Filtra discos com 20%+ de desconto
3. Verifica no banco local (SQLite) se já foi enviado
4. Envia foto + texto formatado pro canal
5. Marca como enviado pra não repetir
