from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx


@dataclass(frozen=True, slots=True)
class DomainCnameCheck:
    verified: bool
    target: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DomainRoutingCheck:
    verified: bool
    status_code: int | None = None
    error: str | None = None


class DomainDnsService:
    def __init__(self, *, technical_domain: str) -> None:
        self.technical_domain = technical_domain.strip().lower().rstrip(".")

    async def check_cname(self, domain_name: str) -> DomainCnameCheck:
        domain = domain_name.strip().lower().rstrip(".")
        resolver = dns.asyncresolver.Resolver()
        resolver.timeout = 1.5
        resolver.lifetime = 3.0
        try:
            answer = await resolver.resolve(domain, "CNAME", search=False)
        except dns.resolver.NXDOMAIN:
            return DomainCnameCheck(verified=False, error="Домен не найден в DNS")
        except dns.resolver.NoAnswer:
            return DomainCnameCheck(verified=False, error="CNAME-запись не найдена")
        except dns.resolver.NoNameservers:
            return DomainCnameCheck(
                verified=False,
                error="DNS-серверы не ответили",
            )
        except dns.exception.Timeout:
            return DomainCnameCheck(verified=False, error="Таймаут проверки DNS")
        except Exception:
            return DomainCnameCheck(
                verified=False,
                error="Не удалось проверить DNS",
            )

        targets = sorted(
            {
                str(record.target).strip().lower().rstrip(".")
                for record in answer
                if getattr(record, "target", None)
            }
        )
        if not targets:
            return DomainCnameCheck(verified=False, error="CNAME-запись не найдена")

        target = targets[0]
        verified = self._is_expected_target(target)
        return DomainCnameCheck(
            verified=verified,
            target=target,
            error=None if verified else "CNAME направлен на другой адрес",
        )

    def _is_expected_target(self, target: str) -> bool:
        normalized = target.strip().lower().rstrip(".")
        return normalized == self.technical_domain or normalized.endswith(".b-cdn.net")

    async def check_routing(self, domain_name: str) -> DomainRoutingCheck:
        domain = domain_name.strip().lower().rstrip(".")
        address_error = await self._validate_public_addresses(domain)
        if address_error is not None:
            return DomainRoutingCheck(verified=False, error=address_error)

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(5.0),
                trust_env=False,
            ) as client:
                response = await client.get(
                    f"https://{domain}/health",
                    headers={
                        "Accept": "application/json",
                        "Cache-Control": "no-cache",
                        "User-Agent": "SferaCRM-DomainCheck/1.0",
                    },
                )
        except httpx.TimeoutException:
            return DomainRoutingCheck(
                verified=False,
                error="HTTPS-проверка домена превысила 5 секунд",
            )
        except httpx.ConnectError:
            return DomainRoutingCheck(
                verified=False,
                error="Не удалось установить HTTPS-соединение с доменом",
            )
        except httpx.HTTPError:
            return DomainRoutingCheck(
                verified=False,
                error="Ошибка HTTPS-проверки домена",
            )

        return self._routing_result_from_response(domain, response)

    @staticmethod
    async def _validate_public_addresses(domain: str) -> str | None:
        try:
            address_rows = await asyncio.wait_for(
                asyncio.to_thread(
                    socket.getaddrinfo,
                    domain,
                    443,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                ),
                timeout=3.0,
            )
        except asyncio.TimeoutError:
            return "DNS-проверка адреса превысила 3 секунды"
        except socket.gaierror:
            return "Домен не найден в DNS"

        addresses = {
            row[4][0]
            for row in address_rows
            if len(row) > 4 and row[4] and row[4][0]
        }
        if not addresses:
            return "DNS не вернул IP-адрес домена"
        try:
            if any(not ipaddress.ip_address(address).is_global for address in addresses):
                return "Домен направлен на локальный или служебный IP-адрес"
        except ValueError:
            return "DNS вернул некорректный IP-адрес"
        return None

    @staticmethod
    def _routing_result_from_response(
        domain: str,
        response: httpx.Response,
    ) -> DomainRoutingCheck:
        status_code = response.status_code
        pull_zone = (response.headers.get("cdn-pullzone") or "").strip()
        zone_suffix = f", Pull Zone {pull_zone}" if pull_zone else ""

        if status_code == 508 or response.headers.get("errorcode") == "108":
            return DomainRoutingCheck(
                verified=False,
                status_code=status_code,
                error=(
                    f"Обнаружен CDN-цикл (HTTP {status_code}{zone_suffix}). "
                    "Origin должен вести напрямую на сервер, а не на другой Bunny-домен"
                ),
            )

        if 300 <= status_code < 400:
            location = (response.headers.get("location") or "").strip()
            target_host = (urlsplit(location).hostname or "").strip().lower().rstrip(".")
            if target_host == domain:
                error = (
                    f"Домен перенаправляет /health сам на себя "
                    f"(HTTP {status_code}{zone_suffix})"
                )
            else:
                destination = target_host or location or "неизвестный адрес"
                error = (
                    f"Неожиданный редирект /health на {destination} "
                    f"(HTTP {status_code}{zone_suffix})"
                )
            return DomainRoutingCheck(
                verified=False,
                status_code=status_code,
                error=error,
            )

        if status_code != 200:
            return DomainRoutingCheck(
                verified=False,
                status_code=status_code,
                error=f"Шлюз CRM вернул HTTP {status_code}{zone_suffix}",
            )

        try:
            payload = response.json()
        except ValueError:
            payload = None
        components = payload.get("components") if isinstance(payload, dict) else None
        if not isinstance(components, dict) or components.get("api") != "ok":
            return DomainRoutingCheck(
                verified=False,
                status_code=status_code,
                error="Домен отвечает, но запрос /health попал не в шлюз CRM",
            )
        return DomainRoutingCheck(verified=True, status_code=status_code)
