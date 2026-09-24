import re

from pyinfra import host
from pyinfra.api import deploy
from pyinfra.facts.server import Command
from pyinfra.operations import files, server, systemd

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


def _read(command: str) -> str:
    return host.get_fact(Command, f"{command} 2>/dev/null || true", _sudo=True)


@deploy("certificate")
def certificate(domain: str, extra_domains: tuple[str, ...] = ()):
    """Issues before any site config exists: until a site claims the name, the
    host's default server answers the HTTP-01 challenge from WEBROOT."""
    sans = _read(f"openssl x509 -noout -ext subjectAltName -in /etc/letsencrypt/live/{domain}/fullchain.pem")
    stale = renewal_is_stale(_read(f"cat /etc/letsencrypt/renewal/{domain}.conf"))
    names = [domain, *extra_domains]
    files.directory(name="Certbot webroot", path=WEBROOT, user="www-data", group="www-data", mode="755")
    if sans and not stale and set(names) <= certificate_names(sans):
        return
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
    # certbot's deploy hooks run on renewals only: a site already serving keeps the old certificate
    server.shell(name="Validate nginx config", commands=["nginx -t"])
    systemd.service(name="Reload nginx", service="nginx", reloaded=True)
