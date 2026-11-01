# The app's pinned Flutter image: cirruslabs/flutter (Android SDK, JDK, tools)
# with the Flutter SDK replaced by the official 3.44.9 release.
#
# Why: Flutter 3.44.0 cannot build iOS with Xcode 27 (its thinFramework calls
# `lipo -verify_arch arm64 x86_64`, which Xcode 27's lipo rejects); 3.44.9
# verifies each architecture on its own. cirruslabs publishes no 3.44.9 tag
# (its tags stop at 3.44.0, and `stable` is 3.44.0), so the SDK comes from
# Google's release archive, checked against the SHA-256 in
# https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json
# (Dart 3.12.2, revision 6b182d2c7585eba26d4edce0f97630effd256c33).
# When cirruslabs publishes 3.44.9 (or later), this file can go and
# tools/docker_app.py and CI can pin that image by digest again.
FROM ghcr.io/cirruslabs/flutter:3.44.0@sha256:46691e311715845de03a3ba4753a475476936805b29431b1f00f1816981033f8

ARG FLUTTER_VERSION=3.44.9
ARG FLUTTER_SHA256=a9120fa4a01048bdef438ddc3a2d4b7389662ea98a95db86eeaf10382bc4efcb

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
