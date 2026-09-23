import re
from io import StringIO
from pathlib import Path
from typing import Literal

import jinja2
from pyinfra import host
from pyinfra.api import deploy
from pyinfra.facts.server import Command
from pyinfra.operations import files, server, systemd
from pyinfra.operations.util import any_changed

TEMPLATE = Path(__file__).parent / "templates/nginx_site.conf.j2"
WEBROOT = "/var/www/certbot"


def renewal_is_stale(conf: str) -> bool:
    """A site moved here from another deploy keeps that deploy's renewal webroot:
    the certificate is valid, and every unattended renewal 404s until it expires."""
    if not conf:
        return False
    authenticator = re.search(r"(?m)^authenticator\s*=\s*(\S+)", conf)
    webroots = re.findall(r"(?m)^\S+\s*=\s*(\S+)\s*$", (conf.split("[[webroot_map]]") + [""])[1])
    return (authenticator and authenticator.group(1)) != "webroot" or any(w != WEBROOT for w in webroots)


def certificate_names(sans: str) -> set[str]:
    return set(re.findall(r"DNS:([^,\s]+)", sans))


def modern_http2(nginx_version: str) -> bool:
    """nginx 1.25.1 introduced `http2 on;` and deprecated `listen ... http2`."""
    version = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", nginx_version)
    return not version or tuple(map(int, version.groups())) >= (1, 25, 1)


def render_site(
    site: str,
    domain: str,
    type: Literal["static", "spa", "proxy"],
    root: str = "",
    upstream: str = "",
    aliases: tuple[str, ...] = (),
    open_api_paths: tuple[str, ...] = (),
    plain_http_paths: tuple[str, ...] = (),
    client_max_body_size: str = "10m",
    extra_locations: str = "",
    public: bool = False,
    log_tag: str | None = None,
    cert_exists: bool = True,
    modern_http2: bool = True,
) -> str:
    if type == "proxy" and not upstream:
        raise ValueError("nginx_site: a proxy site needs an upstream")
    if type != "proxy" and not root:
        raise ValueError("nginx_site: a static or spa site needs a root")
    if type != "proxy" and "/" in open_api_paths:
        raise ValueError("nginx_site: a whole-site open API needs a proxy site, the others own `location /`")
    if public and (type == "proxy" or plain_http_paths):
        raise ValueError("nginx_site: a public site serves files on both ports, with no plain_http_paths")
    # site becomes an nginx syslog tag, which rejects anything else with a cryptic parse error
    if not re.fullmatch(r"[A-Za-z0-9_]+", site):
        raise ValueError(f"nginx_site: site must be alphanumeric or underscore, got {site!r}")

    env = jinja2.Environment(trim_blocks=True, keep_trailing_newline=True, undefined=jinja2.StrictUndefined)
    return env.from_string(TEMPLATE.read_text()).render(
        site=site,
        domain=domain,
        type=type,
        root=root,
        upstream=upstream,
        server_names=" ".join([domain, *aliases]),
        open_api_paths=open_api_paths,
        plain_http_paths=plain_http_paths,
        client_max_body_size=client_max_body_size,
        extra_locations=extra_locations,
        public=public,
        log_tag=log_tag or site,
        cert_exists=cert_exists,
        modern_http2=modern_http2,
    )


def _read(command: str) -> str:
    return host.get_fact(Command, f"{command} 2>/dev/null || true", _sudo=True)


@deploy("nginx site")
def nginx_site(
    site: str,
    domain: str,
    type: Literal["static", "spa", "proxy"],
    root: str = "",
    upstream: str = "",
    aliases: tuple[str, ...] = (),
    cert_extra_domains: tuple[str, ...] = (),
    open_api_paths: tuple[str, ...] = (),
    plain_http_paths: tuple[str, ...] = (),
    client_max_body_size: str = "10m",
    extra_locations: str = "",
    public: bool = False,
    log_tag: str | None = None,
):
    sans = _read(f"openssl x509 -noout -ext subjectAltName -in /etc/letsencrypt/live/{domain}/fullchain.pem")
    stale = renewal_is_stale(_read(f"cat /etc/letsencrypt/renewal/{domain}.conf"))
    names = [domain, *aliases, *cert_extra_domains]
    needs_cert = not sans or stale or not set(names) <= certificate_names(sans)

    def config(cert_exists: bool) -> StringIO:
        return StringIO(
            render_site(
                site,
                domain,
                type,
                root=root,
                upstream=upstream,
                aliases=aliases,
                open_api_paths=open_api_paths,
                plain_http_paths=plain_http_paths,
                client_max_body_size=client_max_body_size,
                extra_locations=extra_locations,
                public=public,
                log_tag=log_tag,
                cert_exists=cert_exists,
                modern_http2=modern_http2(host.get_fact(Command, "nginx -v 2>&1")),
            )
        )

    available = f"/etc/nginx/sites-available/{site}.conf"
    enabled = f"/etc/nginx/sites-enabled/{site}.conf"
    changes = [files.directory(name="Certbot webroot", path=WEBROOT, user="www-data", group="www-data", mode="755")]
    if needs_cert:
        # the HTTP-01 challenge needs the port-80 server live before certbot runs
        http_only = files.put(name="Site config (HTTP only)", src=config(bool(sans)), dest=available, mode="644")
        link = files.link(name="Enable site", path=enabled, target=available)
        server.shell(name="Validate nginx config", commands=["nginx -t"], _if=any_changed(http_only, link))
        systemd.service(name="Reload nginx", service="nginx", reloaded=True, _if=any_changed(http_only, link))
        changes.append(
            server.shell(
                name="Request certificate",
                commands=[
                    f"certbot certonly --webroot -w {WEBROOT} --cert-name {domain} "
                    + " ".join(f"-d {name}" for name in names)
                    + " --expand"
                    + (" --force-renewal" if stale else "")
                    + " --non-interactive --agree-tos --register-unsafely-without-email"
                ],
            )
        )
    changes.append(files.put(name="Site config", src=config(True), dest=available, mode="644"))
    changes.append(files.link(name="Enable site", path=enabled, target=available))
    # a reload with a broken config keeps serving the old one, and says so only in the journal
    server.shell(name="Validate nginx config", commands=["nginx -t"], _if=any_changed(*changes))
    systemd.service(name="Reload nginx", service="nginx", reloaded=True, _if=any_changed(*changes))
