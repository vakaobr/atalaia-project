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

    buildTypes {
        release {
            // No release signing yet (plan phase G): release builds use the debug key.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
