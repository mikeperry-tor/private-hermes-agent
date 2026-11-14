# Official stable image: Tailscale 1.104.7.
FROM tailscale/tailscale@sha256:72c1e19e0aedca96b8533bbb0b4368564410ff20b17e53b804eb6c1f04a31be4
RUN apk add --no-cache python3
COPY components/tailscale/funnel.py /opt/funnel.py
ENTRYPOINT ["python3", "/opt/funnel.py"]
