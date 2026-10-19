// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// TEST ONLY. A certificate authority and a server certificate for
/// 127.0.0.1, made once for the on-device check-in test (check_in_test.dart):
/// the phone serves a stand-in field controller over HTTPS with them, so the
/// app's real pinning (lib/checkin/field_trust.dart) and HTTPS client run.
/// The private key is public here on purpose: it protects nothing and must
/// never be used for a real field (a real controller makes its own, tls.py).
library;

const testCaPem = '''
-----BEGIN CERTIFICATE-----
MIIBljCCATygAwIBAgIUW/UjuLVS1dUnYhEnhhx+UmBrBOswCgYIKoZIzj0EAwIw
NzE1MDMGA1UEAwwsQXRhbGFpYSBvbi1kZXZpY2UgdGVzdCBDQSAobm90IGEgcmVh
bCBmaWVsZCkwHhcNMjYxMDAxMDAwMDAwWhcNMzYwOTI4MDAwMDAwWjA3MTUwMwYD
VQQDDCxBdGFsYWlhIG9uLWRldmljZSB0ZXN0IENBIChub3QgYSByZWFsIGZpZWxk
KTBZMBMGByqGSM49AgEGCCqGSM49AwEHA0IABCSzlz255adlUX2JSgD05ndIWzka
OvsCrRMAMeuaa/UcfivdWIqrM5j9mBABVZTKlVSUq5rvjhbvCRd3NdXVje2jJjAk
MBIGA1UdEwEB/wQIMAYBAf8CAQAwDgYDVR0PAQH/BAQDAgEGMAoGCCqGSM49BAMC
A0gAMEUCIQCaLw85Sj0XhjyufglQtiOhxBJKOc8wTnEsxfNssQ5IOgIgS3bGGDm/
VjEeFyHAh8lXzmVvpjTpju44Lky/u+5/B0s=
-----END CERTIFICATE-----
''';

const testServerCertPem = '''
-----BEGIN CERTIFICATE-----
MIIBjzCCATSgAwIBAgIUHkE7O8BStK6heJ8Zl80CvucFF8EwCgYIKoZIzj0EAwIw
NzE1MDMGA1UEAwwsQXRhbGFpYSBvbi1kZXZpY2UgdGVzdCBDQSAobm90IGEgcmVh
bCBmaWVsZCkwHhcNMjYxMDAxMDAwMDAwWhcNMzYwOTI4MDAwMDAwWjAUMRIwEAYD
VQQDDAkxMjcuMC4wLjEwWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQMJcZnjIgv
Nk4ZsP5OoAmWH+khkvEc80/BTSdO+BdFvl6rgdVPf2ccTI8VzPTpKSCE/6yTMHZS
jJ2W2o4BIMNRo0EwPzAMBgNVHRMBAf8EAjAAMBoGA1UdEQQTMBGHBH8AAAGCCWxv
Y2FsaG9zdDATBgNVHSUEDDAKBggrBgEFBQcDATAKBggqhkjOPQQDAgNJADBGAiEA
1JZ8DKJTw9DiAgFc3m0+zT/8ZJ7x3QVeKMMKlPFQdUwCIQDn84e4Mn0rwIi4AUBq
RGF6CFEzBjdf6oHyMxcCagwMOA==
-----END CERTIFICATE-----
''';

const testServerKeyPem = '''
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgLTmdCRn2xRYqclwF
5nic6vQKRod7VRH4QImI+0IXq3WhRANCAAQMJcZnjIgvNk4ZsP5OoAmWH+khkvEc
80/BTSdO+BdFvl6rgdVPf2ccTI8VzPTpKSCE/6yTMHZSjJ2W2o4BIMNR
-----END PRIVATE KEY-----
''';
