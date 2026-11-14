FROM dockurr/tor:0.4.9.17@sha256:c1637d01527fb78e8ba5132671e5607d7e267037756ee112fd33be4382822920
RUN apk add --no-cache python3 iptables iproute2 util-linux
COPY components/network/network.py components/network/tor-health.py components/network/onion.py /opt/
ENTRYPOINT ["python3", "/opt/network.py"]
