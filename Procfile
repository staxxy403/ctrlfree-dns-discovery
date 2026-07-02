controller: python3 -u /app/src/main.py
coredns: sh -c "until [ -f /etc/coredns/Corefile ]; do sleep 1; done && exec /usr/local/bin/coredns -conf /etc/coredns/Corefile"