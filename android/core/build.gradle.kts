import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm")
}

java {
    sourceCompatibility = JavaVersion.VERSION_17
    targetCompatibility = JavaVersion.VERSION_17
}

kotlin {
    compilerOptions {
        jvmTarget.set(JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:5.3.2")
    implementation("org.msgpack:msgpack-core:0.9.12")
    implementation("com.google.code.gson:gson:2.15.0")
    implementation("com.google.zxing:core:3.5.4")

    testImplementation(kotlin("test"))
}

tasks.test {
    useJUnitPlatform()
}
