// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The app module. Gradle builds the shared C core (../../../core) with the
// Android NDK for every ABI below and packs lib/<abi>/libatalaia_core.so into
// the APK, where lib/ffi/bindings.dart opens it (ADR-P3-1). The core is built
// with the same options as core/CMakePresets.json (app/tool/check.sh ndk):
// 64-bit Lua numbers as on the ESP32 (no LUA_32BITS), no mbedtls, no tests.

plugins {
    id("com.android.application")
    // The Flutter Gradle plugin must come after the Android and Kotlin plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// A release signing setting: the environment first, then the Gradle property.
fun releaseSetting(property: String, env: String): String? =
    System.getenv("ATALAIA_RELEASE_$env")?.takeIf { it.isNotBlank() }
        ?: (project.findProperty("atalaia.release.$property") as String?)?.takeIf { it.isNotBlank() }

val releaseSigningFound =
    listOf("storeFile" to "STORE_FILE", "storePassword" to "STORE_PASSWORD", "keyAlias" to "KEY_ALIAS",
        "keyPassword" to "KEY_PASSWORD").all { (p, e) -> releaseSetting(p, e) != null }
val releaseDebugSigned = (project.findProperty("atalaia.release.debugSigned") as String?) == "true"

android {
    namespace = "org.atalaia.app"
    compileSdk = 36
    // Pinned (the same in app/tool/check.sh); Gradle installs it if missing.
    ndkVersion = "28.2.13676358"

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "org.atalaia.app"
        // Android 8.0 (ADR constraint 24).
        minSdk = 26
        targetSdk = 36
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        // The host the site server's social-login return link (an App Link,
        // https://<host>/app/oidc) opens the app for (decision PKA-1; the
        // manifest needs it at build time): -Patalaia.appLinkHost=campo.example.pt,
        // or a wildcard such as *.hub.example.pt. The default matches nothing.
        manifestPlaceholders["appLinkHost"] =
            (project.findProperty("atalaia.appLinkHost") as String?) ?: "app-links.invalid"
        // The network policy (security review APP-3): cleartext HTTP only to the
        // few console addresses in res/xml/network_security_config.xml, or, with
        // -Patalaia.cleartextLan=true, to any address (the _lan file).
        manifestPlaceholders["networkSecurityConfig"] =
            if ((project.findProperty("atalaia.cleartextLan") as String?) == "true")
                "network_security_config_lan"
            else
                "network_security_config"

        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a", "x86_64")
        }
        externalNativeBuild {
            cmake {
                arguments += listOf("-DATALAIA_SHARED=ON", "-DATALAIA_MBEDTLS=OFF", "-DBUILD_TESTING=OFF")
                targets += "atalaia_core_shared"
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("../../../core/CMakeLists.txt")
            version = "3.22.1"
        }
    }

    signingConfigs {
        // The release key (security review APP-2). The key ceremony is the
        // maintainer's: nothing here makes, stores or defaults a keystore. Read
        // from the environment (ATALAIA_RELEASE_STORE_FILE, _STORE_PASSWORD,
        // _KEY_ALIAS, _KEY_PASSWORD) or from Gradle properties
        // (atalaia.release.storeFile, .storePassword, .keyAlias, .keyPassword,
        // for example in ~/.gradle/gradle.properties, never in the repository).
        if (releaseSigningFound) {
            create("release") {
                storeFile = file(releaseSetting("storeFile", "STORE_FILE")!!)
                storePassword = releaseSetting("storePassword", "STORE_PASSWORD")
                keyAlias = releaseSetting("keyAlias", "KEY_ALIAS")
                keyPassword = releaseSetting("keyPassword", "KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            // Never the debug key by accident: a debug-signed release has no
            // identity the site's assetlinks.json or a passkey's origin binding
            // can rely on (the sha256 of the signing certificate is what they
            // name). With no release keystore the build stops in
            // checkReleaseSigning below, unless -Patalaia.release.debugSigned=true
            // asks for a debug-signed build (CI smoke builds, a trial on a desk).
            signingConfig =
                if (releaseSigningFound) signingConfigs.getByName("release")
                else if (releaseDebugSigned) signingConfigs.getByName("debug")
                else null
        }
    }
}

// Stops a release build that has no release keystore (and did not ask for the
// debug key) with a message that says what to set, rather than building an
// unsigned or debug-signed APK nobody noticed. Debug builds never need it.
val checkReleaseSigning by tasks.registering {
    val found = releaseSigningFound
    val debugSigned = releaseDebugSigned
    doFirst {
        if (!found && !debugSigned) {
            throw GradleException(
                "No release keystore: set ATALAIA_RELEASE_STORE_FILE, ATALAIA_RELEASE_STORE_PASSWORD, " +
                    "ATALAIA_RELEASE_KEY_ALIAS and ATALAIA_RELEASE_KEY_PASSWORD (environment) or " +
                    "atalaia.release.storeFile, .storePassword, .keyAlias and .keyPassword (Gradle " +
                    "properties). For a build that is not for distribution, pass " +
                    "-Patalaia.release.debugSigned=true to sign it with the debug key on purpose. " +
                    "See app/README.md, \"Signing a release\"."
            )
        }
    }
}
tasks.matching { it.name == "preReleaseBuild" }.configureEach { dependsOn(checkReleaseSigning) }

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

// The QR scanner's own code (QrScanActivity.kt): CameraX for the camera
// (AndroidX, Apache-2.0) and ZXing's core library for the decoding
// (Apache-2.0, pure Java). Neither needs Google Play services (decision PD5).
// Pinned; change them together with app/README.md.
dependencies {
    implementation("androidx.activity:activity:1.13.0")
    implementation("androidx.camera:camera-camera2:1.6.2")
    implementation("androidx.camera:camera-lifecycle:1.6.2")
    implementation("androidx.camera:camera-view:1.6.2")
    implementation("com.google.zxing:core:3.5.4")
    // The social login's Custom Tab (BrowserPlugin.kt) and passkeys through the
    // Credential Manager (PasskeyPlugin.kt; the system's own providers from
    // Android 14, no Google Play services: decision PKA-1). AndroidX, Apache-2.0.
    implementation("androidx.browser:browser:1.9.0")
    implementation("androidx.credentials:credentials:1.5.0")
}

flutter {
    source = "../.."
}
