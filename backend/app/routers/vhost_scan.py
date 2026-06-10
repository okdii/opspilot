"""Vhost auto-discovery — SSH into a server and extract virtual host config.

Supports nginx, apache (Debian + RHEL), caddy, and LiteSpeed.
Returns a list of discovered domains with already_monitored flag.
"""
import re
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import AdminUser
from app.models.other import Service
from app.models.server import Server
from app.services.ssh import SSHError, SSHSession

router = APIRouter(tags=["servers"])


class VhostEntry(BaseModel):
    domain: str
    url: str
    port: int
    scheme: str
    server_type: str
    already_monitored: bool


# ── Web server detection ────────────────────────────────────────────────────


async def _has_nginx(session: SSHSession) -> bool:
    return (await session.run("nginx -v", timeout=5)).exit_code == 0


async def _has_apache(session: SSHSession) -> bool:
    for cmd in ("apache2ctl -v", "httpd -v"):
        if (await session.run(cmd, timeout=5)).exit_code == 0:
            return True
    return False


async def _has_caddy(session: SSHSession) -> bool:
    return (await session.run("caddy version", timeout=5)).exit_code == 0


async def _has_litespeed(session: SSHSession) -> bool:
    return (await session.run("/usr/local/lsws/bin/lshttpd -v", timeout=5)).exit_code == 0


# ── Parsers ─────────────────────────────────────────────────────────────────


def _parse_nginx(stdout: str) -> list[dict]:
    """Extract vhosts from `nginx -T` merged config dump."""
    entries: list[dict] = []
    seen: set[tuple] = set()

    # Split on server { blocks; index 0 is preamble
    for block in re.split(r'\bserver\s*\{', stdout)[1:]:
        names = re.findall(r'server_name\s+([^;]+);', block)
        listens = re.findall(r'listen\s+([^;]+);', block)

        port, scheme = 80, 'http'
        for listen in listens:
            if '443' in listen or 'ssl' in listen:
                port, scheme = 443, 'https'
                break
            m = re.search(r'\b(\d+)\b', listen)
            if m:
                port = int(m.group(1))

        for name_group in names:
            for name in name_group.split():
                name = name.strip()
                # Skip wildcard and default catch-all entries
                if name and name != '_' and '.' in name and not name.startswith('~'):
                    key = (name, port)
                    if key not in seen:
                        seen.add(key)
                        entries.append({'domain': name, 'port': port, 'scheme': scheme})

    return entries


def _parse_apache(output: str) -> list[dict]:
    """Extract vhosts from `apache2ctl -S` / `httpd -S` output.

    apache2ctl -S writes to stderr on Debian; callers pass stderr+stdout combined.
    Lines look like:  port 443 namevhost app.example.com (/etc/apache2/...)
    """
    entries: list[dict] = []
    seen: set[tuple] = set()

    for line in output.splitlines():
        m = re.search(r'port\s+(\d+)\s+namevhost\s+(\S+)', line)
        if not m:
            continue
        port = int(m.group(1))
        domain = m.group(2).split(':')[0]
        scheme = 'https' if port == 443 else 'http'
        if '.' not in domain:
            continue
        key = (domain, port)
        if key not in seen:
            seen.add(key)
            entries.append({'domain': domain, 'port': port, 'scheme': scheme})

    return entries


def _parse_caddy(content: str) -> list[dict]:
    """Extract site addresses from a Caddyfile.

    Handles: domain.com { ... }, https://domain.com { ... }, http://domain.com { ... }
    Ignores bare-port blocks like :2019 { ... }.
    """
    entries: list[dict] = []
    seen: set[tuple] = set()

    for m in re.finditer(r'^([^\s{#\n][^{\n]*)\s*\{$', content, re.MULTILINE):
        addr_part = m.group(1).strip()
        for part in addr_part.split(','):
            part = part.strip()
            if part.startswith('https://'):
                domain = part[8:].split('/')[0].split(':')[0]
                port, scheme = 443, 'https'
            elif part.startswith('http://'):
                domain = part[7:].split('/')[0].split(':')[0]
                port, scheme = 80, 'http'
            elif re.match(r'^:\d+$', part):
                continue  # bare port, no domain
            else:
                domain = part.split('/')[0].split(':')[0]
                port, scheme = 443, 'https'

            if '.' not in domain or not domain:
                continue
            key = (domain, port)
            if key not in seen:
                seen.add(key)
                entries.append({'domain': domain, 'port': port, 'scheme': scheme})

    return entries


def _parse_litespeed(xml_content: str) -> list[dict]:
    """Extract vhosts from LiteSpeed httpd_config.xml."""
    entries: list[dict] = []
    seen: set[tuple] = set()

    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError:
        return entries

    # Determine if any SSL listener exists (port 443)
    ssl_ports: set[int] = set()
    for listener in root.iter('listener'):
        ssl_el = listener.find('secure')
        port_el = listener.find('port')
        if ssl_el is not None and ssl_el.text == '1' and port_el is not None:
            try:
                ssl_ports.add(int(port_el.text))
            except (ValueError, TypeError):
                pass

    for vh in root.iter('virtualHostConfig'):
        name_el = vh.find('serverName')
        if name_el is None or not name_el.text:
            continue
        domain = name_el.text.strip()
        if '.' not in domain:
            continue
        port = 443 if ssl_ports else 80
        scheme = 'https' if ssl_ports else 'http'
        key = (domain, port)
        if key not in seen:
            seen.add(key)
            entries.append({'domain': domain, 'port': port, 'scheme': scheme})

    return entries


# ── Endpoint ─────────────────────────────────────────────────────────────────


@router.post("/api/servers/{server_id}/scan-vhosts", response_model=list[VhostEntry])
async def scan_vhosts(
    server_id: str,
    user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """SSH into a server and return all discovered virtual hosts."""
    server = await db.get(Server, server_id)
    if not server:
        raise HTTPException(404, detail={"error": "not_found", "message": "Server not found."})

    raw: list[dict] = []

    try:
        async with SSHSession(server) as ssh:
            detected_any = False

            # nginx
            if await _has_nginx(ssh):
                detected_any = True
                r = await ssh.run("nginx -T", timeout=30, sudo=True)
                if r.ok:
                    for e in _parse_nginx(r.stdout):
                        raw.append({**e, 'server_type': 'nginx'})

            # apache (Debian: apache2ctl, RHEL: httpd)
            if await _has_apache(ssh):
                detected_any = True
                for cmd in ("apache2ctl -S", "httpd -S"):
                    r = await ssh.run(cmd, timeout=30, sudo=True)
                    if r.ok or (r.exit_code not in (127, 126) and r.stderr):
                        combined = r.stderr + '\n' + r.stdout
                        for e in _parse_apache(combined):
                            raw.append({**e, 'server_type': 'apache'})
                        break

            # caddy
            if await _has_caddy(ssh):
                detected_any = True
                for path in ("/etc/caddy/Caddyfile", "/etc/caddy/conf.d/*.conf"):
                    r = await ssh.run(f"cat {path} 2>/dev/null", timeout=15)
                    if r.ok and r.stdout.strip():
                        for e in _parse_caddy(r.stdout):
                            raw.append({**e, 'server_type': 'caddy'})

            # litespeed
            if await _has_litespeed(ssh):
                detected_any = True
                r = await ssh.run("cat /usr/local/lsws/conf/httpd_config.xml", timeout=15)
                if r.ok and r.stdout.strip():
                    for e in _parse_litespeed(r.stdout):
                        raw.append({**e, 'server_type': 'litespeed'})

    except SSHError as exc:
        raise HTTPException(502, detail={"error": "ssh_failed", "message": str(exc)})

    if not detected_any:
        raise HTTPException(422, detail={"error": "no_webserver", "message": "No supported web server found (nginx/apache/caddy/litespeed)"})

    # Zero vhosts found is not an error — server may use default config only
    if not raw:
        return []

    # Cross-check against services already monitored in this org
    monitored_urls = {
        u.lower()
        for u in (
            await db.execute(
                select(Service.url)
                .join(Server, Service.server_id == Server.id)
                .where(Server.org_id == server.org_id, Service.url.isnot(None))
            )
        ).scalars().all()
    }

    # Deduplicate across web servers, then build response
    seen: set[tuple] = set()
    result: list[VhostEntry] = []
    for e in raw:
        key = (e['domain'], e['port'])
        if key in seen:
            continue
        seen.add(key)
        url = f"{e['scheme']}://{e['domain']}"
        if not (e['scheme'] == 'https' and e['port'] == 443) and \
           not (e['scheme'] == 'http' and e['port'] == 80):
            url += f":{e['port']}"
        result.append(
            VhostEntry(
                domain=e['domain'],
                url=url,
                port=e['port'],
                scheme=e['scheme'],
                server_type=e['server_type'],
                already_monitored=url.lower() in monitored_urls,
            )
        )

    return result
