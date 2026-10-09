# Simple Web Crawler

A single-threaded web crawler written in Python. It starts from a seed URL, downloads HTML pages, extracts links, and follows them in breadth-first order until a page limit is reached.

> **Course project:** This is the first project of the **Web Search** course at **[Yazd University]**.
> Instructor: **[Dr.Zarebidoki]** · Author: **[Ghazal Dolatshahi]**

## Features

- Breadth-first crawling with a FIFO queue (frontier)
- URL normalization (removes fragments and trailing slashes) and duplicate detection
- Same-site filtering, with optional subdomain support
- Skips non-HTML files by extension and by `Content-Type`
- Automatic retries with backoff on timeouts and connection errors
- Configurable delay between requests
- Optional `robots.txt` support
- Saves every page as an HTML file and builds a `url_index.json` (URL → file, title, status, size)
- Generates a statistics report (`report.json`) and a full log (`crawl.log`)

## Project structure

| Class | Responsibility |
|---|---|
| `Config` | All settings in one place |
| `URLChecker` | Normalizes URLs and decides whether a URL should be crawled |
| `URLFrontier` | Queue of URLs to visit, without duplicates |
| `Fetcher` | Downloads pages with retries and error counting |
| `Parser` | Extracts links and the page title using BeautifulSoup |
| `Storage` | Saves pages and the URL index to disk |
| `Crawler` | Runs the main crawl loop and builds the report |

## Requirements

- Python 3.8+
- `requests`
- `beautifulsoup4`

```bash
pip install -r requirements.txt
```

## Usage

1. Open `crawler.py` and edit the `Config` class (at least `START_URL` and `MAX_PAGES`).
2. Run:

```bash
python crawler.py
```

## Output

Everything is written to the `crawled_output/` folder:

```
crawled_output/
├── pages/            # downloaded HTML files (named by SHA-1 hash of the URL)
├── url_index.json    # URL -> file, title, status, size
├── report.json       # crawl statistics
└── crawl.log         # full log
```

## Configuration

| Option | Default | Description |
|---|---|---|
| `START_URL` | `https://www.technolife.com/` | Seed URL |
| `MAX_PAGES` | `200` | Maximum number of pages to download |
| `ALLOW_SUBDOMAINS` | `True` | Also crawl subdomains of the seed domain |
| `TIMEOUT` | `15` | Request timeout (seconds) |
| `REQUEST_DELAY` | `0.5` | Delay between requests (seconds) |
| `MAX_RETRIES` | `2` | Retries per URL on network errors |
| `RETRY_BACKOFF_SECONDS` | `2` | Wait time between retries |
| `RESPECT_ROBOTS_TXT` | `False` | Follow `robots.txt` rules |

## Sample results

A run on `https://www.technolife.com/` with `MAX_PAGES = 200`:

| Metric | Value |
|---|---|
| Pages downloaded | 200 |
| Crawl time | 238.78 s |
| Output size | 199.49 MB |
| URLs discovered (with duplicates) | 26,294 |
| Unique URLs visited or queued | 6,909 |
| Final queue length | 6,709 |
| Errors | 0 |

Link filtering breakdown: 22,524 accepted, 3,769 already visited, 3,467 from other domains, 372 with non-HTML extensions.

## Limitations

- Single-threaded, so it is slow on large crawls.
- Only fetches raw HTML. It does not execute JavaScript, so links rendered client-side are not discovered.
- No persistence of the queue: if the crawl stops, it starts over.

## Responsible use

`RESPECT_ROBOTS_TXT` is `False` by default in this educational project. When crawling any real website, set it to `True`, keep a reasonable `REQUEST_DELAY`, and follow the site's terms of use.
