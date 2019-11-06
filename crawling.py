import asyncio
import cgi
import re
import time
import urllib.parse
from asyncio import Queue
from collections import namedtuple

import aiohttp


def is_redirect(response):
    return response.status in (300, 301, 302, 303, 307)


FetchStatistic = namedtuple('FetchStatistic', [
    'url', 'next_url', 'status', 'exception', 'size', 'content_type',
    'encoding', 'num_urls', 'num_new_urls'
])


class Crawler(object):
    def __init__(self,
                 url,
                 max_redirect=10,
                 max_tries=4,
                 max_tasks=10,
                 loop=None,
                 host=None):
        self.loop = loop or asyncio.get_event_loop()
        self.max_redirect = max_redirect
        self.max_tries = max_tries
        self.max_tasks = max_tasks
        self.q = Queue(loop=self.loop)
        self.seen_urls = set()
        self.done = []
        self.session = aiohttp.ClientSession(loop=self.loop)
        self.t0 = time.time()
        self.t1 = None
        self.host = host

        self.add_url(url)

    async def close(self):
        await self.session.close()

    def url_allowed(self, url):
        parts = urllib.parse.urlparse(url)
        if parts.scheme not in ('http', 'https'):
            return False

        if parts.netloc != self.host:
            return False

        return True

    def record_statistic(self, fetch_statistic):
        self.done.append(fetch_statistic)

    async def parse_links(self, response):
        links = set()
        content_type = None
        encoding = None
        body = await response.read()

        if response.status == 200:
            content_type = response.headers.get('content-type')
            pdict = {}

            if content_type:
                content_type, pdict = cgi.parse_header(content_type)

            encoding = pdict.get('charset', 'utf-8')
            if content_type in ('text/html', 'application/xml'):
                text = await response.text()

                urls = set(re.findall(r'''(?i)href=["']([^\s"'<>]+)''', text))
                if urls:
                    print(
                        f'[*] got {len(urls)} distinct urls from {response.url}'
                    )
                    pass

                for url in urls:
                    normalized = urllib.parse.urljoin(str(response.url), url)
                    defragmented, frag = urllib.parse.urldefrag(normalized)
                    if self.url_allowed(defragmented):
                        links.add(defragmented)

        stat = FetchStatistic(url=response.url,
                              next_url=None,
                              status=response.status,
                              exception=None,
                              size=len(body),
                              content_type=content_type,
                              encoding=encoding,
                              num_urls=len(links),
                              num_new_urls=len(links - self.seen_urls))
        return stat, links

    async def fetch(self, url, max_redirect):
        tries = 0
        exception = None
        while tries < self.max_tries:
            try:
                response = await self.session.get(url, allow_redirects=False)
                break
            except aiohttp.ClientError as client_error:
                exception = client_error

            tries += 1
        else:
            self.record_statistic(
                FetchStatistic(url=url,
                               next_url=None,
                               status=None,
                               exception=exception,
                               size=0,
                               content_type=None,
                               encoding=None,
                               num_urls=0,
                               num_new_urls=0))
            return

        try:
            if is_redirect(response):
                location = response.headers['location']
                next_url = urllib.parse.urljoin(url, location)
                self.record_statistic(
                    FetchStatistic(url=url,
                                   next_url=next_url,
                                   status=response.status,
                                   exception=None,
                                   size=0,
                                   content_type=None,
                                   encoding=None,
                                   num_urls=0,
                                   num_new_urls=0))

                if next_url in self.seen_urls:
                    return
                if max_redirect > 0:
                    self.add_url(next_url, max_redirect - 1)
                else:
                    pass
            else:
                stat, links = await self.parse_links(response)
                self.record_statistic(stat)
                for link in links.difference(self.seen_urls):
                    self.q.put_nowait((link, self.max_redirect))
                self.seen_urls.update(links)
        finally:
            await response.release()

    async def work(self):
        try:
            while True:
                url, max_redirect = await self.q.get()
                assert url in self.seen_urls
                await self.fetch(url, max_redirect)
                self.q.task_done()
        except asyncio.CancelledError:
            pass

    def add_url(self, url, max_redirect=None):
        if max_redirect is None:
            max_redirect = self.max_redirect
        self.seen_urls.add(url)
        self.q.put_nowait((url, max_redirect))

    async def crawl(self):
        print('[*] start')
        workers = [
            asyncio.Task(self.work(), loop=self.loop)
            for _ in range(self.max_tasks)
        ]
        await self.q.join()
        self.t1 = time.time()

        for w in workers:
            w.cancel()

        print(f'[*] use time:{ self.t1 - self.t0}')
