#!/usr/bin/env python3
"""
Small no-cache HLS test server for local live_hls folders.

Usage:
  python hls_browser_debug_server.py --dir live_hls --port 8080

Then open:
  http://127.0.0.1:8080/index.html
"""

from __future__ import annotations

import argparse
import http.server
import mimetypes
import os
import socketserver
from pathlib import Path

INDEX_HTML = r'''<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Live HLS Debug Player</title>
  <style>
    body { margin: 0; background: #111; color: #eee; font-family: Arial, sans-serif; }
    main { max-width: 1100px; margin: 0 auto; padding: 18px; }
    video { width: 100%; max-height: 72vh; background: black; border: 1px solid #333; }
    pre { white-space: pre-wrap; background: #1b1b1b; padding: 12px; border-radius: 8px; border: 1px solid #333; }
    .ok { color: #76ff9f; }
    .bad { color: #ff7777; }
    .warn { color: #ffd166; }
  </style>
</head>
<body>
<main>
  <h2>Live HLS Debug Player</h2>
  <video id="video" controls autoplay muted playsinline></video>
  <h3>Status</h3>
  <pre id="log">Loading...</pre>
</main>

<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
<script>
const video = document.getElementById('video');
const logBox = document.getElementById('log');
const streamUrl = 'live.m3u8?cacheBust=' + Date.now();

function log(msg, cls='') {
  const prefix = new Date().toLocaleTimeString();
  logBox.innerHTML += `[${prefix}] ${cls ? '<span class="' + cls + '">' : ''}${msg}${cls ? '</span>' : ''}\n`;
}

async function checkPlaylist() {
  try {
    const r = await fetch(streamUrl, {cache: 'no-store'});
    log(`GET ${streamUrl} -> HTTP ${r.status}`, r.ok ? 'ok' : 'bad');
    if (!r.ok) return false;
    const txt = await r.text();
    log('Playlist content:\n' + txt.slice(0, 1200));
    if (!txt.includes('#EXTM3U')) log('This does not look like an HLS playlist.', 'bad');
    if (!txt.match(/\.ts|\.m4s|\.mp4/)) log('Playlist has no visible media segments yet.', 'warn');
    return true;
  } catch (e) {
    log('Could not fetch playlist: ' + e, 'bad');
    return false;
  }
}

(async () => {
  logBox.textContent = '';
  log('Starting HLS debug player...');
  const playlistOk = await checkPlaylist();

  if (!playlistOk) {
    log('The browser cannot load live.m3u8. Check that ffmpeg is creating it and that you started this server inside the live_hls folder.', 'bad');
    return;
  }

  if (window.Hls && Hls.isSupported()) {
    log('hls.js loaded and MediaSource is supported.', 'ok');
    const hls = new Hls({
      lowLatencyMode: true,
      liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 5,
      enableWorker: true,
      maxBufferLength: 10,
    });
    hls.on(Hls.Events.ERROR, function(event, data) {
      log(`hls.js error: type=${data.type}, details=${data.details}, fatal=${data.fatal}`, data.fatal ? 'bad' : 'warn');
      if (data.fatal) {
        try { hls.recoverMediaError(); log('Tried hls.recoverMediaError()', 'warn'); } catch(e) {}
      }
    });
    hls.on(Hls.Events.MANIFEST_PARSED, function() {
      log('Manifest parsed. Trying playback...', 'ok');
      video.play().then(() => log('video.play() OK', 'ok')).catch(e => log('video.play() blocked/failed: ' + e, 'warn'));
    });
    hls.on(Hls.Events.LEVEL_LOADED, function(event, data) {
      log(`Level loaded: live=${data.details.live}, fragments=${data.details.fragments.length}`, 'ok');
    });
    hls.loadSource(streamUrl);
    hls.attachMedia(video);
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    log('Using native browser HLS playback.', 'ok');
    video.src = streamUrl;
    video.addEventListener('loadedmetadata', () => video.play());
  } else {
    log('No hls.js and no native HLS support. If this lab PC has no internet, the CDN script did not load.', 'bad');
  }
})();
</script>
</body>
</html>
'''

class HLSHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def guess_type(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext == '.m3u8':
            return 'application/vnd.apple.mpegurl'
        if ext == '.ts':
            return 'video/mp2t'
        if ext == '.m4s':
            return 'video/iso.segment'
        if ext == '.mp4':
            return 'video/mp4'
        return super().guess_type(path)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()


def main():
    p = argparse.ArgumentParser(description='Serve an HLS folder with correct MIME/no-cache headers and auto-create index.html.')
    p.add_argument('--dir', default='live_hls', help='HLS folder containing live.m3u8')
    p.add_argument('--port', type=int, default=8080)
    p.add_argument('--bind', default='127.0.0.1')
    args = p.parse_args()

    root = Path(args.dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    index = root / 'index.html'
    if not index.exists():
        index.write_text(INDEX_HTML, encoding='utf-8')

    os.chdir(root)
    mimetypes.add_type('application/vnd.apple.mpegurl', '.m3u8')
    mimetypes.add_type('video/mp2t', '.ts')
    mimetypes.add_type('video/iso.segment', '.m4s')

    with socketserver.TCPServer((args.bind, args.port), HLSHandler) as httpd:
        print(f'[+] Serving {root}')
        print(f'[+] Open http://{args.bind}:{args.port}/index.html')
        print('[+] Press Ctrl+C to stop')
        httpd.serve_forever()

if __name__ == '__main__':
    main()
