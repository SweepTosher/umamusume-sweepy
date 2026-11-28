import java.util.Properties

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "sweepy-android"
include(":core")

val localPropsFile = rootDir.resolve("local.properties")
val localSdkDir = if (localPropsFile.isFile) {
    Properties().apply { localPropsFile.inputStream().use { load(it) } }.getProperty("sdk.dir")
} else {
    null
}
val hasAndroidSdk = !System.getenv("ANDROID_HOME").isNullOrBlank()
    || !System.getenv("ANDROID_SDK_ROOT").isNullOrBlank()
    || !localSdkDir.isNullOrBlank()
    || providers.gradleProperty("includeApp").orNull == "true"

if (hasAndroidSdk) {
    include(":app")
}
