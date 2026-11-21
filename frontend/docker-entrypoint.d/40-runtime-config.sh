#!/bin/sh
# If API_URL is set, expose it to the SPA at runtime; otherwise the build-time VITE_API_URL is used.
set -e
if [ -n "$API_URL" ]; then
  printf 'window.__APP_CONFIG__ = { API_URL: "%s" };\n' "$API_URL" > /usr/share/nginx/html/config.js
fi
