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

from server_setup.certificate import certificate

TEMPLATE = Path(__file__).parent / "templates/nginx_site.conf.j2"


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
        modern_http2=modern_http2,
    )


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
    certificate(domain, (*aliases, *cert_extra_domains))
    config = render_site(
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
        modern_http2=modern_http2(host.get_fact(Command, "nginx -v 2>&1")),
    )
    available = f"/etc/nginx/sites-available/{site}.conf"
    changes = [
        files.put(name="Site config", src=StringIO(config), dest=available, mode="644"),
        files.link(name="Enable site", path=f"/etc/nginx/sites-enabled/{site}.conf", target=available),
    ]
    # a reload with a broken config keeps serving the old one, and says so only in the journal
    server.shell(name="Validate nginx config", commands=["nginx -t"], _if=any_changed(*changes))
    systemd.service(name="Reload nginx", service="nginx", reloaded=True, _if=any_changed(*changes))
