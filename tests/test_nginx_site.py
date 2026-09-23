import re
import sys
from pathlib import Path

import pytest

from server_setup.nginx_site import certificate_names, modern_http2, render_site, renewal_is_stale

SITES = {
    "t_static": {"domain": "static.test", "type": "static", "root": "/srv/site"},
    "t_plain": {"domain": "plain.test", "type": "static", "root": "/srv/site", "plain_http_paths": ("/",)},
    "t_public": {
        "domain": "public.test",
        "type": "static",
        "root": "/srv/site",
        "public": True,
        "extra_locations": "rewrite ^/bust/\\d+/(.*)$ /$1 last;\n",
    },
    "t_spa": {"domain": "spa.test", "type": "spa", "root": "/srv/site"},
    "t_proxy": {"domain": "proxy.test", "type": "proxy", "upstream": "http://127.0.0.1:8000"},
    "t_api": {"domain": "api.test", "type": "proxy", "upstream": "http://127.0.0.1:8000", "open_api_paths": ("/",)},
}


def render(name: str, **overrides) -> str:
    return render_site(name, **{**SITES[name], **overrides})


def test_open_api_proxies_the_root_once_per_server():
    conf = render("t_api")
    assert "Access-Control-Allow-Origin" in conf
    assert conf.count("location / {") == 2


def test_whole_site_plain_http_replaces_the_redirect():
    conf = render("t_plain")
    assert "return 301" not in conf
    assert conf.count("location / {") == 2


def test_public_site_serves_both_ports_alike():
    conf = render("t_public")
    assert "return 301" not in conf
    http, https = conf.split("listen 443")
    for server in (http, https):
        assert "autoindex on" in server
        assert "GET, HEAD, OPTIONS" in server
        assert "rewrite ^/bust/" in server


def test_spa_caches_only_its_hashed_assets_and_a_private_site_sends_no_cors():
    conf = render("t_spa")
    assert re.search(r"location /assets/ \{[^}]*immutable", conf)
    assert re.search(r"location / \{[^}]*no-cache", conf)
    assert "Access-Control" not in conf


def test_before_the_certificate_only_port_80_answers():
    conf = render("t_proxy", cert_exists=False)
    assert 'return 503 "TLS certificate not yet provisioned' in conf
    assert "listen 443" not in conf


def test_http2_directive_follows_the_nginx_version():
    assert "http2 on;" in render("t_proxy", modern_http2=True)
    assert "listen 443 ssl http2;" in render("t_proxy", modern_http2=False)
    assert modern_http2("nginx version: nginx/1.26.3")
    assert not modern_http2("nginx version: nginx/1.25.0")
    assert not modern_http2("nginx version: nginx/1.22.1")


@pytest.mark.parametrize(
    "bad",
    [
        {"type": "proxy", "upstream": ""},
        {"type": "static", "root": ""},
        {"type": "static", "root": "/srv", "public": True, "plain_http_paths": ("/",)},
    ],
)
def test_inconsistent_inputs_fail(bad):
    with pytest.raises(ValueError):
        render_site("t_bad", "bad.test", **bad)


def test_site_name_must_be_a_valid_syslog_tag():
    with pytest.raises(ValueError):
        render_site("new-archon", "x.test", "proxy", upstream="http://127.0.0.1:1")


RENEWAL = """\
version = 2.1.0
[renewalparams]
authenticator = {authenticator}
webroot_path = {webroot},
server = https://acme-v02.api.letsencrypt.org/directory
[[webroot_map]]
bot.example.org = {webroot}
"""


def test_renewal_through_our_webroot_is_current():
    assert not renewal_is_stale(RENEWAL.format(authenticator="webroot", webroot="/var/www/certbot"))
    assert not renewal_is_stale("")


def test_renewal_through_another_webroot_or_plugin_is_stale():
    assert renewal_is_stale(RENEWAL.format(authenticator="webroot", webroot="/usr/share/nginx/html"))
    assert renewal_is_stale(RENEWAL.format(authenticator="nginx", webroot="/var/www/certbot"))


def test_certificate_names_read_the_san_extension():
    sans = "X509v3 Subject Alternative Name: \n    DNS:api.test, DNS:alias.test"
    assert certificate_names(sans) == {"api.test", "alias.test"}


# CI renders every site into the runner's nginx and runs `nginx -t` over them
if __name__ == "__main__":
    out = Path(sys.argv[1])
    for name in SITES:
        (out / f"{name}.conf").write_text(render(name))
