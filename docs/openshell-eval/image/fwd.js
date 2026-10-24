// fwd.js — ORCH-OPENSHELL-EVAL-1 spike. Inside an OpenShell sandbox `localhost` is the sandbox's own
// loopback, and policy never authorizes a loopback destination. This listens on the sandbox's
// 127.0.0.1/::1 for each port and dials host.openshell.internal:<port>, which policy can name, so SITs
// that hard-code localhost:8103 run unchanged. Usage: node /opt/toni/fwd.js 8103,3001,11434
const net = require('net');
const target = process.env.FWD_HOST || 'host.openshell.internal';
const ports = (process.argv[2] || '8103').split(',').map(Number);
for (const port of ports) {
  for (const addr of ['127.0.0.1', '::1']) {
    const srv = net.createServer((c) => {
      const up = net.connect(port, target);
      c.pipe(up); up.pipe(c);
      up.on('error', () => c.destroy()); c.on('error', () => up.destroy());
    });
    srv.on('error', (e) => console.error(`fwd ${addr}:${port} ${e.code}`));
    srv.listen(port, addr);
  }
}
