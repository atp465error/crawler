import argparse
import asyncio
from urllib.parse import urlparse

import aiohttp

import crawling
import reporting

ARGS = argparse.ArgumentParser(description="Web crawler")
ARGS.add_argument('url', help='Website url')
ARGS.add_argument('--max_redirect',
                  action='store',
                  type=int,
                  default=10,
                  help='Limit redirection chains (for 301, 302 etc.)')
ARGS.add_argument('--max_tries',
                  action='store',
                  type=int,
                  default=4,
                  help='Limit retries on network errors')
ARGS.add_argument('--max_tasks',
                  action='store',
                  type=int,
                  default=100,
                  help='Limit concurrent connections')


def main():
    args = ARGS.parse_args()
    if '://' not in args.url:
        args.url = 'http://' + args.url

    loop = asyncio.get_event_loop()
    host = urlparse(args.url).netloc
    crawler = crawling.Crawler(args.url,
                               max_redirect=args.max_redirect,
                               max_tries=args.max_tries,
                               max_tasks=args.max_tasks,
                               host=host)

    try:
        loop.run_until_complete(crawler.crawl())
    except KeyboardInterrupt:
        import sys
        sys.stderr.flush()
        print('\nInterrupted\n')
    finally:
        reporting.report(crawler)
        loop.run_until_complete(crawler.close())
        loop.stop()
        loop.run_forever()
        loop.close()


if __name__ == "__main__":
    main()
