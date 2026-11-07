#!/bin/sh
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Signs the unsigned release APK that `app/tool/check.sh apk-release` built, and checks it
# (decisions APK-1 to APK-8, APS-1 to APS-6). release.yml runs it in atalaia-flutter:3.47.9
# with `docker run --network none`: the keystore and its password are only ever in a container
# that has no network, and never in the build that downloads Gradle and pub dependencies.
#
#   ATALAIA_APK_IN                  the unsigned APK
#   ATALAIA_APK_OUT                 the folder the signed APK goes to
#   ATALAIA_APK_VERSION             the release's version: the signed APK is atalaia-app-<version>.apk
#   ATALAIA_APK_CERT_SHA256         the SHA-256 the signer's certificate must have (64 hex digits,
#                                   colons and case ignored)
#   ATALAIA_RELEASE_STORE_FILE      the PKCS12 keystore (mounted read-only)
#   ATALAIA_RELEASE_STORE_PASSWORD  its password (also the key's: PKCS12 has one)
#   ATALAIA_RELEASE_KEY_ALIAS       the key's alias (default atalaia)
#
# It refuses to run where it has a network interface other than the loopback. The APK is
# aligned with zipalign (4-byte entries, native libraries on 16 KB pages) only if it is not
# already, signed with apksigner, and then apksigner must say it verifies with exactly one
# signer whose certificate has ATALAIA_APK_CERT_SHA256, and zipalign must say it is still
# aligned, or nothing is written.
set -eu
in="${ATALAIA_APK_IN:?ATALAIA_APK_IN is not set}"
out="${ATALAIA_APK_OUT:?ATALAIA_APK_OUT is not set}"
version="${ATALAIA_APK_VERSION:?ATALAIA_APK_VERSION is not set}"
store="${ATALAIA_RELEASE_STORE_FILE:?ATALAIA_RELEASE_STORE_FILE is not set}"
: "${ATALAIA_RELEASE_STORE_PASSWORD:?ATALAIA_RELEASE_STORE_PASSWORD is not set}"
alias="${ATALAIA_RELEASE_KEY_ALIAS:-atalaia}"
want=$(printf '%s' "${ATALAIA_APK_CERT_SHA256:?ATALAIA_APK_CERT_SHA256 is not set}" | tr -d ':' | tr 'A-F' 'a-f')
printf '%s' "$want" | grep -Eqx '[0-9a-f]{64}' \
    || { echo "sign_apk.sh: ATALAIA_APK_CERT_SHA256 is not a SHA-256 fingerprint" >&2; exit 1; }
printf '%s' "$version" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?' \
    || { echo "sign_apk.sh: ATALAIA_APK_VERSION $version is not X.Y.Z[-pre]" >&2; exit 1; }
[ -f "$in" ] || { echo "sign_apk.sh: no APK at $in" >&2; exit 1; }
[ -f "$store" ] || { echo "sign_apk.sh: no keystore at $store" >&2; exit 1; }

# No network: the loopback must be the only interface (docker run --network none).
for dev in /sys/class/net/*; do
    [ "$(basename "$dev")" = lo ] && continue
    echo "sign_apk.sh: this container has the network interface $(basename "$dev"); run it with --network none" >&2
    exit 1
done
echo "ok   no network (only the loopback)"

# The newest build-tools (the image's SDK has them): zipalign -P needs 35 or later.
tools=$(ls -d "${ANDROID_HOME:?ANDROID_HOME is not set}"/build-tools/* 2>/dev/null | sort -V | tail -n 1)
[ -x "$tools/apksigner" ] && [ -x "$tools/zipalign" ] \
    || { echo "sign_apk.sh: no apksigner and zipalign in $ANDROID_HOME/build-tools" >&2; exit 1; }
echo "     build-tools $(basename "$tools")"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
if "$tools/zipalign" -c -P 16 4 "$in" > /dev/null 2>&1; then
    cp "$in" "$work/aligned.apk"
    echo "ok   the unsigned APK is already aligned"
else
    "$tools/zipalign" -P 16 -f 4 "$in" "$work/aligned.apk"
    echo "ok   aligned the unsigned APK"
fi

"$tools/apksigner" sign --ks "$store" --ks-type PKCS12 --ks-key-alias "$alias" \
    --ks-pass env:ATALAIA_RELEASE_STORE_PASSWORD --key-pass env:ATALAIA_RELEASE_STORE_PASSWORD \
    --out "$work/signed.apk" "$work/aligned.apk"

"$tools/apksigner" verify --verbose --print-certs "$work/signed.apk" > "$work/verify.txt" 2>&1 \
    || { cat "$work/verify.txt"; echo "sign_apk.sh: apksigner does not verify the signed APK" >&2; exit 1; }
grep -E '^Verified using|^Number of signers|certificate (DN|SHA-256)' "$work/verify.txt"
grep -qx 'Number of signers: 1' "$work/verify.txt" \
    || { echo "sign_apk.sh: the APK must have exactly one signer" >&2; exit 1; }
got=$(sed -n 's/^Signer #1 certificate SHA-256 digest: *//p' "$work/verify.txt" | tr 'A-F' 'a-f')
if [ "$got" != "$want" ]; then
    echo "sign_apk.sh: the APK is signed by certificate $got, not the release key $want" >&2
    exit 1
fi
echo "ok   signed by the certificate $got"
"$tools/zipalign" -c -P 16 4 "$work/signed.apk" > /dev/null \
    || { echo "sign_apk.sh: the signed APK is not aligned" >&2; exit 1; }
echo "ok   the signed APK is aligned (native libraries on 16 KB pages)"

cp "$work/signed.apk" "$out/atalaia-app-$version.apk"
echo "ok   wrote atalaia-app-$version.apk ($(wc -c < "$out/atalaia-app-$version.apk") bytes)"
