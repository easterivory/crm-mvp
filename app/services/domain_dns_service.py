from __future__ import annotations

from dataclasses import dataclass

import dns.asyncresolver
import dns.exception
import dns.resolver


@dataclass(frozen=True, slots=True)
class DomainCnameCheck:
    verified: bool
    target: str | None = None
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
