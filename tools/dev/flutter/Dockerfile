# The app's pinned Flutter image: cirruslabs/flutter (Android SDK, JDK, tools)
# with the Flutter SDK replaced by the official 3.47.9 release.
#
# Why: Flutter 3.44.0 cannot build iOS with Xcode 27 (its thinFramework calls
# `lipo -verify_arch arm64 x86_64`, which Xcode 27's lipo rejects); 3.44.9 and
# later verify each architecture on its own, and the app wants the current
# stable, 3.47.9 (Dart 3.13.7). cirruslabs publishes no 3.47.9 tag
# (its tags stop at 3.44.0, and `stable` is 3.44.0; checked again for 3.47.9), so the SDK comes from
# Google's release archive, checked against the SHA-256 in
# https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json
# (Dart 3.13.7, revision c197ca5199e9ee5661e865596c9c07294dfab51c).
# When cirruslabs publishes 3.47.9 (or later), this file can go and
# tools/docker_app.py and CI can pin that image by digest again.
FROM ghcr.io/cirruslabs/flutter:3.44.0@sha256:46691e311715845de03a3ba4753a475476936805b29431b1f00f1816981033f8

ARG FLUTTER_VERSION=3.47.9
ARG FLUTTER_SHA256=25ed8c3c29d51a7353f2a944310b478af8214920639524b19c50a19e6c044c5a

RUN set -eu \
    && curl -fsSL -o /tmp/flutter.tar.xz \
        "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
    && echo "${FLUTTER_SHA256}  /tmp/flutter.tar.xz" | sha256sum -c - \
    && rm -rf /sdks/flutter \
    && tar -xJf /tmp/flutter.tar.xz -C /sdks \
    && rm /tmp/flutter.tar.xz \
    && git config --global --add safe.directory /sdks/flutter \
    && flutter config --no-analytics --no-cli-animations \
    && flutter precache --android \
    && flutter --version
ENV FLUTTER_VERSION=${FLUTTER_VERSION}
