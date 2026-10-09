import os
import json
import time
import hashlib
import logging
from collections import deque
from urllib.parse import urljoin, urlparse, urldefrag
from urllib import robotparser
import requests
from bs4 import BeautifulSoup


class Config:
    START_URL = "https://www.technolife.com/"
    MAX_PAGES = 200
    ALLOW_SUBDOMAINS = True
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    OUTPUT_DIR = os.path.join(BASE_DIR, "crawled_output")
    PAGES_DIR = os.path.join(OUTPUT_DIR, "pages")

    TIMEOUT = 15
    REQUEST_DELAY = 0.5
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    MAX_RETRIES = 2
    RETRY_BACKOFF_SECONDS = 2
    RESPECT_ROBOTS_TXT = False
    NON_HTML_EXTENSIONS = (
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
        ".css", ".js", ".zip", ".rar", ".mp4", ".mp3", ".avi", ".mov",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".woff",
        ".woff2", ".ttf", ".eot", ".json", ".xml", ".rss", ".exe",
    )


os.makedirs(Config.OUTPUT_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(Config.OUTPUT_DIR, "crawl.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("crawler")


# 1) URL Checker
class URLChecker:
    def __init__(self, base_url: str, allow_subdomains: bool = True):
        parsed = urlparse(base_url)
        self.base_domain = parsed.netloc.lower()
        parts = self.base_domain.split(".")
        self.root_domain = ".".join(parts[-2:]) if len(parts) >= 2 else self.base_domain
        self.allow_subdomains = allow_subdomains
        self.robots_parsers = {}

    def normalize(self, url: str) -> str:
        url, _frag = urldefrag(url)
        parsed = urlparse(url)
        path = parsed.path if parsed.path else "/"
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return parsed._replace(path=path).geturl()

    def is_same_site(self, netloc: str) -> bool:
        netloc = netloc.lower()
        if netloc == self.base_domain:
            return True
        if self.allow_subdomains and netloc.endswith("." + self.root_domain):
            return True
        return False

    def looks_like_html(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return not path.endswith(Config.NON_HTML_EXTENSIONS)

    def is_allowed_by_robots(self, url: str) -> bool:
        if not Config.RESPECT_ROBOTS_TXT:
            return True
        parsed = urlparse(url)
        netloc = parsed.netloc
        if netloc not in self.robots_parsers:
            rp = robotparser.RobotFileParser()
            robots_url = f"{parsed.scheme}://{netloc}/robots.txt"
            try:
                rp.set_url(robots_url)
                rp.read()
                log.info(f"[debug] robots.txt read successfully: {robots_url}")
            except Exception as e:
                log.warning(f"[debug] Failed to read robots.txt ({robots_url}): {e}")
                rp = None
            self.robots_parsers[netloc] = rp
        rp = self.robots_parsers[netloc]
        if rp is None:
            return True
        try:
            return rp.can_fetch(Config.USER_AGENT, url)
        except Exception:
            return True

    def is_valid(self, url: str) -> bool:
        ok, _reason = self.is_valid_verbose(url)
        return ok

    def is_valid_verbose(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "scheme_not_http"
        if not self.is_same_site(parsed.netloc):
            return False, "different_domain"
        if not self.looks_like_html(url):
            return False, "non_html_extension"
        if not self.is_allowed_by_robots(url):
            return False, "blocked_by_robots_txt"
        return True, "ok"


# 2) Queue
class URLFrontier:
    def __init__(self):
        self._queue = deque()
        self._queued_or_visited = set()
        self.total_discovered_with_duplicates = 0

    def add(self, url: str) -> bool:
        self.total_discovered_with_duplicates += 1
        if url in self._queued_or_visited:
            return False
        self._queued_or_visited.add(url)
        self._queue.append(url)
        return True

    def pop(self):
        return self._queue.popleft() if self._queue else None

    def __len__(self):
        return len(self._queue)

    def seed(self, url: str):
        self._queued_or_visited.add(url)
        self._queue.append(url)
        self.total_discovered_with_duplicates += 1


# 3) Fetcher
class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": Config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fa,en-US;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })
        self.error_counts = {
            "timeout": 0,
            "connection_error": 0,
            "http_error": 0,
            "not_html_content_type": 0,
            "other": 0,
        }

    def fetch(self, url: str):
        for attempt in range(Config.MAX_RETRIES + 1):
            try:
                resp = self.session.get(url, timeout=Config.TIMEOUT, allow_redirects=True)
                content_type = resp.headers.get("Content-Type", "")
                if resp.status_code != 200:
                    log.warning(f"HTTP {resp.status_code} for {url}")
                    self.error_counts["http_error"] += 1
                    return None, resp.status_code
                if "text/html" not in content_type.lower():
                    log.info(f"Skipped (not HTML, Content-Type={content_type}): {url}")
                    self.error_counts["not_html_content_type"] += 1
                    return None, resp.status_code
                return resp.text, resp.status_code
            except requests.exceptions.Timeout as e:
                self.error_counts["timeout"] += 1
                log.warning(f"Timeout for {url} (attempt {attempt + 1}): {e}")
            except requests.exceptions.SSLError as e:
                self.error_counts["connection_error"] += 1
                log.warning(f"SSL error for {url} (attempt {attempt + 1}): {e}")
            except requests.exceptions.ConnectionError as e:
                self.error_counts["connection_error"] += 1
                log.warning(f"Connection error for {url} (attempt {attempt + 1}): {e}")
            except Exception as e:
                self.error_counts["other"] += 1
                log.warning(f"Unknown error for {url}: {e}")
                break

            if attempt < Config.MAX_RETRIES:
                time.sleep(Config.RETRY_BACKOFF_SECONDS)
        return None, None

    def total_errors(self):
        return sum(self.error_counts.values())


# 4) Parser
class Parser:
    def extract_links(self, html: str, base_url: str):
        links = []
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            log.warning(f"HTML parse error for {base_url}: {e}")
            return links

        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            links.append(urljoin(base_url, href))
        return links

    def extract_title(self, html: str) -> str:
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.title and soup.title.string:
                return soup.title.string.strip()
        except Exception:
            pass
        return ""


# Storage
class Storage:
    def __init__(self, output_dir: str, pages_dir: str):
        self.output_dir = output_dir
        self.pages_dir = pages_dir
        os.makedirs(self.pages_dir, exist_ok=True)
        self.index = {}  # url -> {"file": filename, "title": ..., "status": ...}

    def _filename_for(self, url: str) -> str:
        h = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return f"{h}.html"

    def save_page(self, url: str, html: str, title: str = "", status: int = 200):
        filename = self._filename_for(url)
        filepath = os.path.join(self.pages_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        self.index[url] = {
            "file": os.path.join("pages", filename),
            "title": title,
            "status": status,
            "size_bytes": len(html.encode("utf-8")),
        }
        return filepath

    def write_index(self):
        with open(os.path.join(self.output_dir, "url_index.json"), "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)

    def total_output_size_bytes(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.output_dir):
            for name in files:
                total += os.path.getsize(os.path.join(root, name))
        return total


# Crawler
class Crawler:
    def __init__(self, start_url: str, max_pages: int):
        self.checker = URLChecker(start_url, allow_subdomains=Config.ALLOW_SUBDOMAINS)
        self.start_url = self.checker.normalize(start_url)
        self.max_pages = max_pages

        self.frontier = URLFrontier()
        self.fetcher = Fetcher()
        self.parser = Parser()
        self.storage = Storage(Config.OUTPUT_DIR, Config.PAGES_DIR)

        self.visited = set()
        self.downloaded_count = 0

        self.debug_raw_links_seen = 0
        self.reject_reasons = {
            "already_visited": 0,
            "different_domain": 0,
            "non_html_extension": 0,
            "blocked_by_robots_txt": 0,
            "scheme_not_http": 0,
            "ok": 0,
        }

    def run(self):
        log.info(f"Starting crawl from: {self.start_url}")
        log.info(f"Page limit: {self.max_pages}")
        start_time = time.time()

        self.frontier.seed(self.start_url)

        while self.frontier and self.downloaded_count < self.max_pages:
            url = self.frontier.pop()
            if url is None:
                break
            if url in self.visited:
                continue
            self.visited.add(url)

            log.info(f"[{self.downloaded_count + 1}/{self.max_pages}] Fetching: {url}")
            html, status = self.fetcher.fetch(url)

            if Config.REQUEST_DELAY:
                time.sleep(Config.REQUEST_DELAY)

            if html is None:
                continue
            title = self.parser.extract_title(html)
            self.storage.save_page(url, html, title=title, status=status)
            self.downloaded_count += 1

            raw_links = self.parser.extract_links(html, url)
            self.debug_raw_links_seen += len(raw_links)
            if self.downloaded_count == 1:
                log.info(f"[debug] Raw <a href> links found on the first page: {len(raw_links)}")
                for sample in raw_links[:10]:
                    log.info(f"[debug] Sample raw link: {sample}")

            for link in raw_links:
                normalized = self.checker.normalize(link)
                if normalized in self.visited:
                    self.frontier.total_discovered_with_duplicates += 1
                    self.reject_reasons["already_visited"] += 1
                    continue
                ok, reason = self.checker.is_valid_verbose(normalized)
                if not ok:
                    self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1
                    continue
                self.reject_reasons["ok"] += 1
                self.frontier.add(normalized)

        end_time = time.time()
        self.storage.write_index()

        stats = self._build_stats(start_time, end_time)
        self._write_report(stats)
        self._print_summary(stats)
        return stats

    def _build_stats(self, start_time, end_time):
        return {
            "start_url": self.start_url,
            "max_pages_config": self.max_pages,
            "pages_downloaded": self.downloaded_count,
            "crawl_time_seconds": round(end_time - start_time, 2),
            "output_size_bytes": self.storage.total_output_size_bytes(),
            "output_size_mb": round(self.storage.total_output_size_bytes() / (1024 * 1024), 3),
            "urls_discovered_with_duplicates": self.frontier.total_discovered_with_duplicates,
            "unique_urls_visited_or_queued": len(self.visited) + len(self.frontier),
            "final_queue_length": len(self.frontier),
            "total_errors": self.fetcher.total_errors(),
            "errors_breakdown": self.fetcher.error_counts,
            "user_agent": Config.USER_AGENT,
            "language_platform": "Python 3 (requests + BeautifulSoup4), single-threaded",
            "debug_raw_links_seen_total": self.debug_raw_links_seen,
            "debug_reject_reasons": self.reject_reasons,
        }

    def _write_report(self, stats):
        with open(os.path.join(Config.OUTPUT_DIR, "report.json"), "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

    def _print_summary(self, stats):
        log.info("=" * 60)
        log.info("Crawl summary")
        log.info("=" * 60)
        for k, v in stats.items():
            log.info(f"{k}: {v}")
        log.info("=" * 60)
        if stats["pages_downloaded"] < 5:
            log.warning(
                "Very few pages were downloaded. Check debug_reject_reasons and "
                "debug_raw_links_seen_total in report.json to find the cause "
                "(e.g. blocked by robots.txt, or links rendered by JavaScript)."
            )


if __name__ == "__main__":
    crawler = Crawler(Config.START_URL, Config.MAX_PAGES)
    crawler.run()