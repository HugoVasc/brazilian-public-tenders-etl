"""Raspagem de "AVISO DE LICITAÇÃO" (e derivados) no Diário Oficial da União - Seção 3.

A página https://www.in.gov.br/leiturajornal monta os cards (<a> dentro de
<h5 class="title-marker"> e <p class="abstract-marker">) via JavaScript, a partir
de um JSON embutido em <script id="params">. O HTML estático não contém essas
tags, por isso o spider lê esse JSON, que tem exatamente os mesmos dados:
    title    -> texto do <a>
    urlTitle -> href do <a>
    content  -> texto do <p class="abstract-marker">

Uso:
    python scrape_avisos.py                              # 30-09-2026
    python scrape_avisos.py 30-09-2026 05-10-2026        # intervalo (dias subsequentes)
"""
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta

import scrapy
from scrapy import signals
from scrapy.crawler import CrawlerProcess

BASE_URL = "https://www.in.gov.br/leiturajornal?data={data}&secao={secao}"
ARTICLE_URL = "https://www.in.gov.br/web/dou/-/{url_title}"
BRONZE_LAYER_PATH = 'data/bronze/federal_tenders'
# "AVISO DE LICITAÇÃO", "AVISOS DE LICITAÇÃO", "AVISO DE DISPENSA DE LICITAÇÃO",
# "AVISO DE LICITAÇÃO - PREGÃO ELETRÔNICO ..." etc. (comparação sem acentos)
TITLE_RE = re.compile(r"^AVISOS?\b.*\bLICITACA?O", re.IGNORECASE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).strip()


def date_range(start: str, end: str):
    d0 = datetime.strptime(start, "%d-%m-%Y")
    d1 = datetime.strptime(end, "%d-%m-%Y")
    while d0 <= d1:
        yield d0.strftime("%d-%m-%Y")
        d0 += timedelta(days=1)


class AvisoLicitacaoSpider(scrapy.Spider):
    name = "aviso_licitacao"
    custom_settings = {
        "USER_AGENT": "Mozilla/5.0 (compatible; tenders-etl/0.1)",
        # O robots.txt do in.gov.br tem "Disallow: /". Só desative conscientemente:
        #   IGNORE_ROBOTS=1 python scrape_avisos.py
        "ROBOTSTXT_OBEY": not os.environ.get("IGNORE_ROBOTS"),
        "DOWNLOAD_DELAY": 1,
        "LOG_LEVEL": "INFO",
    }

    def __init__(self, start_date="30-09-2026", end_date=None, secao="do3", **kwargs):
        super().__init__(**kwargs)
        self.dates = list(date_range(start_date, end_date or start_date))
        self.secao = secao

    async def start(self):  # Scrapy >= 2.13
        for data in self.dates:
            yield scrapy.Request(BASE_URL.format(data=data, secao=self.secao))

    def start_requests(self):  # Scrapy < 2.13
        for data in self.dates:
            yield scrapy.Request(BASE_URL.format(data=data, secao=self.secao))

    def parse(self, response):
        raw = response.css("script#params::text").get()
        if not raw:
            self.logger.warning("JSON 'params' não encontrado em %s", response.url)
            return
        for art in json.loads(raw).get("jsonArray", []):
            title = art.get("title", "")
            if TITLE_RE.match(normalize(title)):
                yield {
                    "link": ARTICLE_URL.format(url_title=art["urlTitle"]),
                    "conteudo": art.get("content", ""),
                }


def run(start_date="30-09-2026", end_date=None):
    """Executa o spider e devolve uma lista de tuplas (link, conteudo)."""
    resultados = {}

    def collect(item, response, spider):
        resultados[item["link"]] = item["conteudo"]

    process = CrawlerProcess()
    crawler = process.create_crawler(AvisoLicitacaoSpider)
    crawler.signals.connect(collect, signal=signals.item_scraped)
    process.crawl(crawler, start_date=start_date, end_date=end_date)
    process.start()
    return resultados


if __name__ == "__main__":
    os.makedirs(BRONZE_LAYER_PATH, exist_ok=True)
    args = sys.argv[1:]
    avisos = run(*args[:2])
    print(f"\n{len(avisos)} avisos encontrados")
    if len(avisos) > 0:
        with open(f"{BRONZE_LAYER_PATH}/federal_tenders.json", "w") as f:
            json.dump(avisos, f, ensure_ascii=False, indent=2)
    # for link, conteudo in list(avisos.items())[:5]:
    #     print(link, "\n   ", conteudo[:120])
