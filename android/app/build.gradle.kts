import java.io.File

plugins {
    id("com.android.application")
}

android {
    namespace = "top.mayano.sweepy"
    compileSdk = 35

    defaultConfig {
        applicationId = "top.mayano.sweepy"
        minSdk = 26
        targetSdk = 35
        versionCode = (providers.gradleProperty("versionCode").orNull?.toIntOrNull()) ?: 1
        versionName = providers.gradleProperty("versionName").orNull ?: "2.0.0"
    }

    signingConfigs {
        val ksPath = System.getenv("ANDROID_KEYSTORE_PATH")
        if (!ksPath.isNullOrBlank() && File(ksPath).isFile) {
            create("release") {
                storeFile = File(ksPath)
                storePassword = System.getenv("ANDROID_KEYSTORE_PASS") ?: ""
                keyAlias = System.getenv("ANDROID_KEY_ALIAS") ?: ""
                keyPassword = System.getenv("ANDROID_KEY_PASS") ?: ""
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
            signingConfig = signingConfigs.findByName("release")
                ?: if (providers.gradleProperty("fallbackDebugSign").orNull == "true") {
                    signingConfigs.getByName("debug")
                } else {
                    null
                }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    sourceSets {
        getByName("main") {
            assets.directories.addAll(listOf("../../public", "../../sweepy/data"))
        }
    }

    packaging {
        resources {
            excludes += setOf(
                "META-INF/INDEX.LIST",
                "META-INF/*.kotlin_module",
                "META-INF/LICENSE*",
                "META-INF/NOTICE*",
            )
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(project(":core"))
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.squareup.okhttp3:okhttp:5.3.2")
}
