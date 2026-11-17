import groovy.json.JsonSlurper
import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// Single source of truth: reads shared ../app_config.json at Gradle build time
@Suppress("UNCHECKED_CAST")
val sharedAppConfig: Map<String, Any> = run {
    val cfgFile = rootProject.file("../app_config.json")
    if (cfgFile.exists()) {
        JsonSlurper().parse(cfgFile) as Map<String, Any>
    } else {
        emptyMap()
    }
}
@Suppress("UNCHECKED_CAST")
val androidCfg = (sharedAppConfig["android"] as? Map<String, Any>) ?: emptyMap()

val cfgAppName = (sharedAppConfig["app_name"] as? String) ?: "Universal Media Downloader"
val cfgShortName = (sharedAppConfig["short_name"] as? String) ?: "Universal Downloader"
val cfgVersionName = (sharedAppConfig["version_name"] as? String) ?: "2.5.0"
val cfgVersionCode = (sharedAppConfig["version_code"] as? Number)?.toInt() ?: 250
val cfgGithubOwner = (sharedAppConfig["github_owner"] as? String) ?: "Antony-Gh"
val cfgGithubRepo = (sharedAppConfig["github_repo"] as? String) ?: "Universal-Donwloader"
val cfgAppId = (androidCfg["application_id"] as? String) ?: "com.universaldownloader.app"
val cfgMinSdk = (androidCfg["min_sdk"] as? Number)?.toInt() ?: 24
val cfgTargetSdk = (androidCfg["target_sdk"] as? Number)?.toInt() ?: 35
val cfgCompileSdk = (androidCfg["compile_sdk"] as? Number)?.toInt() ?: 35
val cfgYtdlVersion = (androidCfg["youtubedl_android_version"] as? String) ?: "0.18.1"

android {
    namespace = "com.universaldownloader.app"
    compileSdk = cfgCompileSdk

    defaultConfig {
        applicationId = cfgAppId
        minSdk = cfgMinSdk
        targetSdk = cfgTargetSdk
        versionCode = cfgVersionCode
        versionName = cfgVersionName

        buildConfigField("String", "APP_NAME", "\"$cfgAppName\"")
        buildConfigField("String", "SHORT_NAME", "\"$cfgShortName\"")
        buildConfigField("String", "GITHUB_OWNER", "\"$cfgGithubOwner\"")
        buildConfigField("String", "GITHUB_REPO", "\"$cfgGithubRepo\"")

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        vectorDrawables {
            useSupportLibrary = true
        }
    }

    splits {
        abi {
            isEnable = true
            reset()
            include("arm64-v8a", "armeabi-v7a", "x86_64")
            isUniversalApk = true
        }
    }

    signingConfigs {
        create("release") {
            // Load local gitignored android/keystore.properties if present; CI environment variables take precedence
            val keystoreProps = Properties().apply {
                val propsFile = rootProject.file("keystore.properties")
                if (propsFile.exists()) {
                    propsFile.inputStream().use { load(it) }
                }
            }

            val rawStorePath = System.getenv("ANDROID_KEYSTORE_PATH")?.takeIf { it.isNotBlank() }
                ?: keystoreProps.getProperty("storeFile")
            val resolvedStoreFile = rawStorePath?.takeIf { it.isNotBlank() }?.let { p ->
                val direct = file(p)
                if (direct.exists()) direct else rootProject.file(p)
            }

            if (resolvedStoreFile != null && resolvedStoreFile.exists()) {
                storeFile = resolvedStoreFile
                storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")?.takeIf { it.isNotBlank() }
                    ?: keystoreProps.getProperty("storePassword")
                    ?: ""
                keyAlias = System.getenv("ANDROID_KEY_ALIAS")?.takeIf { it.isNotBlank() }
                    ?: keystoreProps.getProperty("keyAlias")
                    ?: ""
                keyPassword = System.getenv("ANDROID_KEY_PASSWORD")?.takeIf { it.isNotBlank() }
                    ?: keystoreProps.getProperty("keyPassword")
                    ?: ""
                enableV1Signing = true
                enableV2Signing = true
                enableV3Signing = true
            } else {
                // Fallback to standard debug signing so unconfigured builds remain directly installable
                initWith(getByName("debug"))
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("release")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        jniLibs {
            // Required for youtubedl-android to extract native Python & FFmpeg libraries on Android 10+
            useLegacyPackaging = true
        }
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.01")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    // Core AndroidX & Jetpack Compose Material 3
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // Async Thumbnail Loading
    implementation("io.coil-kt:coil-compose:2.7.0")

    // Native Embedded Python + yt-dlp + FFmpeg Engine
    implementation("io.github.junkfood02.youtubedl-android:library:$cfgYtdlVersion")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:$cfgYtdlVersion")

    // Debug & Testing
    debugImplementation("androidx.compose.ui:ui-tooling")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
    testImplementation("junit:junit:4.13.2")
}
