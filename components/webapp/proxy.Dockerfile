# HAProxy 3.4.7 on the 3.4-alpine channel.
FROM haproxy:3.4-alpine@sha256:b9fe316f718d5015c5cfebd8ca019591f3e44656f61d93cb8b59a1028961e530
USER root
RUN apk add --no-cache python3 iptables iproute2 util-linux
COPY components/webapp/proxy-start.py /usr/local/bin/proxy-start.py
ENTRYPOINT ["python3", "/usr/local/bin/proxy-start.py"]
CMD ["-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg"]
