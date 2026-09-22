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
