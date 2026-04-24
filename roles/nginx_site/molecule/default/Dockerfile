FROM debian:trixie

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        systemd systemd-sysv dbus \
        python3 python3-apt \
        sudo iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN for svc in sys-kernel-debug.mount sys-kernel-tracing.mount \
               systemd-logind.service console-getty.service \
               systemd-udevd.service systemd-udev-trigger.service; do \
        systemctl mask "$svc" || true; \
    done

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
