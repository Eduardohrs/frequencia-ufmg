import java.util.Properties

plugins {
    id("com.android.application")
    id("dev.flutter.flutter-gradle-plugin")
    id("com.google.gms.google-services")
    id("com.google.firebase.crashlytics")
}

android {
    namespace = "br.ufmg.frequencia.frequencia_ufmg"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        applicationId = "br.ufmg.frequencia.frequencia_ufmg"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    val ciKeystorePath = System.getenv("ANDROID_DEBUG_KEYSTORE_PATH")
    if (ciKeystorePath != null) {
        signingConfigs.getByName("debug") {
            storeFile = file(ciKeystorePath)
            storePassword = System.getenv("ANDROID_DEBUG_KEYSTORE_PASSWORD")
            keyAlias = System.getenv("ANDROID_DEBUG_KEY_ALIAS")
            keyPassword = System.getenv("ANDROID_DEBUG_KEY_PASSWORD")
        }
    }

    buildTypes {
        release {
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

dependencies {
    // Expose the SDKs already shipped by FlutterFire to the native queue, using its locked BOM.
    val firebaseSdk = Properties().apply {
        rootProject.project(":firebase_core").file("gradle.properties").inputStream().use { load(it) }
    }.getProperty("FirebaseSDKVersion")
    implementation(platform("com.google.firebase:firebase-bom:$firebaseSdk"))
    implementation("com.google.firebase:firebase-auth")
    implementation("com.google.firebase:firebase-appcheck-playintegrity")
    implementation("androidx.work:work-runtime:2.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20250517")
}
