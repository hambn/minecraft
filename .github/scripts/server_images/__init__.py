"""Build, check and publish the Minecraft server images.

Run as ``PYTHONPATH=.github/scripts python -m server_images <command>``.  The
server assets this tooling reads (Dockerfiles, entrypoints, manifests, locks)
live in ``src/mc-server-images/``; see :mod:`server_images.config`.
"""
