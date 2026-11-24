// Restored from app/build.gradle.kts.backup (4 Sep 2026, 1585 bytes), which is
// this project's own original module build script. The live file was truncated
// to 0 bytes on 5 Sep 2026, ten minutes after the last successful build.
//
// Every value below is carried over from that backup UNCHANGED. The backup's
// numbers were cross-checked against the 5 Sep APK's own `aapt dump badging`
// (sdkVersion:'26', targetSdkVersion:'37', compileSdkVersion='37'), so they
// are confirmed from two independent artefacts rather than assumed.
//
// The ONLY additions are the CameraX and OkHttp dependencies at the bottom.
// Those are genuine additions, not restorations: the backup declares neither,
// yet the current MainActivity.kt imports both. See docs/PHASE4_ANDROID_RECOVERY.md.
//
// NOTE ON PLUGINS: there is deliberately no `org.jetbrains.kotlin.android`
// plugin here. The backup does not declare one either, and the 5 Sep APK
// nevertheless contains compiled Kotlin -- AGP 9.x provides built-in Kotlin
// support. Adding the standalone Kotlin plugin would be an unrequested
// toolchain change, so the original plugin set is preserved as-is.
plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.example.fyp3d"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.example.fyp3d"
        minSdk = 26
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
}

dependencies {
    // ---- Original Compose set, preserved verbatim from the backup ----------
    // MainActivity is View-based (the existing implementation it was repaired
    // from used FrameLayout/PreviewView, not Compose), but ui/theme/*.kt are
    // @Composable and are kept rather than deleted, so these stay required.
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    testImplementation(libs.junit)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)

    // ---- ADDED for Phase 4A: camera capture + WebSocket uplink ------------
    // CameraX 1.5.0: the version already resolved in this machine's Gradle
    // cache and present in the 5 Sep APK, so it is known to build against
    // AGP 9.4.0 / compileSdk 37. Its AAR declares minSdkVersion 23 <= our 26.
    // camera-video is deliberately NOT included -- no video recording is used,
    // and dropping it is what removes the need for RECORD_AUDIO.
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)

    // OkHttp 4.12.0 for the WebSocket client; Okio 3.6.0 is pinned explicitly
    // because MainActivity uses okio.ByteString directly rather than only
    // through OkHttp. 3.6.0 is exactly what okhttp 4.12.0's POM declares, so
    // the explicit pin cannot drag in a conflicting version.
    implementation(libs.okhttp)
    implementation(libs.okio)
}
