plugins {
    id("com.android.application")
    kotlin("android")
}

android {
    compileSdk = 33
    namespace = "com.xcheng.scannere3"

    defaultConfig {
        applicationId = "com.xcheng.scannere3"
        minSdk = 23
        targetSdk = 33
        versionCode = 1
        versionName = "1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_1_8
        targetCompatibility = JavaVersion.VERSION_1_8
    }

    // Добавьте настройки для Kotlin
    kotlinOptions {
        jvmTarget = "1.8"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
}


dependencies {
    implementation(
        mapOf(
            "name" to "ru.atol.barcodeservice.api-release-1.5.32",
            "ext" to "aar"
        )
    )
    implementation("androidx.core:core-ktx:1.10.0")
    implementation("androidx.appcompat:appcompat:1.6.1")

    // WebView - встроен в платформу, доп. зависимостей не нужно
}

