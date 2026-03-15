from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse

import requests
try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None  # type: ignore[assignment]

from models.resume import ResumeProfile

logger = logging.getLogger(__name__)

class OlostepSearchClient:
    def __init__(self, api_key: str, base_url: str = "https://api.olostep.com/v1/searches", timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    def _request_with_retry(self, payload: Dict[str, Any], retries: int = 10, backoff: float = 1.5) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                sleep_for = backoff ** attempt
                status = None
                body = ""
                if exc.response is not None:
                    status = exc.response.status_code
                    body = exc.response.text[:300]

                logger.warning(
                    "Olostep request failed on attempt %s/%s (status=%s): %s | response=%s",
                    attempt,
                    retries,
                    status,
                    exc,
                    body,
                )

                # 4xx auth/contract issues usually won't succeed on retry.
                if status in {400, 401, 403, 404, 422}:
                    break
                time.sleep(sleep_for)

        raise RuntimeError(f"Olostep API call failed after {retries} attempts: {last_error}")

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        payload = {"query": query}
        data = self._request_with_retry(payload)
        if not isinstance(data, dict):
            return []

        # Normalize common response shapes into a flat list of objects.
        candidates: List[Any] = []
        result = data.get("result")
        if isinstance(result, dict):
            if isinstance(result.get("links"), list):
                candidates = result["links"]
            elif isinstance(result.get("json_content"), str):
                try:
                    json_content = json.loads(result["json_content"])
                except json.JSONDecodeError:
                    json_content = {}
                if isinstance(json_content, dict):
                    for key in ("links", "results", "items", "organic"):
                        value = json_content.get(key)
                        if isinstance(value, list):
                            candidates = value
                            break

        for key in ("results", "result", "data", "items"):
            if candidates:
                break
            value = data.get(key)
            if isinstance(value, list):
                candidates = value
                break
            if isinstance(value, dict):
                nested = value.get("results") or value.get("items")
                if isinstance(nested, list):
                    candidates = nested
                    break

        if not candidates and isinstance(data.get("organic"), list):
            candidates = data["organic"]

        normalized: List[Dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("job_title") or item.get("name") or ""
            url = item.get("url") or item.get("job_url") or item.get("link") or ""
            snippet = item.get("description") or item.get("snippet") or item.get("summary") or ""
            if not title or not url:
                continue
            record = dict(item)
            if "title" not in record:
                record["title"] = title
            if "url" not in record:
                record["url"] = url
            if "description" not in record and isinstance(snippet, str) and snippet.strip():
                record["description"] = snippet
            normalized.append(record)

        if normalized:
            return normalized[:limit]
        return []


class OlostepScrapeClient:
    def __init__(self, api_key: str, base_url: str = "https://api.olostep.com/v1/scrapes", timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout

    def _request_with_retry(self, payload: Dict[str, Any], retries: int = 5, backoff: float = 1.5) -> Dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                response = requests.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                sleep_for = backoff ** attempt
                status = None
                body = ""
                if exc.response is not None:
                    status = exc.response.status_code
                    body = exc.response.text[:300]

                logger.warning(
                    "Olostep scrape failed on attempt %s/%s (status=%s): %s | response=%s",
                    attempt,
                    retries,
                    status,
                    exc,
                    body,
                )
                if status in {400, 401, 403, 404, 422}:
                    break
                time.sleep(sleep_for)

        raise RuntimeError(f"Olostep scrape call failed after {retries} attempts: {last_error}")

    def scrape_page(self, url: str) -> Dict[str, Any]:
        payload = {
            "url_to_scrape": url,
            "formats": ["markdown", "html"],
            "wait_before_scraping": 0,
        }
        data = self._request_with_retry(payload)
        if not isinstance(data, dict):
            return {}
        return data.get("result", {}) if isinstance(data.get("result"), dict) else {}


def _extract_links_from_html(html: str, base_url: str) -> List[str]:
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
    out: List[str] = []
    for href in hrefs:
        href = href.strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        out.append(absolute)
    # preserve order while deduping
    seen = set()
    unique: List[str] = []
    for u in out:
        if u in seen:
            continue
        seen.add(u)
        unique.append(u)
    return unique


def _looks_like_job_link(url: str) -> bool:
    lowered = url.lower()
    job_markers = ("job", "jobs", "career", "careers", "position", "opening", "vacancy", "workday", "greenhouse")
    return any(marker in lowered for marker in job_markers)


def _scrape_description_recursive(
    scrape_client: OlostepScrapeClient,
    url: str,
    depth: int,
    visited: set[str],
) -> str:
    if depth <= 0 or not url or url in visited:
        return ""
    visited.add(url)

    result = scrape_client.scrape_page(url)
    markdown = result.get("markdown")
    if isinstance(markdown, str) and markdown.strip():
        return markdown.strip()

    html = result.get("html")
    if not isinstance(html, str) or not html.strip():
        return ""

    child_links = _extract_links_from_html(html, base_url=url)
    prioritized = [link for link in child_links if _looks_like_job_link(link)]
    fallback = [link for link in child_links if link not in prioritized]
    for next_url in prioritized + fallback:
        text = _scrape_description_recursive(scrape_client, next_url, depth=depth - 1, visited=visited)
        if text:
            return text
    return ""


def _fallback_queries(profile: ResumeProfile) -> List[str]:
    role = profile.roles[0] if profile.roles else "machine learning engineer"
    tech = profile.technologies[0] if profile.technologies else "python"

    return [
        f"{role} remote {tech}",
        "ai engineer python remote",
        "machine learning engineer europe",
        "ml engineer germany",
    ]


def _generate_queries_with_openai(profile: ResumeProfile, max_queries: int = 6) -> List[str]:
    if OpenAI is None:
        return []

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return []

    client = OpenAI(api_key=api_key)
    prompt = (
        "Generate highly relevant web search queries for job hunting.\n"
        f"Candidate skills: {', '.join(profile.skills)}\n"
        f"Technologies: {', '.join(profile.technologies)}\n"
        f"Years of experience: {profile.years_experience}\n"
        f"Roles: {', '.join(profile.roles)}\n"
        f"Keywords: {', '.join(profile.keywords[:20])}\n\n"
        f"Return ONLY valid JSON with this shape: {{\"queries\": [\"...\", \"...\"]}}.\n"
        f"Constraints: {max_queries} queries max, concise, job-focused, include remote and location variants."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "Return only valid JSON. Do not wrap JSON in markdown fences.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        payload = json.loads(text)
        queries = payload.get("queries", [])
        if isinstance(queries, list):
            cleaned = []
            for q in queries:
                if isinstance(q, str) and q.strip():
                    cleaned.append(q.strip())
            return cleaned[:max_queries]
    except Exception as exc:  # noqa: BLE001
        logger.warning("OpenAI query generation failed, using fallback queries: %s", exc)
    return []


def build_search_queries(profile: ResumeProfile) -> List[str]:
    openai_queries = _generate_queries_with_openai(profile)
    if openai_queries:
        return openai_queries
    return _fallback_queries(profile)


def search_jobs(profile: ResumeProfile, api_key: str, max_results_per_query: int = 3) -> List[Dict[str, Any]]:
    search_client = OlostepSearchClient(api_key=api_key)
    aggregated: List[Dict[str, Any]] = []

    for query in build_search_queries(profile):
        try:
            results = search_client.search(query=query, limit=max_results_per_query)
            logger.info("Query '%s' returned %s results", query, len(results))
            aggregated.extend(results)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed search query '%s': %s", query, exc)

    return aggregated


def scrape_jobs(
    jobs: List[Dict[str, Any]],
    api_key: str,
    recursive_depth: int = 2,
) -> List[Dict[str, Any]]:
    scrape_client = OlostepScrapeClient(api_key=api_key)
    enriched: List[Dict[str, Any]] = []

    for item in jobs:
        record = dict(item)
        description = record.get("description") or record.get("snippet")
        if isinstance(description, str) and description.strip():
            enriched.append(record)
            continue

        job_url = record.get("url") or record.get("job_url") or record.get("link")
        if not isinstance(job_url, str) or not job_url.strip():
            enriched.append(record)
            continue

        try:
            resolved = _scrape_description_recursive(
                scrape_client=scrape_client,
                url=job_url.strip(),
                depth=recursive_depth,
                visited=set(),
            )
            if resolved:
                record["description"] = resolved
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recursive scrape fallback failed for %s: %s", job_url, exc)
        enriched.append(record)

    return enriched
