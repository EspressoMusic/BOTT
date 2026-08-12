# This machine runs local HTTPS-inspecting software (Netspark) that MITMs all TLS
# connections, including to OANDA. certifi's bundled CA list doesn't know Netspark's
# root, so plain httpx/requests fail TLS verification. `truststore` makes Python use
# the OS certificate store instead (the same one Windows/schannel already trusts),
# so we verify against whatever the OS trusts rather than skipping verification.
# This must run before any ssl.SSLContext is created, so it lives at package import time.
import truststore

truststore.inject_into_ssl()
