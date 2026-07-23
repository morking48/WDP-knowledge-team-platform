#!/usr/bin/env python
"""Filter base64 images from wecom-cli output (stdin)."""
import sys, re

text = sys.stdin.read()
# Remove base64 data URIs: data:image/png;base64,... 
# Also handles data:image/jpeg, data:image/gif, etc.
filtered = re.sub(r'data:image[^;]*;base64,[A-Za-z0-9+/=]{100,}', '[IMAGE_REMOVED]', text)
sys.stdout.write(filtered)
